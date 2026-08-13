"""Streaming a song to the browser's audio element."""

from pathlib import Path

import httpx

from pypl2mp3.web.app import create_app

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _make_song(repo: Path, vid: str) -> Path:
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"ARTIST - Title [{vid}].mp3"
    path.write_bytes(_MP3_FRAME * 8)

    return path


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_it_serves_the_file_as_audio(tmp_path):
    path = _make_song(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        response = await client.get("/songs/aaaaaaaaaaa/audio")

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == path.read_bytes()


async def test_it_supports_range_requests(tmp_path):
    """Without Range the browser cannot seek without fetching everything."""

    _make_song(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        response = await client.get(
            "/songs/aaaaaaaaaaa/audio", headers={"Range": "bytes=0-99"}
        )

    assert response.status_code == 206
    assert len(response.content) == 100
    assert response.headers["content-range"].startswith("bytes 0-99/")


async def test_an_unknown_id_is_a_404(tmp_path):
    _make_song(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        response = await client.get("/songs/zzzzzzzzzzz/audio")

    assert response.status_code == 404


async def test_a_traversal_attempt_does_not_escape_the_repository(tmp_path):
    """The id reaches this route straight from the URL."""

    _make_song(tmp_path, "aaaaaaaaaaa")
    secret = tmp_path.parent / "secret.mp3"
    secret.write_bytes(b"do not serve me")

    async with _client(create_app(tmp_path)) as client:
        for attempt in ("../secret", "..%2Fsecret", "%2e%2e%2fsecret"):
            response = await client.get(f"/songs/{attempt}/audio")
            assert response.status_code in (404, 400), attempt
            assert b"do not serve me" not in response.content, attempt


async def test_a_listing_never_ships_one_player_per_row(tmp_path):
    """It used to: 915 rows, 915 <audio> elements, none of which survived
    leaving the page. The console has a single player instead, and its
    guarantees are tested in test_web_console.py."""

    for i in range(4):
        _make_song(tmp_path, f"vid{i:07d}")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/songs")).text

    assert body.count("<audio") == 0, (
        "a 900-row listing must not read every file on page load"
    )
