"""The repair screen: the one place a browser beats a terminal outright."""

from pathlib import Path

import httpx
from mutagen.id3 import APIC, ID3, TXXX

from pypl2mp3.web.app import create_app

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"
HX = {"HX-Request": "true"}

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413
# Smallest valid JPEG-ish payload; only its bytes matter to these tests.
_COVER = b"\xff\xd8\xff\xe0" + b"\x00" * 60 + b"\xff\xd9"


def _make_junk(repo: Path, vid: str = "aaaaaaaaaaa", cover: bool = False):
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"UNKNOWN - Something [{vid}] (JUNK).mp3"
    path.write_bytes(_MP3_FRAME * 8)

    frames = ID3()
    frames.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
    if cover:
        frames.add(
            APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=_COVER)
        )
    frames.save(path)

    return path


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_the_junk_listing_links_to_the_repair_screen(tmp_path):
    _make_junk(tmp_path)

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/songs?junk=1")).text

    assert "/songs/aaaaaaaaaaa/fix" in body


async def test_the_screen_offers_the_cover_the_player_and_the_form(tmp_path):
    """Seeing the cover and hearing the track is why this is a page."""

    _make_junk(tmp_path)

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/songs/aaaaaaaaaaa/fix")).text

    assert "/songs/aaaaaaaaaaa/cover" in body, "no cover art"
    assert "/songs/aaaaaaaaaaa/audio" in body, "no player"
    assert 'name="artist"' in body
    assert 'name="title"' in body
    assert 'name="cover_art_url"' in body


async def test_the_screen_does_not_call_shazam_on_load(tmp_path, monkeypatch):
    """Shazam costs seconds and waits 15 more between calls."""

    called = []

    async def spy(self, **kwargs):
        called.append(self)

    monkeypatch.setattr("pypl2mp3.libs.song.SongModel.shazam_song", spy)
    _make_junk(tmp_path)

    async with _client(create_app(tmp_path)) as client:
        assert (await client.get("/songs/aaaaaaaaaaa/fix")).status_code == 200

    assert called == [], "loading the page must not identify the song"


async def test_submitting_the_form_writes_the_tags_and_clears_junk(tmp_path):
    _make_junk(tmp_path)

    async with _client(create_app(tmp_path)) as client:
        response = await client.post(
            "/songs/aaaaaaaaaaa/fix",
            data={"artist": "THE PHARCYDE", "title": "Passin Me By"},
        )

    assert response.status_code == 200
    written = next((tmp_path / PLAYLIST).glob("*.mp3"))
    assert "(JUNK)" not in written.name
    assert ID3(written).getall("TPE1")[0].text[0] == "THE PHARCYDE"


async def test_the_cover_route_serves_the_embedded_image(tmp_path):
    _make_junk(tmp_path, cover=True)

    async with _client(create_app(tmp_path)) as client:
        response = await client.get("/songs/aaaaaaaaaaa/cover")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")
    assert response.content == _COVER


async def test_a_song_without_cover_art_is_a_404_not_a_broken_image(tmp_path):
    _make_junk(tmp_path, cover=False)

    async with _client(create_app(tmp_path)) as client:
        assert (
            await client.get("/songs/aaaaaaaaaaa/cover")
        ).status_code == 404


async def test_an_unknown_song_is_a_404_everywhere(tmp_path):
    _make_junk(tmp_path)

    async with _client(create_app(tmp_path)) as client:
        for path in ("fix", "cover", "audio"):
            assert (
                await client.get(f"/songs/zzzzzzzzzzz/{path}")
            ).status_code == 404, path

        assert (
            await client.post(
                "/songs/zzzzzzzzzzz/fix", data={"artist": "A", "title": "B"}
            )
        ).status_code == 404


async def test_shazam_runs_as_a_job_rather_than_blocking_the_request(
    tmp_path, monkeypatch
):
    """It takes seconds; holding the request open would freeze the click."""

    async def fake(self, shazam_match_threshold=50, **kwargs):
        self.shazam_artist = "THE PHARCYDE"
        self.shazam_title = "Passin Me By"
        self.shazam_cover_art_url = ""
        self.shazam_match_score = 88.0

    monkeypatch.setattr("pypl2mp3.libs.song.SongModel.shazam_song", fake)
    _make_junk(tmp_path)

    async with _client(create_app(tmp_path)) as client:
        started = await client.post("/songs/aaaaaaaaaaa/shazam")

    assert started.status_code == 200
    assert started.json()["job_id"] == "shazam:aaaaaaaaaaa"
