"""The inventory page renders local data and touches no network."""

import socket

import httpx

from pypl2mp3.web.app import create_app


def _forbidden(*args, **kwargs):
    raise AssertionError("the web inventory attempted network access")


def _block_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", _forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", _forbidden)


def _make_playlist(repo, name, songs, junks):
    folder = repo / name
    folder.mkdir()
    for index in range(songs):
        (folder / f"ARTIST - Song {index} [vid{index:07d}].mp3").touch()
    for index in range(junks):
        (folder / f"ARTIST - Junk {index} [jnk{index:07d}] (JUNK).mp3").touch()


async def _get(app, path):
    """Fetch a page.

    httpx.ASGITransport implements only the async transport interface, so a
    sync httpx.Client cannot drive it. `asyncio_mode = "auto"` means the
    tests below need no decorator.
    """

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        return await client.get(path)


async def test_inventory_lists_playlists_with_their_counts(
    tmp_path, monkeypatch
):
    _block_network(monkeypatch)
    _make_playlist(
        tmp_path, "Owner - Alpha [PL0000000000000000000000000000001]", 3, 1
    )

    response = await _get(create_app(tmp_path), "/")

    assert response.status_code == 200
    body = response.text
    assert "Owner - Alpha" in body
    assert "PL0000000000000000000000000000001" in body

    # Counts must appear as their own table cells, not merely somewhere in
    # the page: asserting "4" in body would pass on almost any markup.
    import re

    cells = re.findall(r'<td class="num[^"]*">\s*([0-9]+)\s*</td>', body)
    assert cells == ["3", "1", "4"], (
        f"expected tagged/junk/total = 3/1/4, got {cells}"
    )


async def test_inventory_reports_an_empty_repository(tmp_path, monkeypatch):
    _block_network(monkeypatch)

    response = await _get(create_app(tmp_path), "/")

    assert response.status_code == 200
    assert "No playlists" in response.text


async def test_htmx_is_served_locally(tmp_path):
    response = await _get(create_app(tmp_path), "/static/htmx.min.js")

    assert response.status_code == 200
    assert len(response.content) > 10_000


async def test_the_page_references_no_external_host(tmp_path, monkeypatch):
    """No CDN: the interface must work offline."""

    _block_network(monkeypatch)
    _make_playlist(
        tmp_path, "Owner - Alpha [PL0000000000000000000000000000001]", 1, 0
    )

    body = (await _get(create_app(tmp_path), "/")).text

    for marker in ("http://", "https://", "//unpkg", "//cdn"):
        assert marker not in body, f"external reference found: {marker}"
