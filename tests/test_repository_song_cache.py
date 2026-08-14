"""Reusing parsed songs between listings.

Reading a song's ID3 tags is what a listing spends its time on: 1.3s
over a 927-song repository, paid again on every call. A search box that
filters as you type calls it once per keystroke.
"""

import os
from pathlib import Path

import pytest
from mutagen.id3 import ID3, TPE1, TXXX

from pypl2mp3.libs import repository
from pypl2mp3.services.list_songs import list_songs

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


@pytest.fixture(autouse=True)
def empty_cache():
    repository._song_cache.clear()
    yield
    repository._song_cache.clear()


@pytest.fixture
def parses(monkeypatch):
    """Every path whose tags get read."""

    seen = []
    real = repository.SongModel

    class Counted(real):
        def __init__(self, path, *args, **kwargs):
            seen.append(Path(path))
            super().__init__(path, *args, **kwargs)

    monkeypatch.setattr(repository, "SongModel", Counted)

    return seen


def _make_song(repo: Path, artist: str, vid: str, junk: bool = False) -> Path:
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    suffix = " (JUNK)" if junk else ""
    path = folder / f"{artist} - Title [{vid}]{suffix}.mp3"
    path.write_bytes(_MP3_FRAME * 8)

    frames = ID3()
    frames.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
    frames.add(TPE1(encoding=3, text=artist))
    frames.save(path)

    return path


def test_a_second_listing_reads_no_tags_again(tmp_path, parses):
    for i in range(3):
        _make_song(tmp_path, f"ARTIST {i}", f"vid{i:07d}")

    list_songs(tmp_path)
    assert len(parses) == 3, parses

    parses.clear()
    list_songs(tmp_path)

    assert parses == [], "the second listing re-read every file"


def test_filtering_differently_still_reads_nothing_again(tmp_path, parses):
    """Keywords and the junk flag change what is selected, not what the
    files contain."""

    _make_song(tmp_path, "WU-TANG CLAN", "aaaaaaaaaaa")
    _make_song(tmp_path, "DIRE STRAITS", "bbbbbbbbbbb")
    _make_song(tmp_path, "UNKNOWN", "ccccccccccc", junk=True)

    list_songs(tmp_path)
    parses.clear()

    list_songs(tmp_path, keywords="wu tang")
    list_songs(tmp_path, junk_only=True)
    list_songs(tmp_path, playlist_identifier="PL0000000000000000000000000000001")

    assert parses == [], parses


def test_a_song_edited_on_disk_is_read_again(tmp_path, parses):
    """Something outside this process can rewrite the tags."""

    path = _make_song(tmp_path, "UNKNOWN", "aaaaaaaaaaa")

    assert list_songs(tmp_path)[0].artist == "UNKNOWN"
    parses.clear()

    frames = ID3(path)
    frames.setall("TPE1", [TPE1(encoding=3, text="THE PHARCYDE")])
    frames.save(path)
    # Filesystems keep whole-second mtimes on some volumes; make the
    # change unmistakable rather than relying on nanosecond resolution.
    os.utime(path, (0, 0))

    assert list_songs(tmp_path)[0].artist == "THE PHARCYDE", (
        "the listing served tags that are no longer on disk"
    )
    assert parses, "the edited file was never re-read"


def test_a_same_sized_rewrite_at_the_same_time_is_missed(tmp_path):
    """The one case this cannot see, stated rather than hidden.

    Validation is (mtime, size). A rewrite that changes neither is
    invisible — restarting the server is the way out. It takes deliberate
    effort to produce and no ordinary edit does it.
    """

    path = _make_song(tmp_path, "UNKNOWN", "aaaaaaaaaaa")
    stamp = path.stat()

    assert list_songs(tmp_path)[0].artist == "UNKNOWN"

    frames = ID3(path)
    frames.setall("TPE1", [TPE1(encoding=3, text="UNKNOWM")])
    frames.save(path)
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

    if path.stat().st_size == stamp.st_size:
        assert list_songs(tmp_path)[0].artist == "UNKNOWN", (
            "documented blind spot no longer reproduces — if the "
            "validation got stronger, say so here"
        )


def test_a_renamed_song_leaves_nothing_behind(tmp_path):
    """Fixing a junk song renames its file. One dead entry per
    correction would accumulate through a whole session."""

    path = _make_song(tmp_path, "UNKNOWN", "aaaaaaaaaaa", junk=True)
    list_songs(tmp_path)
    assert len(repository._song_cache) == 1

    path.rename(path.with_name("THE PHARCYDE - Title [aaaaaaaaaaa].mp3"))
    list_songs(tmp_path)

    assert len(repository._song_cache) == 1, (
        f"the old path is still cached: {list(repository._song_cache)}"
    )


def test_another_playlist_is_not_forgotten_by_a_scoped_listing(tmp_path):
    """Listing one playlist says nothing about whether the others still
    exist."""

    _make_song(tmp_path, "ARTIST", "aaaaaaaaaaa")
    other = tmp_path / "Owner - Beta [PL0000000000000000000000000000002]"
    other.mkdir(parents=True)
    path = other / "OTHER - Title [bbbbbbbbbbb].mp3"
    path.write_bytes(_MP3_FRAME * 8)
    frames = ID3()
    frames.add(TXXX(encoding=3, desc="YouTube ID", text="bbbbbbbbbbb"))
    frames.save(path)

    list_songs(tmp_path)
    assert len(repository._song_cache) == 2

    list_songs(tmp_path, playlist_identifier="PL0000000000000000000000000000001")

    assert len(repository._song_cache) == 2, (
        "listing one playlist evicted another's songs"
    )


def test_a_deleted_song_disappears_from_the_listing(tmp_path):
    path = _make_song(tmp_path, "ARTIST", "aaaaaaaaaaa")
    _make_song(tmp_path, "OTHER", "bbbbbbbbbbb")

    assert len(list_songs(tmp_path)) == 2

    path.unlink()

    assert [s.youtube_id for s in list_songs(tmp_path)] == ["bbbbbbbbbbb"]


def test_the_cached_listing_is_the_same_listing(tmp_path):
    """Order included: it is what the play queue is built from."""

    for i in range(8):
        _make_song(tmp_path, f"ARTIST {7 - i}", f"vid{i:07d}")

    cold = [(s.youtube_id, s.artist, s.is_junk) for s in list_songs(tmp_path)]
    warm = [(s.youtube_id, s.artist, s.is_junk) for s in list_songs(tmp_path)]

    assert cold == warm
    assert len(cold) == 8


def test_an_unreadable_file_is_not_cached(tmp_path, parses):
    """A path that cannot be stat-ed must not poison the cache."""

    _make_song(tmp_path, "ARTIST", "aaaaaaaaaaa")
    list_songs(tmp_path)

    missing = tmp_path / PLAYLIST / "GONE - Title [zzzzzzzzzzz].mp3"
    with pytest.raises(Exception):
        repository._load_song(missing)

    assert missing not in repository._song_cache
