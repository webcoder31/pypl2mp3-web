"""Importing a playlist, without touching YouTube."""

from pathlib import Path

import pytest

from pypl2mp3.services import import_playlist as mod
from pypl2mp3.services.import_playlist import ImportReport, import_playlist

from tests.doubles import FakeProgress

PLAYLIST_ID = "PLP6XxNg42qDGMg1cR2PPPzwdoAOD1MQ97"
REMOTE_IDS = ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"]

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


class _FakePlaylist:
    def __init__(self, url, *args, **kwargs):
        self.title = "fake"
        self.owner = "owner"
        self.length = len(REMOTE_IDS)
        self.video_urls = [
            f"https://www.youtube.com/watch?v={vid}" for vid in REMOTE_IDS
        ]


class _FakeYouTube:
    def __init__(self, url, *args, **kwargs):
        self.video_id = url.rsplit("=", 1)[-1]
        self.author = "ARTIST"
        self.title = "Title"


class _FakeSong:
    """What create_from_youtube hands back, reduced to what we read."""

    def __init__(self, youtube_id):
        self.filename = f"ARTIST - Title [{youtube_id}].mp3"
        self.artist = "ARTIST"
        self.title = "Title"
        self.shazam_match_score = 66.0
        self.has_junk_filename = False


def _folder(repo: Path) -> Path:
    return repo / f"owner - fake [{PLAYLIST_ID}]"


def _make_local(repo: Path, present: list[str]) -> None:
    folder = _folder(repo)
    folder.mkdir(parents=True, exist_ok=True)
    for vid in present:
        (folder / f"ARTIST - Title [{vid}].mp3").write_bytes(_MP3_FRAME * 8)


def _install_fakes(monkeypatch, create=None):
    monkeypatch.setattr(mod, "DEFAULT_REQUEST_INTERVAL", 0.0)
    monkeypatch.setattr(mod, "Playlist", _FakePlaylist)
    monkeypatch.setattr(mod, "YouTube", _FakeYouTube)

    async def default_create(youtube_id, playlist_path, threshold, **kwargs):
        (playlist_path / f"ARTIST - Title [{youtube_id}].mp3").write_bytes(
            _MP3_FRAME * 8
        )
        return _FakeSong(youtube_id)

    monkeypatch.setattr(
        mod.SongModel, "create_from_youtube", create or default_create
    )


async def test_it_imports_only_what_is_missing(tmp_path, monkeypatch):
    _install_fakes(monkeypatch)
    _make_local(tmp_path, ["AAAAAAAAAAA"])

    report = await import_playlist(tmp_path, PLAYLIST_ID, FakeProgress())

    assert isinstance(report, ImportReport)
    assert report.total_remote == 3
    assert report.already_local == 1
    assert sorted(song.youtube_id for song in report.imported) == [
        "BBBBBBBBBBB",
        "CCCCCCCCCCC",
    ]
    assert report.failed == []


async def test_it_reports_nothing_to_do_when_local_is_complete(
    tmp_path, monkeypatch
):
    _install_fakes(monkeypatch)
    _make_local(tmp_path, REMOTE_IDS)

    report = await import_playlist(tmp_path, PLAYLIST_ID, FakeProgress())

    assert report.imported == []
    assert report.already_local == 3


async def test_one_failing_song_does_not_abort_the_others(
    tmp_path, monkeypatch
):
    """A dropped connection on song 2 used to lose songs 3 through 34."""

    async def flaky(youtube_id, playlist_path, threshold, **kwargs):
        if youtube_id == "BBBBBBBBBBB":
            raise RuntimeError("network down")
        (playlist_path / f"ARTIST - Title [{youtube_id}].mp3").write_bytes(
            _MP3_FRAME * 8
        )
        return _FakeSong(youtube_id)

    _install_fakes(monkeypatch, create=flaky)
    _make_local(tmp_path, [])

    report = await import_playlist(tmp_path, PLAYLIST_ID, FakeProgress())

    assert sorted(song.youtube_id for song in report.imported) == [
        "AAAAAAAAAAA",
        "CCCCCCCCCCC",
    ]
    assert len(report.failed) == 1
    assert report.failed[0].youtube_id == "BBBBBBBBBBB"
    assert "network down" in report.failed[0].issue


async def test_each_song_is_announced_with_its_position(
    tmp_path, monkeypatch
):
    """Sub-stage events carry no song identity; this is what attributes them."""

    _install_fakes(monkeypatch)
    _make_local(tmp_path, [])
    progress = FakeProgress()

    await import_playlist(tmp_path, PLAYLIST_ID, progress)

    labels = [
        event[2]
        for event in progress.events
        if event[0] == "stage_started" and event[1] == "song"
    ]
    assert "1/3 ARTIST - Title" in labels
    assert "3/3 ARTIST - Title" in labels


async def test_an_unreachable_playlist_raises_rather_than_reporting_zero(
    tmp_path, monkeypatch
):
    class _Failing:
        def __init__(self, url, *args, **kwargs):
            raise RuntimeError("network down")

    monkeypatch.setattr(mod, "Playlist", _Failing)
    _make_local(tmp_path, [])

    with pytest.raises(Exception):
        await import_playlist(tmp_path, PLAYLIST_ID, FakeProgress())


