"""The 15s gap between Shazam calls, under concurrency.

It is enforced by reading a timestamp and then sleeping. That is not
mutual exclusion: two coroutines can both measure the same gap, both
decide they may go, and both fire. It went unnoticed while one caller
existed at a time; identifying songs ahead of the one on screen creates
a second.
"""

import asyncio
from pathlib import Path

import pytest
from mutagen.id3 import ID3, TXXX

from pypl2mp3.libs.song import SongModel

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _make_song(folder: Path, vid: str) -> SongModel:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"ARTIST - Title [{vid}].mp3"
    path.write_bytes(_MP3_FRAME * 8)

    frames = ID3()
    frames.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
    frames.save(path)

    return SongModel(path)


@pytest.fixture
def instant_sleep(monkeypatch):
    """Let the throttle's waits pass without spending them.

    What is under test is whether callers overlap, not how long they
    wait — a real 15s pause would make this a minute-long test.
    """

    waits = []
    real_sleep = asyncio.sleep

    async def fake(seconds, *args, **kwargs):
        waits.append(seconds)
        # Yield to the loop so a competing task genuinely gets a turn:
        # a no-op would let the caller run straight through and hide the
        # very interleaving this exists to provoke.
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake)

    return waits


@pytest.fixture(autouse=True)
def fresh_throttle(monkeypatch):
    monkeypatch.setattr(SongModel, "last_shazam_request_time", 0)


async def test_two_identifications_never_overlap(tmp_path, instant_sleep):
    inside = 0
    overlapped = False

    async def recognize(path):
        nonlocal inside, overlapped
        inside += 1
        if inside > 1:
            overlapped = True
        # Force a suspension point: without one the call would never be
        # interrupted and the test could not fail even unguarded.
        await asyncio.sleep(0)
        inside -= 1
        return {}

    class FakeShazam:
        recognize_song = staticmethod(recognize)

    songs = [
        _make_song(tmp_path / "pl", f"vid{i:07d}") for i in range(4)
    ]
    for song in songs:
        song.shazam_client = FakeShazam()

    await asyncio.gather(*(song.shazam_song() for song in songs))

    assert not overlapped, "two Shazam requests were in flight at once"


async def test_the_gap_is_measured_from_the_previous_call(
    tmp_path, instant_sleep
):
    """Each caller after the first must wait, not just the second."""

    async def recognize(path):
        return {}

    class FakeShazam:
        recognize_song = staticmethod(recognize)

    songs = [_make_song(tmp_path / "pl", f"vid{i:07d}") for i in range(3)]
    for song in songs:
        song.shazam_client = FakeShazam()

    await asyncio.gather(*(song.shazam_song() for song in songs))

    # The first call finds a zero timestamp and goes straight through.
    # The other two each wait out most of the interval.
    waited = [seconds for seconds in instant_sleep if seconds > 14]
    assert len(waited) == 2, instant_sleep


async def test_a_failing_call_does_not_strand_the_lock(
    tmp_path, instant_sleep
):
    """A raise inside the guarded block must still release it, or the
    first bad song would freeze every identification after it."""

    calls = 0

    async def recognize(path):
        nonlocal calls
        calls += 1
        raise RuntimeError("shazam is down")

    class FakeShazam:
        recognize_song = staticmethod(recognize)

    song = _make_song(tmp_path / "pl", "aaaaaaaaaaa")
    song.shazam_client = FakeShazam()

    with pytest.raises(Exception):
        await song.shazam_song()

    assert calls == 2, "the retry did not run"
    assert not SongModel.shazam_lock().locked(), "the lock was never released"

    # And the next song still gets through.
    async def works(path):
        return {}

    other = _make_song(tmp_path / "pl", "bbbbbbbbbbb")
    other.shazam_client = type("S", (), {"recognize_song": staticmethod(works)})()

    await asyncio.wait_for(other.shazam_song(), timeout=5)
