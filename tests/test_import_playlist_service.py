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
    """What create_from_youtube hands back, reduced to what we read.

    `path` included: the real SongModel has always had one, and the
    import now stores the song's waveform through it. A double that
    leaves it off lets that kind of change land with the suite green.
    """

    def __init__(self, youtube_id, path):
        self.filename = f"ARTIST - Title [{youtube_id}].mp3"
        self.path = path
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
    monkeypatch.setattr(mod, "Playlist", _FakePlaylist)
    monkeypatch.setattr(mod, "YouTube", _FakeYouTube)

    async def default_create(youtube_id, playlist_path, threshold, **kwargs):
        written = playlist_path / f"ARTIST - Title [{youtube_id}].mp3"
        written.write_bytes(_MP3_FRAME * 8)

        return _FakeSong(youtube_id, written)

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
        written = playlist_path / f"ARTIST - Title [{youtube_id}].mp3"
        written.write_bytes(_MP3_FRAME * 8)

        return _FakeSong(youtube_id, written)

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


from pytubefix.exceptions import BotDetection


def _wrapped(cause: Exception) -> Exception:
    """As SongModel raises it: the real reason buried under a wrapper."""

    wrapper = RuntimeError("Failed to fetch information")
    wrapper.__cause__ = cause

    return wrapper


def test_it_reads_the_reason_from_under_the_wrapper():
    """The surface message is the same words for every kind of failure."""

    from pytubefix.exceptions import AgeRestrictedError, VideoRegionBlocked

    from pypl2mp3.services.import_playlist import (
        failure_reason,
        is_bot_detection,
    )

    age = _wrapped(AgeRestrictedError("x"))
    assert failure_reason(age) == "age restricted"
    assert not is_bot_detection(age), "age restriction never clears"

    region = _wrapped(VideoRegionBlocked("x"))
    assert failure_reason(region) == "blocked in this country"
    assert not is_bot_detection(region)

    refused = _wrapped(BotDetection("vid"))
    assert failure_reason(refused) == "refused by YouTube"
    assert is_bot_detection(refused), "a refusal is what we retry"


async def test_it_retries_only_what_youtube_refused(tmp_path, monkeypatch):
    """A refused song has been seen to succeed moments later. An
    age-restricted one never will, and retrying it only spends time."""

    from pytubefix.exceptions import AgeRestrictedError

    attempts: dict[str, int] = {}

    async def selective(youtube_id, playlist_path, threshold, **kwargs):
        attempts[youtube_id] = attempts.get(youtube_id, 0) + 1

        if youtube_id == "AAAAAAAAAAA":
            raise _wrapped(AgeRestrictedError(youtube_id))
        if youtube_id == "BBBBBBBBBBB" and attempts[youtube_id] == 1:
            raise _wrapped(BotDetection("vid"))

        written = playlist_path / f"ARTIST - Title [{youtube_id}].mp3"
        written.write_bytes(_MP3_FRAME * 8)

        return _FakeSong(youtube_id, written)

    _install_fakes(monkeypatch, create=selective)
    _make_local(tmp_path, [])

    report = await import_playlist(tmp_path, PLAYLIST_ID, FakeProgress())

    assert attempts["AAAAAAAAAAA"] == 1, "age restriction must not be retried"
    assert attempts["BBBBBBBBBBB"] == 2, "a refusal should get a second pass"

    assert sorted(s.youtube_id for s in report.imported) == [
        "BBBBBBBBBBB",
        "CCCCCCCCCCC",
    ], "the retried song should end up imported"
    assert [f.reason for f in report.failed] == ["age restricted"]


async def test_a_refusal_that_persists_is_reported_not_looped(
    tmp_path, monkeypatch
):
    attempts: dict[str, int] = {}

    async def always_refused(youtube_id, playlist_path, threshold, **kwargs):
        attempts[youtube_id] = attempts.get(youtube_id, 0) + 1
        raise _wrapped(BotDetection("vid"))

    _install_fakes(monkeypatch, create=always_refused)
    _make_local(tmp_path, [])

    report = await import_playlist(tmp_path, PLAYLIST_ID, FakeProgress())

    assert all(count == 2 for count in attempts.values()), (
        f"one retry pass, no more: {attempts}"
    )
    assert len(report.failed) == 3
    assert {f.reason for f in report.failed} == {"refused by YouTube"}


async def test_a_selection_narrows_what_is_imported(tmp_path, monkeypatch):
    """The point of the selection panel: you choose, and only what you
    chose is fetched."""

    _install_fakes(monkeypatch)
    _make_local(tmp_path, [])

    report = await import_playlist(
        tmp_path, PLAYLIST_ID, FakeProgress(), only=[REMOTE_IDS[1]]
    )

    assert [song.youtube_id for song in report.imported] == [REMOTE_IDS[1]]
    assert report.failed == []


async def test_an_empty_selection_imports_nothing(tmp_path, monkeypatch):
    """Not the same as no selection at all. `None` means "everything
    missing"; an empty list means the user unticked every row, and
    downloading the lot would be the worst possible reading of that."""

    _install_fakes(monkeypatch)
    _make_local(tmp_path, [])

    report = await import_playlist(
        tmp_path, PLAYLIST_ID, FakeProgress(), only=[]
    )

    assert report.imported == []
    assert list(tmp_path.rglob("*.mp3")) == []


async def test_a_selection_cannot_reach_outside_the_playlist(
    tmp_path, monkeypatch
):
    """A selection narrows what was offered. An id the playlist does not
    hold is ignored, not fetched: the panel's list is the only thing that
    decides what may be downloaded."""

    _install_fakes(monkeypatch)
    _make_local(tmp_path, [])

    report = await import_playlist(
        tmp_path, PLAYLIST_ID, FakeProgress(), only=["ZZZZZZZZZZZ"]
    )

    assert report.imported == []
    assert report.failed == []
    assert list(tmp_path.rglob("*.mp3")) == []


async def test_a_selection_still_skips_what_is_already_on_disk(
    tmp_path, monkeypatch
):
    """The list may be minutes old, and another run may have fetched the
    song in between."""

    _install_fakes(monkeypatch)
    _make_local(tmp_path, [REMOTE_IDS[0]])

    report = await import_playlist(
        tmp_path, PLAYLIST_ID, FakeProgress(), only=REMOTE_IDS
    )

    assert [song.youtube_id for song in report.imported] == REMOTE_IDS[1:], (
        'the song already on disk was fetched a second time'
    )


async def test_no_selection_still_imports_everything_missing(
    tmp_path, monkeypatch
):
    """The CLI passes nothing, and must keep its behaviour exactly."""

    _install_fakes(monkeypatch)
    _make_local(tmp_path, [])

    report = await import_playlist(tmp_path, PLAYLIST_ID, FakeProgress())

    assert sorted(song.youtube_id for song in report.imported) == sorted(
        REMOTE_IDS
    )
