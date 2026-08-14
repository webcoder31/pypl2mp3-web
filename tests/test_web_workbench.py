"""The workbench: judging a run of songs one at a time."""

import re
from pathlib import Path

import httpx
from mutagen.id3 import ID3, TXXX

from pypl2mp3.web.app import create_app

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"
HX = {"HX-Request": "true"}

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _make_junk(repo: Path, vid: str):
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"UNKNOWN - Something [{vid}] (JUNK).mp3"
    path.write_bytes(_MP3_FRAME * 8)

    frames = ID3()
    frames.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
    frames.save(path)

    return path


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_the_listing_offers_a_way_into_the_workbench(tmp_path):
    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/?junk=1")).text

    assert 'data-queue-action="workbench"' in body


async def test_the_card_asks_shazam_on_sight(tmp_path):
    """The opposite of the inspector, and deliberately so: here,
    identifying the song is the work."""

    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        card = (await client.get("/fragments/workbench/aaaaaaaaaaa")).text
        panel = (await client.get("/fragments/inspector/aaaaaaaaaaa")).text

    assert 'hx-trigger="load"' in card, "the card waits to be asked"
    assert "/songs/aaaaaaaaaaa/shazam" in card

    assert 'hx-trigger="load"' not in panel, (
        "the ordinary inspector must not spend a Shazam call on every "
        "song you click"
    )


async def test_the_card_carries_the_form_and_the_song(tmp_path):
    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        card = (await client.get("/fragments/workbench/aaaaaaaaaaa")).text

    assert 'name="artist"' in card
    assert 'name="title"' in card
    assert "/songs/aaaaaaaaaaa/cover" in card
    assert 'data-song-id="aaaaaaaaaaa"' in card, (
        "console.js needs this to know which song is on show"
    )


async def test_the_card_holds_no_player_of_its_own(tmp_path):
    """The bar plays it. A second element would fight the first."""

    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        card = (await client.get("/fragments/workbench/aaaaaaaaaaa")).text

    assert "<audio" not in card
    for tag in ("<html", "<body", "<head"):
        assert tag not in card, tag


async def test_an_unknown_song_has_no_card(tmp_path):
    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        assert (
            await client.get("/fragments/workbench/zzzzzzzzzzz")
        ).status_code == 404


async def test_saving_from_the_card_paints_nothing_and_moves_on(tmp_path):
    """Advancing is the confirmation. Painting the ordinary inspector
    first would flash the wrong panel on the way there."""

    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        card = (await client.get("/fragments/workbench/aaaaaaaaaaa")).text
        script = (await client.get("/static/console.js")).text

    form = re.search(r"<form[^>]*>", card).group(0)
    assert 'hx-swap="none"' in form, form
    assert 'hx-target="#inspector"' not in form

    assert "move(1)" in script
    assert "event.detail.successful" in script, (
        "a failed save would advance and lose the correction"
    )


async def test_the_save_still_tells_the_listing_to_refetch(tmp_path):
    """A fixed song leaves a junk-filtered selection; the listing behind
    the workbench must learn that."""

    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        response = await client.post(
            "/songs/aaaaaaaaaaa/fix",
            headers=HX,
            data={"artist": "THE PHARCYDE", "title": "Passin Me By"},
        )

    assert response.headers.get("HX-Trigger") == "songsChanged"


async def test_the_mode_is_a_class_not_a_page(tmp_path):
    """Leaving it must not reload anything: the music keeps playing."""

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    assert 'classList.add("workbench-mode")' in script
    assert 'classList.remove("workbench-mode")' in script
    assert "window.location" not in script, "leaving the mode navigates"


async def test_it_identifies_the_songs_that_come_next(tmp_path):
    """Shazam allows one call every 15s. Waiting for it after each
    decision would put that gap in front of the person, not behind."""

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    assert "const PREFETCH" in script
    assert "index + step" in script, "the prefetch does not look ahead"

    prefetch = script[script.index("function prefetch"):]
    prefetch = prefetch[: prefetch.index("\n  }")]
    assert "if (!inWorkbench()) return" in prefetch, (
        "browsing the listing would fire Shazam calls at every click"
    )


async def test_the_ordinary_inspector_never_prefetches(tmp_path, monkeypatch):
    """Clicking through a listing must stay free."""

    called = []

    async def spy(self, **kwargs):
        called.append(self)

    monkeypatch.setattr("pypl2mp3.libs.song.SongModel.shazam_song", spy)
    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        await client.get("/fragments/inspector/aaaaaaaaaaa")

    assert called == []


async def test_the_card_states_its_keys(tmp_path):
    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        card = (await client.get("/fragments/workbench/aaaaaaaaaaa")).text
        script = (await client.get("/static/console.js")).text

    for key in ("enter", "esc", "space", "tab"):
        assert key in card.lower(), key

    # Enter is handled apart from the other keys: the shared handler
    # ignores anything typed in a field, and the fast path here is
    # correct-then-enter without reaching for the mouse.
    assert 'event.key !== "Enter" || !inWorkbench()' in script
    assert "form.requestSubmit()" in script
