"""Filling the library with vectors: at import, and in bulk."""

import asyncio
import threading
from pathlib import Path

import httpx
from mutagen.id3 import ID3, TXXX

from pypl2mp3.libs.features import FEATURE_COUNT
from pypl2mp3.web.app import create_app

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"
_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _song(repo: Path, vid: str) -> Path:
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"ARTIST - Title [{vid}].mp3"
    path.write_bytes(_MP3_FRAME * 8)
    frames = ID3()
    frames.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
    frames.save(path)
    return path


async def _settled(client, job_id="features"):
    """Poll a job until it stops running, as the pane does."""

    for _ in range(200):
        state = (await client.get(f"/jobs/{job_id}")).json()
        if state["state"] in ("completed", "failed", "cancelled"):
            return state
        await asyncio.sleep(0.02)

    raise AssertionError(f"job never settled: {state}")


async def test_the_bulk_job_writes_a_vector_into_every_song(
    tmp_path, monkeypatch
):
    from pypl2mp3.web import app as web

    for vid in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
        _song(tmp_path, vid)

    # The extractor has its own tests; this one is about the job.
    seen = []
    monkeypatch.setattr(
        web, "features_for",
        lambda path: (seen.append(path), [1.0] * FEATURE_COUNT)[1],
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(tmp_path)),
        base_url="http://test",
    ) as client:
        started = await client.post("/features/analyse")
        assert started.status_code == 200, started.text

        state = await _settled(client)

    assert state["state"] == "completed", state
    assert state["result"] == {"analysed": 2, "failed": 0, "total": 2}
    assert len(seen) == 2


async def test_a_song_that_cannot_be_analysed_does_not_fail_the_run(
    tmp_path, monkeypatch
):
    """One unreadable file out of 944 must not cost the other 943."""

    from pypl2mp3.libs.features import FeatureError
    from pypl2mp3.web import app as web

    _song(tmp_path, "aaaaaaaaaaa")
    _song(tmp_path, "bbbbbbbbbbb")

    def refuse(path):
        if "bbbbbbbbbbb" in path.name:
            raise FeatureError("nope")
        return [1.0] * FEATURE_COUNT

    monkeypatch.setattr(web, "features_for", refuse)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(tmp_path)),
        base_url="http://test",
    ) as client:
        await client.post("/features/analyse")
        state = await _settled(client)

    assert state["state"] == "completed", state
    assert state["result"] == {"analysed": 1, "failed": 1, "total": 2}


async def test_asking_twice_joins_the_run_rather_than_starting_a_second(
    tmp_path, monkeypatch
):
    """Two passes over the same 944 files, each rewriting the same tags,
    is how a library gets a half-written MP3 in it."""

    from pypl2mp3.web import app as web

    _song(tmp_path, "aaaaaaaaaaa")
    monkeypatch.setattr(web, "features_for",
                        lambda path: [1.0] * FEATURE_COUNT)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(tmp_path)),
        base_url="http://test",
    ) as client:
        first = await client.post("/features/analyse")
        second = await client.post("/features/analyse")

        assert second.status_code == 200, second.text
        assert second.json()["job_id"] == first.json()["job_id"]

        await _settled(client)


async def test_two_songs_are_analysed_at_the_same_time(tmp_path, monkeypatch):
    """The whole loop used to sit inside one `asyncio.to_thread`, so 944
    songs were decoded one after another: measured on the real library,
    3.49s each on one thread against 1.34s on four — forty minutes
    against fifteen. The pass is meant to be re-run, too: the frame's
    owner carries a version precisely so that changing how a feature is
    computed makes every existing frame invisible.

    A barrier rather than a sleep and a hopeful assertion. Two songs
    must be in flight at once for either to get past it, which a
    sequential loop cannot do at any speed.
    """

    from pypl2mp3.web import app as web

    for vid in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
        _song(tmp_path, vid)

    # Short enough that a sequential loop breaks the barrier and lets
    # the job settle, so the failure read here is the one below and not
    # `_settled` giving up with nothing to say.
    together = threading.Barrier(2, timeout=2)
    threads = set()

    def wait_for_the_other(path):
        threads.add(threading.current_thread().ident)
        together.wait()
        return [1.0] * FEATURE_COUNT

    monkeypatch.setattr(web, "features_for", wait_for_the_other)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(tmp_path)),
        base_url="http://test",
    ) as client:
        await client.post("/features/analyse")
        state = await _settled(client)

    assert state["result"] == {"analysed": 2, "failed": 0, "total": 2}, (
        "neither song got through the barrier, so they never overlapped"
    )
    assert len(threads) == 2, threads


async def test_the_pool_does_not_grow_with_the_library(tmp_path, monkeypatch):
    """A thread per song is 944 threads, 944 ffmpeg processes and a
    machine that stops answering. The cap is fixed and small: past four
    the gain is measured in hundredths and the console it shares the
    processor with is what pays for them."""

    from pypl2mp3.web.app import ANALYSIS_THREADS
    from pypl2mp3.web import app as web

    for at in range(24):
        _song(tmp_path, f"song{at:07d}")

    threads = set()
    busy = threading.Event()

    def note(path):
        threads.add(threading.current_thread().ident)
        # Long enough that the pool has every reason to open another
        # thread if it is allowed to.
        busy.wait(0.02)
        return [1.0] * FEATURE_COUNT

    monkeypatch.setattr(web, "features_for", note)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(tmp_path)),
        base_url="http://test",
    ) as client:
        await client.post("/features/analyse")
        state = await _settled(client)

    assert state["result"]["analysed"] == 24
    assert len(threads) <= ANALYSIS_THREADS, threads


def test_the_import_asks_for_a_vector_without_depending_on_one():
    """Best effort, exactly like the waveform beside it: a vector that
    cannot be computed is not a failed import."""

    source = Path("src/pypl2mp3/services/import_playlist.py").read_text()

    # Called, and not merely defined: a helper nobody reaches leaves
    # every imported song without a vector until the bulk job is run by
    # hand, which is a thing nobody would think to do.
    assert "_store_features, song.path" in source, (
        "the import never analyses anything"
    )
    assert "_store_waveform, song.path" in source, (
        "the waveform call this one stands beside has moved"
    )

    block = source[source.index("def _store_features"):]
    block = block[:block.index("\n\n\n")]
    assert "features_for" in block, block
    assert "except Exception" in block, block
