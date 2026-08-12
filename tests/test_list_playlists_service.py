import socket
from pathlib import Path

import pytest

from pypl2mp3.services.list_playlists import PlaylistSummary, list_playlists


def _forbidden(*args, **kwargs):
    raise AssertionError("un listing local a tenté un accès réseau")


def _block_network(monkeypatch):
    """Interdire les trois portes d'entrée réseau : connexion bloquante,
    connexion non bloquante (utilisée par les clients HTTP asynchrones tels
    qu'aiohttp, déjà présent dans l'arbre de dépendances via shazamio), et
    résolution DNS seule."""

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


def test_sorting_ignores_case_and_accents(tmp_path):
    """Ce que `natural_sort_key` apporte par rapport à un tri brut.

    Le cas précédent (A, B, C) se trie identiquement avec `.sort()` : il ne
    prouve donc rien sur la clé de tri. Une casse mélangée et une lettre
    accentuée, si : `.sort()` rendrait Beta, Fabrice, alpha, Émile, l'ordre
    des points de code, où les majuscules précèdent les minuscules et les
    caractères accentués finissent en queue de liste.
    """

    labels = ("Owner - Fabrice", "Owner - alpha", "Owner - Émile", "Owner - Beta")
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
    """Le nom `list_playlists` désignait la commande, qui prend un Namespace.

    Le ré-importer tel quel dans la façade le ferait toujours résoudre à
    l'ancienne adresse publique, mais avec une signature incompatible : un
    appelant resté sur `commands.list_playlists.list_playlists(args)`
    échouerait sur un `Path` attendu au lieu d'un `Namespace`. Mieux vaut
    un AttributeError franc.
    """

    from pypl2mp3.commands import list_playlists as facade

    assert not hasattr(facade, "list_playlists")
    assert callable(facade.display_playlists)


def test_performs_no_network_call(tmp_path, monkeypatch):
    """Un listing local ne doit jamais toucher au réseau, même indirectement."""

    _block_network(monkeypatch)
    _make_playlist(tmp_path, "Owner - Alpha [PL0000000000000000000000000000001]", 1, 0)

    assert len(list_playlists(tmp_path)) == 1


def test_the_network_trap_actually_fires(monkeypatch):
    """Sans cela, le piège est affirmé mais jamais exercé."""

    _block_network(monkeypatch)

    with socket.socket() as sock:
        with pytest.raises(AssertionError, match="accès réseau"):
            sock.connect(("127.0.0.1", 9))
        with pytest.raises(AssertionError, match="accès réseau"):
            sock.connect_ex(("127.0.0.1", 9))

    with pytest.raises(AssertionError, match="accès réseau"):
        socket.getaddrinfo("example.invalid", 80)
