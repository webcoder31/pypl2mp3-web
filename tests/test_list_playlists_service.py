from pathlib import Path

from pypl2mp3.services.list_playlists import PlaylistSummary, list_playlists


def _make_playlist(repo: Path, name: str, songs: int, junks: int) -> Path:
    folder = repo / name
    folder.mkdir()
    for index in range(songs):
        (folder / f"ARTIST - Song {index} [vid{index:07d}].mp3").touch()
    for index in range(junks):
        (folder / f"ARTIST - Junk {index} [jnk{index:07d}] (JUNK).mp3").touch()
    return folder


def test_returns_empty_list_when_repository_has_no_playlist(tmp_path):
    assert list_playlists(tmp_path) == []


def test_summarizes_songs_and_junks(tmp_path):
    _make_playlist(tmp_path, "Owner - Alpha [PL0000000000000000000000000000001]", 3, 1)

    summaries = list_playlists(tmp_path)

    assert len(summaries) == 1
    summary = summaries[0]
    assert isinstance(summary, PlaylistSummary)
    assert summary.playlist_id == "PL0000000000000000000000000000001"
    assert summary.name == "Owner - Alpha"
    assert summary.total_songs == 4  # les junks comptent dans le total
    assert summary.junk_songs == 1
    assert summary.valid_songs == 3


def test_ignores_folders_without_a_bracketed_id(tmp_path):
    (tmp_path / "pas-une-playlist").mkdir()
    _make_playlist(tmp_path, "Owner - Alpha [PL0000000000000000000000000000001]", 1, 0)

    assert len(list_playlists(tmp_path)) == 1


def test_sorts_playlists_naturally(tmp_path):
    for label in ("Owner - B", "Owner - A", "Owner - C"):
        _make_playlist(tmp_path, f"{label} [PL{label[-1] * 32}]", 1, 0)

    names = [summary.name for summary in list_playlists(tmp_path)]

    assert names == ["Owner - A", "Owner - B", "Owner - C"]


def test_performs_no_network_call(tmp_path, monkeypatch):
    """Un listing local ne doit jamais toucher au réseau, même indirectement."""

    import socket

    def _forbidden(*args, **kwargs):
        raise AssertionError("un listing local a tenté un accès réseau")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    _make_playlist(tmp_path, "Owner - Alpha [PL0000000000000000000000000000001]", 1, 0)

    assert len(list_playlists(tmp_path)) == 1
