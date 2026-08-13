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
