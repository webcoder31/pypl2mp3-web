"""Junkizing is destructive: it must hit exactly the song it was given."""

from pathlib import Path

import pytest
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError

from pypl2mp3.services.junkize_songs import (
    JunkizeResult,
    SongNotFound,
    junkize_song,
)
from pypl2mp3.services.list_songs import list_songs

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"

# One MPEG-1 Layer III frame: 128 kbps, 44.1 kHz, mono. An empty file will
# not do — SongModel opens it with mutagen.
_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _make_tagged_song(repo: Path, artist: str, title: str, vid: str) -> Path:
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{artist} - {title} [{vid}].mp3"
    path.write_bytes(_MP3_FRAME * 8)

    tags = EasyID3()
    tags["artist"] = artist
    tags["title"] = title
    tags.save(path)

    return path


def test_it_clears_the_tags_and_renames_the_file(tmp_path):
    path = _make_tagged_song(tmp_path, "THE PHARCYDE", "Passin Me By", "aaaaaaaaaaa")

    result = junkize_song(tmp_path, "aaaaaaaaaaa")

    assert isinstance(result, JunkizeResult)
    assert result.previous_filename == path.name
    assert "(JUNK)" in result.filename
    assert not path.exists(), "the original filename must be gone"

    junked = tmp_path / PLAYLIST / result.filename
    assert junked.exists()

    try:
        tags = EasyID3(junked)
    except ID3NoHeaderError:
        tags = {}
    assert not tags.get("artist")
    assert not tags.get("title")


def test_the_song_is_afterwards_reported_as_junk(tmp_path):
    _make_tagged_song(tmp_path, "ARTIST", "Title", "aaaaaaaaaaa")
    assert list_songs(tmp_path, junk_only=True) == []

    junkize_song(tmp_path, "aaaaaaaaaaa")

    junk = list_songs(tmp_path, junk_only=True)
    assert len(junk) == 1
    assert junk[0].youtube_id == "aaaaaaaaaaa"


def test_it_leaves_every_other_song_untouched(tmp_path):
    _make_tagged_song(tmp_path, "TARGET", "Doomed", "aaaaaaaaaaa")
    spared = _make_tagged_song(tmp_path, "SPARED", "Intact", "bbbbbbbbbbb")

    junkize_song(tmp_path, "aaaaaaaaaaa")

    # Not byte equality: get_repository_song_files builds a SongModel per
    # candidate to sort them, and that constructor rewrites the ID3 header
    # from 2.4 to 2.3. Every listing in this project already does that, in
    # the CLI too. What must hold is that the neighbour keeps its name and
    # its metadata.
    assert spared.exists(), "a neighbour was renamed"
    assert EasyID3(spared)["artist"] == ["SPARED"]
    assert EasyID3(spared)["title"] == ["Intact"]


def test_an_unknown_id_raises_rather_than_touching_anything(tmp_path):
    spared = _make_tagged_song(tmp_path, "SPARED", "Intact", "aaaaaaaaaaa")

    with pytest.raises(SongNotFound):
        junkize_song(tmp_path, "zzzzzzzzzzz")

    assert spared.exists()
    assert EasyID3(spared)["artist"] == ["SPARED"]


def test_junkizing_an_already_junk_song_is_harmless(tmp_path):
    _make_tagged_song(tmp_path, "ARTIST", "Title", "aaaaaaaaaaa")
    first = junkize_song(tmp_path, "aaaaaaaaaaa")

    second = junkize_song(tmp_path, "aaaaaaaaaaa")

    assert second.filename == first.filename
    assert len(list_songs(tmp_path, junk_only=True)) == 1


def test_the_title_frame_is_actually_removed(tmp_path):
    """Regression for a copy-paste bug in libs/song.py.

    `update_id3_tags` deleted TPE1 in *both* branches — the artist's own
    else-branch and the title's — so TIT2 was never removed and the title
    survived every reset. `pypl2mp3 junkize` shipped that way.

    Asserted at the frame level rather than through EasyID3, which hides
    the distinction behind friendly names.
    """

    from mutagen.id3 import ID3

    _make_tagged_song(tmp_path, "THE PHARCYDE", "Passin Me By", "aaaaaaaaaaa")

    result = junkize_song(tmp_path, "aaaaaaaaaaa")

    frames = ID3(tmp_path / PLAYLIST / result.filename)
    assert frames.getall("TIT2") == [], "the title frame survived the reset"
    assert frames.getall("TPE1") == [], "the artist frame survived the reset"
