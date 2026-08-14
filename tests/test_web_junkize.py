"""Junkizing from the browser: destructive, so it must be exact."""

from pathlib import Path

import httpx
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3

from pypl2mp3.web.app import create_app

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"
HX = {"HX-Request": "true"}

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _make_song(repo: Path, artist: str, title: str, vid: str) -> Path:
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{artist} - {title} [{vid}].mp3"
    path.write_bytes(_MP3_FRAME * 8)

    tags = EasyID3()
    tags["artist"] = artist
    tags["title"] = title
    tags.save(path)

    return path


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_the_listing_offers_junkize_only_for_tagged_songs(tmp_path):
    _make_song(tmp_path, "GOOD", "Tagged", "aaaaaaaaaaa")
    app = create_app(tmp_path)

    async with _client(app) as client:
        body = (await client.get("/fragments/list")).text
        assert "/songs/aaaaaaaaaaa/junkize" in body

        await client.post("/songs/aaaaaaaaaaa/junkize", headers=HX)

        after = (await client.get("/fragments/list")).text

    assert "/songs/aaaaaaaaaaa/junkize" not in after, (
        "an already-junk song must not offer the button again"
    )


async def test_it_clears_the_tags_on_disk(tmp_path):
    _make_song(tmp_path, "THE PHARCYDE", "Passin Me By", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        response = await client.post("/songs/aaaaaaaaaaa/junkize", headers=HX)

    assert response.status_code == 200

    junked = next((tmp_path / PLAYLIST).glob("*(JUNK).mp3"))
    frames = ID3(junked)
    assert frames.getall("TPE1") == []
    assert frames.getall("TIT2") == []


async def test_the_row_comes_back_marked_as_junk(tmp_path):
    _make_song(tmp_path, "ARTIST", "Title", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        row = (
            await client.post("/songs/aaaaaaaaaaa/junkize", headers=HX)
        ).text

    assert 'id="song-aaaaaaaaaaa"' in row, (
        "the fragment must carry the id it replaces, or the swap misses"
    )
    assert "⚠" in row, "the row should now show the junk marker"
    assert "metadata cleared" in row
    assert "junkize" not in row, "a junk song must not offer the button"


async def test_the_button_asks_for_confirmation(tmp_path):
    """Destructive and not undoable: a stray click must not be enough."""

    _make_song(tmp_path, "ARTIST", "Title", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/fragments/list")).text

    assert "hx-confirm" in body


async def test_an_unknown_song_is_a_404(tmp_path):
    _make_song(tmp_path, "SPARED", "Intact", "aaaaaaaaaaa")
    spared = next((tmp_path / PLAYLIST).glob("*.mp3"))

    async with _client(create_app(tmp_path)) as client:
        response = await client.post("/songs/zzzzzzzzzzz/junkize", headers=HX)

    assert response.status_code == 404
    assert spared.exists()
    assert EasyID3(spared)["artist"] == ["SPARED"]


async def test_without_the_htmx_header_it_answers_json(tmp_path):
    _make_song(tmp_path, "ARTIST", "Title", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        response = await client.post("/songs/aaaaaaaaaaa/junkize")

    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload["youtube_id"] == "aaaaaaaaaaa"
    assert "(JUNK)" in payload["filename"]
