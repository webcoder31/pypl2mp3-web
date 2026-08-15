"""Waveform peaks: the reduction, the ID3 frame, and the endpoint.

The reduction is tested on synthesized samples rather than on decoded
MP3s. It is the part that carries a design decision — absolute loudness,
not normalized — and testing it directly says so without ffmpeg in the
way.
"""

import asyncio
from pathlib import Path
import struct
import threading
import time

import httpx
import mutagen.mp3
import pytest
from mutagen.id3 import PRIV, TIT2

from pypl2mp3.libs import waveform
from pypl2mp3.libs.waveform import (
    PEAK_COUNT,
    PEAK_OWNER,
    WaveformError,
    peaks_for,
    read_peaks,
    reduce_to_peaks,
    store_peaks,
)
from pypl2mp3.web.app import create_app

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _make_song(repo: Path, artist, title, vid, junk=False, playlist=PLAYLIST):
    folder = repo / playlist
    folder.mkdir(parents=True, exist_ok=True)
    suffix = " (JUNK)" if junk else ""
    (folder / f"{artist} - {title} [{vid}]{suffix}.mp3").write_bytes(
        _MP3_FRAME * 8
    )


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def _pcm(*runs) -> bytes:
    """Raw samples from (amplitude, sample count) pairs."""

    return b"".join(
        struct.pack("<h", amplitude) * count for amplitude, count in runs
    )


def _song(tmp_path):
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    return next(tmp_path.rglob("*.mp3"))


def test_every_bar_gets_a_value():
    peaks = reduce_to_peaks(_pcm((10000, 100_000)))

    assert len(peaks) == PEAK_COUNT


def test_a_loud_stretch_reads_louder_than_a_quiet_one():
    """The whole point: the picture has to follow the sound."""

    half = 50_000
    peaks = reduce_to_peaks(_pcm((30000, half), (300, half)))

    assert peaks[0] > peaks[-1], (peaks[0], peaks[-1])
    assert peaks[0] > 200, f"a loud passage draws short: {peaks[0]}"
    assert peaks[-1] < 20, f"a quiet passage draws tall: {peaks[-1]}"


def test_a_quiet_song_stays_quiet():
    """Absolute, not normalized to each song's own loudest moment.

    Normalizing would fill every waveform to the top and throw away the
    one reading worth having — a download that came out near-silent
    should look near-silent, not like a normal song.
    """

    tenth = int(32768 * 0.1)
    peaks = reduce_to_peaks(_pcm((tenth, 100_000)))

    assert max(peaks) < 40, (
        f"a song at a tenth of full scale draws at {max(peaks)}/255, so the "
        "bars are being stretched to fill the height"
    )


def test_audio_shorter_than_the_bar_count_leaves_the_rest_silent():
    """Not repeated across the remaining bars, which would draw sound
    that is not there."""

    peaks = reduce_to_peaks(_pcm((32000, 10)))

    assert peaks[0] > 0
    assert peaks[-1] == 0, "the last bar shows audio the file does not have"
    assert len(peaks) == PEAK_COUNT


def test_peaks_survive_a_round_trip_through_the_file(tmp_path):
    song = _song(tmp_path)
    written = bytes(range(256)) + bytes(PEAK_COUNT - 256)

    store_peaks(song, written)

    assert read_peaks(mutagen.mp3.MP3(song)) == written


def test_a_file_without_peaks_reports_none(tmp_path):
    assert read_peaks(mutagen.mp3.MP3(_song(tmp_path))) is None


def test_a_frame_of_the_wrong_size_is_ignored(tmp_path):
    """The version guard's second half.

    Changing PEAK_COUNT must make old frames invisible rather than draw
    a waveform with the wrong number of bars.
    """

    song = _song(tmp_path)
    mp3 = mutagen.mp3.MP3(song)
    mp3.add_tags()
    mp3.tags.add(PRIV(owner=PEAK_OWNER, data=b"\x40" * (PEAK_COUNT - 1)))
    mp3.save(v1=0, v2_version=3)

    assert read_peaks(mutagen.mp3.MP3(song)) is None


def test_writing_peaks_keeps_another_application_s_private_frame(tmp_path):
    """delall takes a frame type, not an owner. Getting this wrong would
    silently strip whatever else wrote a PRIV frame into the file."""

    song = _song(tmp_path)
    mp3 = mutagen.mp3.MP3(song)
    mp3.add_tags()
    mp3.tags.add(PRIV(owner="some-other-tool", data=b"do not lose me"))
    mp3.save(v1=0, v2_version=3)

    store_peaks(song, b"\x10" * PEAK_COUNT)

    frames = {f.owner: f.data for f in mutagen.mp3.MP3(song).tags.getall("PRIV")}
    assert frames.get("some-other-tool") == b"do not lose me"
    assert len(frames[PEAK_OWNER]) == PEAK_COUNT