async def test_a_lazy_attribute_failure_is_attributed_to_its_song(
    tmp_path, monkeypatch
):
    """pytubefix fails on attribute access, not in the constructor."""

    class _LazyFailing:
        def __init__(self, url, *args, **kwargs):
            self.video_id = url.rsplit("=", 1)[-1]

        @property
        def author(self):
            raise RuntimeError("network down")

        @property
        def title(self):
            return "Title"

    _install_fakes(monkeypatch)
    monkeypatch.setattr(mod, "YouTube", _LazyFailing)
    _make_local(tmp_path, [])

    report = await import_playlist(tmp_path, PLAYLIST_ID, FakeProgress())

    assert report.imported == []
    assert len(report.failed) == 3, "each song should fail on its own"


def test_it_recognises_a_refusal_and_not_a_broken_video():
    """Backing off is only right when YouTube refused, not when a video is bad."""

    from pytubefix.exceptions import PytubeFixError

    from pypl2mp3.services.import_playlist import looks_rate_limited

    refusals = [
        Exception("2VuNyY6RLpA This request was detected as a bot."),
        Exception("HTTP Error 429: Too Many Requests"),
        PytubeFixError("too many requests"),
    ]
    for error in refusals:
        assert looks_rate_limited(error), error

    others = [
        RuntimeError("Remote end closed connection without response"),
        Exception("age restricted, and can't be accessed without logging in"),
        Exception("Failed to encode audio stream to MP3"),
    ]
    for error in others:
        assert not looks_rate_limited(error), error


async def test_it_leaves_a_gap_between_songs(tmp_path, monkeypatch):
    """Nothing paced YouTube while Shazam was paced 15s; that asymmetry
    is what got 20 of 34 songs refused."""

    import time as clock

    _install_fakes(monkeypatch)
    _make_local(tmp_path, [])
    stamps: list[float] = []

    async def stamped(youtube_id, playlist_path, threshold, **kwargs):
        stamps.append(clock.monotonic())
        (playlist_path / f"ARTIST - Title [{youtube_id}].mp3").write_bytes(
            _MP3_FRAME * 8
        )
        return _FakeSong(youtube_id)

    monkeypatch.setattr(mod.SongModel, "create_from_youtube", stamped)

    await import_playlist(
        tmp_path, PLAYLIST_ID, FakeProgress(), request_interval=0.3
    )

    assert len(stamps) == 3
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(gap >= 0.25 for gap in gaps), f"songs were not spaced: {gaps}"


async def test_a_refusal_widens_the_gap(tmp_path, monkeypatch):
    """Charging on at the same rate after a refusal just collects more."""

    from pypl2mp3.services.import_playlist import _Pacer

    pacer = _Pacer(4.0)
    assert pacer.interval == 4.0

    pacer.penalise()
    assert pacer.interval == 8.0

    for _ in range(10):
        pacer.penalise()
    assert pacer.interval == 32.0, "the backoff must stay bounded"


async def test_an_ordinary_failure_does_not_widen_the_gap(
    tmp_path, monkeypatch
):
    """A broken video is not YouTube telling us to slow down."""

    from pypl2mp3.services.import_playlist import _Pacer

    seen: list[float] = []
    original = _Pacer.penalise

    def spy(self):
        seen.append(self.interval)
        original(self)

    monkeypatch.setattr(_Pacer, "penalise", spy)

    async def broken(youtube_id, playlist_path, threshold, **kwargs):
        raise RuntimeError("Failed to encode audio stream to MP3")

    _install_fakes(monkeypatch, create=broken)
    _make_local(tmp_path, [])

    report = await import_playlist(tmp_path, PLAYLIST_ID, FakeProgress())

    assert len(report.failed) == 3
    assert seen == [], "an encoding failure must not trigger a backoff"


def test_the_default_actually_spaces_requests():
    """Setting the default to zero would silently restore the old behaviour.

    The test above passes an explicit interval, so it proves the mechanism
    works but says nothing about what an unconfigured import does — which
    is the only thing the browser ever triggers.
    """

    from pypl2mp3.services.import_playlist import (
        DEFAULT_REQUEST_INTERVAL,
        MAX_REQUEST_INTERVAL,
    )

    assert DEFAULT_REQUEST_INTERVAL > 0, (
        "an unpaced import had 20 of 34 songs refused by YouTube"
    )
    assert MAX_REQUEST_INTERVAL > DEFAULT_REQUEST_INTERVAL


async def test_a_real_refusal_triggers_the_backoff(tmp_path, monkeypatch):
    """The isolated _Pacer test proves penalise works, not that it is called."""

    from pypl2mp3.services.import_playlist import _Pacer

    widened: list[float] = []
    original = _Pacer.penalise

    def spy(self):
        widened.append(self.interval)
        original(self)

    monkeypatch.setattr(_Pacer, "penalise", spy)

    # penalise() floors at 1s before doubling, so even a tiny starting
    # interval reaches seconds after two refusals. We are testing that the
    # backoff fires, not that sleeping works.
    async def no_wait(_seconds):
        return None

    monkeypatch.setattr(mod.asyncio, "sleep", no_wait)

    async def refused(youtube_id, playlist_path, threshold, **kwargs):
        raise Exception(f"{youtube_id} This request was detected as a bot.")

    _install_fakes(monkeypatch, create=refused)
    _make_local(tmp_path, [])

    report = await import_playlist(
        tmp_path, PLAYLIST_ID, FakeProgress(), request_interval=0.01
    )

    assert len(report.failed) == 3
    assert len(widened) == 3, (
        "every refusal should widen the gap; got "
        f"{len(widened)} backoffs for 3 refusals"
    )
