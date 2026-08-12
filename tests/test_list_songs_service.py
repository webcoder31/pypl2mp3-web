"""The song listing reads the disk and nothing else."""

import socket
from pathlib import Path

import pytest

from pypl2mp3.services.list_songs import SongSummary, list_songs

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"

# One MPEG-1 Layer III frame: 128 kbps, 44.1 kHz, mono, 417 bytes. An empty
# file will not do — SongModel opens the file with mutagen, which raises
# HeaderNotFoundError unless it can sync to a real frame.
_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _forbidden(*args, **kwargs):
    raise AssertionError("a local listing attempted network access")


def _block_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", _forbidden)


def _make_song(repo: Path, artist: str, title: str, vid: str, junk=False):
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    suffix = " (JUNK)" if junk else ""
    path = folder / f"{artist} - {title} [{vid}]{suffix}.mp3"
    path.write_bytes(_MP3_FRAME * 8)


def test_returns_empty_for_an_empty_repository(tmp_path):
    assert list_songs(tmp_path) == []


def test_summarizes_a_song_from_its_filename(tmp_path):
    _make_song(tmp_path, "THE PHARCYDE", "Passin Me By", "a-mAK3uB2_0")

    songs = list_songs(tmp_path)

    assert len(songs) == 1
    song = songs[0]
    assert isinstance(song, SongSummary)
    assert song.youtube_id == "a-mAK3uB2_0"
    assert song.artist == "THE PHARCYDE"
    assert song.title == "Passin Me By"
    assert song.playlist == PLAYLIST
    assert song.is_junk is False
    assert song.label == "THE PHARCYDE - Passin Me By"


def test_junk_only_excludes_tagged_songs(tmp_path):
    _make_song(tmp_path, "ARTIST", "Good", "aaaaaaaaaaa")
    _make_song(tmp_path, "ARTIST", "Bad", "bbbbbbbbbbb", junk=True)

    every = list_songs(tmp_path)
    junk = list_songs(tmp_path, junk_only=True)

    assert len(every) == 2
    assert [song.title for song in junk] == ["Bad"]
    assert junk[0].is_junk is True


def test_keywords_filter_the_selection(tmp_path):
    _make_song(tmp_path, "WU-TANG CLAN", "Tearz", "aaaaaaaaaaa")
    _make_song(tmp_path, "DIRE STRAITS", "Sultans Of Swing", "bbbbbbbbbbb")

    found = list_songs(tmp_path, keywords="wu tang tearz", match_threshold=45)

    assert [song.artist for song in found] == ["WU-TANG CLAN"]


def test_a_filter_matching_nothing_returns_empty_rather_than_everything(
    tmp_path,
):
    """The repository helper returns None on no match; that must not leak."""

    _make_song(tmp_path, "WU-TANG CLAN", "Tearz", "aaaaaaaaaaa")

    assert list_songs(tmp_path, keywords="zzqxwv", match_threshold=95) == []


def test_performs_no_network_call(tmp_path, monkeypatch):
    _block_network(monkeypatch)
    _make_song(tmp_path, "ARTIST", "Title", "aaaaaaaaaaa")

    assert len(list_songs(tmp_path)) == 1


def test_the_network_trap_actually_fires(monkeypatch):
    """Without this, the trap above is asserted but never exercised."""

    _block_network(monkeypatch)

    with socket.socket() as sock:
        with pytest.raises(AssertionError, match="network access"):
            sock.connect(("127.0.0.1", 9))
        with pytest.raises(AssertionError, match="network access"):
            sock.connect_ex(("127.0.0.1", 9))

    with pytest.raises(AssertionError, match="network access"):
        socket.getaddrinfo("example.invalid", 80)
