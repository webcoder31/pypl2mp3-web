"""Clicking the button must show something — including when it fails."""

import asyncio
import re

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

    assert 'id="imports-body"' in body, body[:200]
    assert f'hx-get="/fragments/imports?playlist={PLAYLIST_ID}"' in body
    assert "hx-trigger" in body


async def test_the_started_fragment_and_its_polls_are_one_element(
    tmp_path, monkeypatch
):
    """The polling swap rests on one id equality — assert it directly.

    The fragment the POST returns and the fragment each poll returns
    must name the same element: the poll replaces itself by outerHTML,
    and the button that started it targets that id. If the two drift, the
    first poll detaches the pane from the document and the browser never
    learns the job finished.
    """

    monkeypatch.setattr(mod, "Playlist", _FakePlaylist)
    _make_local(tmp_path, [])

    async with _client(create_app(tmp_path)) as client:
        post_fragment = (
            await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        ).text
        get_fragment = (
            await client.get(
                f"/fragments/imports?playlist={PLAYLIST_ID}", headers=HX
            )
        ).text

    post_div = re.search(r'<div id="([^"]+)"', post_fragment)
    get_div = re.search(r'<div id="([^"]+)"', get_fragment)

    assert post_div and get_div, (
        f"expected <div id=...> in both fragments; got post={post_div}, "
        f"get={get_div}"
    )
    assert post_div.group(1) == get_div.group(1)

    # And it polls for the playlist it actually represents. Scoped,
    # because the pane is one element serving every playlist: an
    # unscoped poll would answer with whichever one the server guessed.
    polled = re.search(r'hx-get="/fragments/imports\?playlist=([^"]+)"',
                       post_fragment)
    assert polled, f"the started fragment does not poll: {post_fragment[:200]}"
    assert polled.group(1) == PLAYLIST_ID


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

    # The playlist id itself contains "1", so a bare "1" in settled would
    # pass no matter what the template rendered. Pin down both the wording
    # and the count it must report: one of REMOTE_IDS is present locally,
    # so exactly one is missing.
    assert "new song(s)" in settled
    assert "1 new song(s)" in settled


async def test_a_failed_check_shows_the_error_rather_than_nothing(
    tmp_path, monkeypatch
):
    """Silence after a failure is the worst outcome: it reads as success."""

    monkeypatch.setattr(mod, "Playlist", _FailingPlaylist)
    _make_local(tmp_path, [])

    async with _client(create_app(tmp_path)) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        settled = await _settle(client, f"check:{PLAYLIST_ID}")

    # The template's own literal "Check failed:" would satisfy a check for
    # "failed" regardless of whether the actual error ever reached the
    # page, so the error text itself is the only assertion that proves it.
    assert "network down" in settled


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

        # HTMX never swaps on a 4xx, so a 409 here would leave the
        # screen exactly as it was — indistinguishable from a dead
        # button. The answer is the pane, in-band, showing the run that
        # is already going.
        assert second.status_code == 200
        assert 'id="imports-body"' in second.text
        assert "Looking for new songs" in second.text, (
            "the second click says nothing about the run already going"
        )

        # And it must still poll. Swapping in a fragment without
        # hx-get/hx-trigger would detach the live poller from the
        # document, and the browser would never learn the job finished —
        # the exact inert-button failure this exists to remove.
        assert "hx-get" in second.text
        assert "hx-trigger" in second.text

        app.state.jobs.cancel(f"check:{PLAYLIST_ID}")
