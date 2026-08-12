import socket
from pathlib import Path

import pytest

from pypl2mp3.services.list_playlists import PlaylistSummary, list_playlists


def _forbidden(*args, **kwargs):
    raise AssertionError("a local listing attempted network access")


def _block_network(monkeypatch):
    """Forbid the three network entry points: blocking connect,
    non-blocking connect (used by asynchronous HTTP clients such as
    aiohttp, already present in the dependency tree via shazamio), and
    DNS resolution alone."""

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", _forbidden)


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
    assert summary.total_songs == 4  # junks count towards the total
    assert summary.junk_songs == 1
    assert summary.valid_songs == 3


def test_ignores_folders_without_a_bracketed_id(tmp_path):
    (tmp_path / "not-a-playlist").mkdir()
    _make_playlist(tmp_path, "Owner - Alpha [PL0000000000000000000000000000001]", 1, 0)

    assert len(list_playlists(tmp_path)) == 1


def test_sorts_playlists_naturally(tmp_path):
    for label in ("Owner - B", "Owner - A", "Owner - C"):
        _make_playlist(tmp_path, f"{label} [PL{label[-1] * 32}]", 1, 0)

    names = [summary.name for summary in list_playlists(tmp_path)]

    assert names == ["Owner - A", "Owner - B", "Owner - C"]


def test_sorting_ignores_case_and_accents(tmp_path):
    """What `natural_sort_key` buys us over a raw sort.

    The previous case (A, B, C) sorts identically with `.sort()`: it proves
    nothing about the sort key, then. Mixed case and an accented letter,
    however, do: `.sort()` would yield Beta, Fabrice, alpha, Émile, code
    point order, where uppercase precedes lowercase and accented characters
    end up at the tail of the list.
    """

    labels = (
        "Owner - Fabrice",
        "Owner - alpha",
        "Owner - Émile",
        "Owner - Beta",
    )
    for index, label in enumerate(labels):
        _make_playlist(tmp_path, f"{label} [PL{str(index) * 32}]", 1, 0)

    names = [summary.name for summary in list_playlists(tmp_path)]

    assert names == [
        "Owner - alpha",
        "Owner - Beta",
        "Owner - Émile",
        "Owner - Fabrice",
    ]


def test_the_command_module_does_not_re_export_the_service_function():
    """The name `list_playlists` used to designate the command, which takes
    a Namespace.

    Re-importing it as-is into the facade would still make it resolve to
    the old public address, but with an incompatible signature: a caller
    still relying on `commands.list_playlists.list_playlists(args)` would
    fail on a `Path` expected instead of a `Namespace`. A plain
    AttributeError is preferable.
    """

    from pypl2mp3.commands import list_playlists as facade

    assert not hasattr(facade, "list_playlists")
    assert callable(facade.display_playlists)


def test_performs_no_network_call(tmp_path, monkeypatch):
    """A local listing must never touch the network, even indirectly."""

    _block_network(monkeypatch)
    _make_playlist(tmp_path, "Owner - Alpha [PL0000000000000000000000000000001]", 1, 0)

    assert len(list_playlists(tmp_path)) == 1


def test_the_network_trap_actually_fires(monkeypatch):
    """Without this, the trap is asserted but never exercised."""

    _block_network(monkeypatch)

    with socket.socket() as sock:
        with pytest.raises(AssertionError, match="network access"):
            sock.connect(("127.0.0.1", 9))
        with pytest.raises(AssertionError, match="network access"):
            sock.connect_ex(("127.0.0.1", 9))

    with pytest.raises(AssertionError, match="network access"):
        socket.getaddrinfo("example.invalid", 80)
