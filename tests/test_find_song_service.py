"""Locating one song by its YouTube id."""

from pathlib import Path

import pytest
from mutagen.id3 import ID3, TXXX

from pypl2mp3.libs import repository
from pypl2mp3.services.find_song import SongNotFound, find_song_file

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"
OTHER = "Owner - Beta [PL0000000000000000000000000000002]"

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


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

    assert find_song_file(tmp_path, "bbbbbbbbbbb") == wanted.resolve()


def test_an_unknown_id_is_not_found(tmp_path):
    _make_song(tmp_path, "aaaaaaaaaaa")

    with pytest.raises(SongNotFound):
        find_song_file(tmp_path, "zzzzzzzzzzz")


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

    find_song_file(tmp_path, "vid0000002")

    assert built == [], built


def test_an_untagged_file_is_left_alone(tmp_path):
    """Scanning must not rewrite what it scans past."""

    _make_song(tmp_path, "aaaaaaaaaaa")
    untagged = _make_song(tmp_path, "bbbbbbbbbbb", tag=False)
    before = untagged.read_bytes()

    find_song_file(tmp_path, "aaaaaaaaaaa")

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
        find_song_file(repo, "aaaaaaaaaaa")