def test_writing_peaks_keeps_the_music_tags(tmp_path):
    song = _song(tmp_path)
    mp3 = mutagen.mp3.MP3(song)
    mp3.add_tags()
    mp3.tags.add(TIT2(encoding=1, text=["Kick, Push"]))
    mp3.save(v1=0, v2_version=3)

    store_peaks(song, b"\x10" * PEAK_COUNT)

    assert mutagen.mp3.MP3(song).tags["TIT2"].text == ["Kick, Push"]


def test_writing_peaks_only_replaces_its_own(tmp_path):
    """Stored twice, the file must not end up carrying two waveforms."""

    song = _song(tmp_path)
    store_peaks(song, b"\x10" * PEAK_COUNT)
    store_peaks(song, b"\x20" * PEAK_COUNT)

    ours = [
        f for f in mutagen.mp3.MP3(song).tags.getall("PRIV")
        if f.owner == PEAK_OWNER
    ]
    assert len(ours) == 1, f"{len(ours)} waveforms in one file"
    assert ours[0].data == b"\x20" * PEAK_COUNT


def test_the_song_is_decoded_once_and_read_back_after(tmp_path, monkeypatch):
    """Half a second of ffmpeg per play would be paid on every play."""

    song = _song(tmp_path)
    calls = []
    real = waveform.extract_pcm
    monkeypatch.setattr(
        waveform, "extract_pcm", lambda p: (calls.append(p), real(p))[1]
    )

    first = peaks_for(song)
    second = peaks_for(song)

    assert first == second
    assert len(calls) == 1, f"decoded {len(calls)} times"


def test_a_file_that_cannot_be_written_still_serves_its_waveform(
    tmp_path, monkeypatch
):
    """The file is a cache, not the source of truth. A read-only
    repository must still get a waveform, just not a stored one."""

    song = _song(tmp_path)

    def refuse(*args):
        raise PermissionError("read-only")

    monkeypatch.setattr(waveform, "store_peaks", refuse)

    assert len(peaks_for(song)) == PEAK_COUNT


def test_an_undecodable_file_says_so(tmp_path):
    song = _song(tmp_path)
    song.write_bytes(b"this is not an mp3")

    with pytest.raises(WaveformError):
        peaks_for(song)


async def test_the_endpoint_serves_one_value_per_bar(tmp_path):
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/songs/aaaaaaaaaaa/peaks")).json()

    assert len(body) == PEAK_COUNT
    assert all(0 <= value <= 1 for value in body), (
        "the wire format is 0 to 1; the canvas would draw off its own top"
    )


async def test_an_unknown_song_has_no_peaks(tmp_path):
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        response = await client.get("/songs/zzzzzzzzzzz/peaks")

    assert response.status_code == 404


async def test_an_undecodable_song_returns_404_not_500(tmp_path):
    """The player falls back to the plain bar, which seeks just as well.
    A 500 would put a stack trace in the console on every play."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")
    next(tmp_path.rglob("*.mp3")).write_bytes(b"not an mp3")

    async with _client(create_app(tmp_path)) as client:
        response = await client.get("/songs/aaaaaaaaaaa/peaks")

    assert response.status_code == 404


async def test_simultaneous_requests_decode_the_song_once(tmp_path):
    """Two clicks, or a reload racing the player, would otherwise each
    run ffmpeg and each write the file — and one write could land on
    top of the other."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    calls = []
    guard = threading.Lock()

    def slow(path):
        with guard:
            calls.append(path)
        # Long enough that the later requests arrive while this one runs.
        time.sleep(0.2)

        return b"\x33" * PEAK_COUNT

    app = create_app(tmp_path)
    import pypl2mp3.web.app as app_module

    original = app_module.peaks_for
    app_module.peaks_for = slow
    try:
        async with _client(app) as client:
            responses = await asyncio.gather(
                *(client.get("/songs/aaaaaaaaaaa/peaks") for _ in range(5))
            )
    finally:
        app_module.peaks_for = original

    assert [r.status_code for r in responses] == [200] * 5
    assert len(calls) == 1, f"decoded {len(calls)} times for one song"
