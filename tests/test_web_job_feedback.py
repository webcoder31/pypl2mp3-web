"""Clicking the button must show something — including when it fails."""

import asyncio

import httpx
import pytest

from pypl2mp3.services import check_new_songs as mod
from pypl2mp3.web.app import create_app

PLAYLIST_ID = "PLP6XxNg42qDGMg1cR2PPPzwdoAOD1MQ97"
REMOTE_IDS = ["AAAAAAAAAAA", "BBBBBBBBBBB"]
HX = {"HX-Request": "true"}


class _FakePlaylist:
    def __init__(self, url, *args, **kwargs):
        self.title = "fake"
        self.owner = "owner"
        self.length = len(REMOTE_IDS)
        self.video_urls = [
            f"https://www.youtube.com/watch?v={vid}" for vid in REMOTE_IDS
        ]


class _FailingPlaylist:
    def __init__(self, url, *args, **kwargs):
        raise RuntimeError("network down")


def _make_local(repo, present):
    folder = repo / f"owner - fake [{PLAYLIST_ID}]"
    folder.mkdir(parents=True)
    for vid in present:
        (folder / f"ARTIST - Title [{vid}].mp3").touch()


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _settle(client, job_id):
    """Poll until the job leaves its running states, or fail loudly."""

    for _ in range(50):
        body = (await client.get(f"/jobs/{job_id}", headers=HX)).text
        if "hx-get" not in body:
            return body
        await asyncio.sleep(0.05)

    pytest.fail(f"job {job_id} never settled")


async def test_the_json_api_is_unchanged_without_the_htmx_header(
    tmp_path, monkeypatch
):
    """The task 6 contract must survive: no header, still JSON."""

    monkeypatch.setattr(mod, "Playlist", _FakePlaylist)
    _make_local(tmp_path, [])

    async with _client(create_app(tmp_path)) as client:
        response = await client.post(f"/playlists/{PLAYLIST_ID}/check")

    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["job_id"] == f"check:{PLAYLIST_ID}"


async def test_the_button_gets_a_fragment_that_polls_itself(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(mod, "Playlist", _FakePlaylist)
    _make_local(tmp_path, [])

    async with _client(create_app(tmp_path)) as client:
        body = (
            await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        ).text

    assert "<div" in body
    assert f'hx-get="/jobs/check:{PLAYLIST_ID}"' in body
    assert "hx-trigger" in body


async def test_polling_stops_once_the_job_is_done(tmp_path, monkeypatch):
    """Without this, the browser would poll a finished job forever."""

    monkeypatch.setattr(mod, "Playlist", _FakePlaylist)
    _make_local(tmp_path, [])

    async with _client(create_app(tmp_path)) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        settled = await _settle(client, f"check:{PLAYLIST_ID}")

    assert "hx-trigger" not in settled
    assert "hx-get" not in settled


async def test_a_completed_check_reports_what_it_found(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "Playlist", _FakePlaylist)
    _make_local(tmp_path, ["AAAAAAAAAAA"])

    async with _client(create_app(tmp_path)) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        settled = await _settle(client, f"check:{PLAYLIST_ID}")

    assert "1" in settled


async def test_a_failed_check_shows_the_error_rather_than_nothing(
    tmp_path, monkeypatch
):
    """Silence after a failure is the worst outcome: it reads as success."""

    monkeypatch.setattr(mod, "Playlist", _FailingPlaylist)
    _make_local(tmp_path, [])

    async with _client(create_app(tmp_path)) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        settled = await _settle(client, f"check:{PLAYLIST_ID}")

    assert "network down" in settled or "failed" in settled.lower()


async def test_a_second_click_says_so_instead_of_looking_inert(
    tmp_path, monkeypatch
):
    """HTMX does not swap on a 4xx, so a bare 409 would show nothing."""

    class _Slow(_FakePlaylist):
        def __init__(self, url, *args, **kwargs):
            import time

            time.sleep(2)
            super().__init__(url, *args, **kwargs)

    monkeypatch.setattr(mod, "Playlist", _Slow)
    _make_local(tmp_path, [])
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        await asyncio.sleep(0.1)
        second = await client.post(
            f"/playlists/{PLAYLIST_ID}/check", headers=HX
        )

        assert second.status_code == 200
        assert "already" in second.text.lower()

        app.state.jobs.cancel(f"check:{PLAYLIST_ID}")
