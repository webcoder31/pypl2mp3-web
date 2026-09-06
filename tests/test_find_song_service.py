"""Locating one song by its YouTube id."""

from pathlib import Path

import pytest
from mutagen.id3 import ID3, TXXX

from pypl2mp3.libs import repository
from pypl2mp3.services.find_song import SongNotFound, find_song_file, song_key

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"
OTHER = "Owner - Beta [PL0000000000000000000000000000002]"

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _key(vid, playlist=PLAYLIST):
    """The address a caller uses for one song: the playlist and the video.

    Not the video alone — one held by two playlists is two files, and
    these functions act on the one they are given.
    """

    return song_key(playlist, vid)

def _make_song(repo: Path, vid: str, playlist: str = PLAYLIST, tag=True):
    folder = repo / playlist
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"ARTIST - Title [{vid}].mp3"
    path.write_bytes(_MP3_FRAME * 8)

    if tag:
        frames = ID3()
        frames.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
        frames.save(path)

    return path


def test_it_finds_a_song_in_any_playlist(tmp_path):
    _make_song(tmp_path, "aaaaaaaaaaa")
    wanted = _make_song(tmp_path, "bbbbbbbbbbb", playlist=OTHER)

    assert find_song_file(tmp_path, _key("bbbbbbbbbbb", OTHER)) == wanted.resolve()


def test_an_unknown_id_is_not_found(tmp_path):
    _make_song(tmp_path, "aaaaaaaaaaa")

    with pytest.raises(SongNotFound):
        find_song_file(tmp_path, _key("zzzzzzzzzzz"))


def test_it_reads_no_tags(tmp_path, monkeypatch):
    """The id is in the filename.

    Building a model per candidate would also rewrite the ID3 header of
    any file lacking a YouTube ID tag — modifying files merely to look
    at them — and this is on the path of every click that opens a song.
    """

    built = []
    real = repository.SongModel

    class Counted(real):
        def __init__(self, path, *args, **kwargs):
            built.append(Path(path))
            super().__init__(path, *args, **kwargs)

    monkeypatch.setattr(repository, "SongModel", Counted)

    for i in range(4):
        _make_song(tmp_path, f"vid{i:07d}")
    # The case the docstring warns about: no YouTube ID tag to read.
    _make_song(tmp_path, "untaggedxxx", tag=False)

    find_song_file(tmp_path, _key("vid0000002"))

    assert built == [], built


def test_an_untagged_file_is_left_alone(tmp_path):
    """Scanning must not rewrite what it scans past."""

    _make_song(tmp_path, "aaaaaaaaaaa")
    untagged = _make_song(tmp_path, "bbbbbbbbbbb", tag=False)
    before = untagged.read_bytes()

    find_song_file(tmp_path, _key("aaaaaaaaaaa"))

    assert untagged.read_bytes() == before, (
        "looking for one song rewrote another"
    )


def test_a_path_escaping_the_repository_is_refused(tmp_path):
    """The id comes from a URL; this is the boundary."""

    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "ARTIST - Secret [aaaaaaaaaaa].mp3"
    secret.write_bytes(_MP3_FRAME * 8)

    repo = tmp_path / "repo"
    (repo / PLAYLIST).mkdir(parents=True)
    link = repo / PLAYLIST / "ARTIST - Secret [aaaaaaaaaaa].mp3"
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip("symlinks unavailable")

    with pytest.raises(SongNotFound):
        find_song_file(repo, _key("aaaaaaaaaaa"))


def test_each_copy_of_one_video_answers_to_its_own_key(tmp_path):
    """The whole reason this takes a key. Eight songs in a repository of
    this shape sit in two playlists at once, and a lookup on the video
    returned whichever copy the filesystem listed first — so saving wrote
    to one and left the other on its old metadata, junkizing renamed one
    and left the other whole, and playing streamed a file the row you
    clicked did not name."""

    here = _make_song(tmp_path, "aaaaaaaaaaa")
    there = _make_song(tmp_path, "aaaaaaaaaaa", playlist=OTHER)

    assert find_song_file(tmp_path, _key("aaaaaaaaaaa")) == here.resolve()
    assert find_song_file(tmp_path, _key("aaaaaaaaaaa", OTHER)) \
        == there.resolve()


def test_the_video_on_its_own_is_not_an_address(tmp_path):
    """It names two files as readily as one, so it names none.

    Accepting it as a fallback would be the old behaviour kept alive
    under a new name: every caller that still passed an id would go on
    getting an arbitrary copy, and nothing would say so.
    """

    _make_song(tmp_path, "aaaaaaaaaaa")

    with pytest.raises(SongNotFound):
        find_song_file(tmp_path, "aaaaaaaaaaa")
