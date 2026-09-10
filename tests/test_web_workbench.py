"""The workbench: judging a run of songs one at a time."""

import asyncio
import contextlib
import re
from pathlib import Path

import httpx
from mutagen.id3 import ID3, TXXX

from pypl2mp3.services.find_song import song_key_in_folder
from pypl2mp3.web.app import create_app
from pypl2mp3.web.jobs import JobState

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



def _key(vid, playlist=PLAYLIST):
    """The address the web uses for one song.

    Not the video: a video held by two playlists is two files, and the
    routes name the file. `song_key` is the one definition of the pair.
    """

    return song_key_in_folder(playlist, vid)

def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_the_listing_offers_a_way_into_the_workbench(tmp_path):
    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/?junk=1")).text

    assert 'data-queue-action="workbench"' in body


async def test_the_card_asks_shazam_once_it_has_been_looked_at(tmp_path):
    """The opposite of the inspector, and deliberately so: here,
    identifying the song is the work.

    On sight, but after a dwell. The model waits fifteen seconds between
    calls, so a card stepped past in a third of a second used to leave a
    job holding that wait in front of the song you actually stopped on —
    ten skips, a minute and a half. htmx drops a delayed trigger when the
    element goes, so the run places no calls at all."""

    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        card = (await client.get(f"/fragments/workbench/{_key('aaaaaaaaaaa')}")).text
        panel = (await client.get(f"/fragments/inspector/{_key('aaaaaaaaaaa')}")).text

    trigger = re.search(r'hx-trigger="load([^"]*)"', card)
    assert trigger, "the card waits to be asked"
    delay = re.match(r" delay:(\d+)ms$", trigger.group(1))
    assert delay, f"asked on sight, with nothing to cancel: {trigger.group(0)}"
    # Long enough to outlast a step, short enough not to read as a pause.
    assert 200 <= int(delay.group(1)) <= 800, delay.group(1)
    assert f"/songs/{_key('aaaaaaaaaaa')}/shazam" in card

    assert "hx-trigger=\"load" not in panel, (
        "the ordinary inspector must not spend a Shazam call on every "
        "song you click"
    )


async def test_the_card_carries_the_form_and_the_song(tmp_path):
    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        card = (await client.get(f"/fragments/workbench/{_key('aaaaaaaaaaa')}")).text

    assert 'name="artist"' in card
    assert 'name="title"' in card
    assert f"/songs/{_key('aaaaaaaaaaa')}/cover" in card
    assert 'data-song-id="aaaaaaaaaaa"' in card, (
        "console.js needs this to know which song is on show"
    )


async def test_the_card_holds_no_player_of_its_own(tmp_path):
    """The bar plays it. A second element would fight the first."""

    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        card = (await client.get(f"/fragments/workbench/{_key('aaaaaaaaaaa')}")).text

    assert "<audio" not in card
    for tag in ("<html", "<body", "<head"):
        assert tag not in card, tag


async def test_an_unknown_song_has_no_card(tmp_path):
    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        assert (
            await client.get(f"/fragments/workbench/{_key('zzzzzzzzzzz')}")
        ).status_code == 404


async def test_saving_from_the_card_paints_nothing_and_moves_on(tmp_path):
    """Advancing is the confirmation. Painting the ordinary inspector
    first would flash the wrong panel on the way there."""

    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        card = (await client.get(f"/fragments/workbench/{_key('aaaaaaaaaaa')}")).text
        script = (await client.get("/static/console.js")).text

    form = re.search(r"<form[^>]*>", card).group(0)
    assert 'hx-swap="none"' in form, form
    assert 'hx-target="#inspector"' not in form

    # Asked for, not passive: the save means done with this one, so it
    # steps the way Skip does — and lets go of the edits the same way.
    assert "move(1, true)" in script
    assert "event.detail.successful" in script, (
        "a failed save would advance and lose the correction"
    )


async def test_the_save_still_tells_the_listing_to_refetch(tmp_path):
    """A fixed song leaves a junk-filtered selection; the listing behind
    the workbench must learn that."""

    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        response = await client.post(
            f"/songs/{_key('aaaaaaaaaaa')}/fix",
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
        await client.get(f"/fragments/inspector/{_key('aaaaaaaaaaa')}")

    assert called == []


async def test_the_mode_states_its_keys(tmp_path):
    """In the frame, not in the card. Nothing in the line changes with
    the song, and rendering it inside the swapped region redrew it on
    every one — and put it between the form and the timeline, which cut
    the card in two."""

    _make_junk(tmp_path, "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        page = (await client.get("/")).text
        card = (await client.get(f"/fragments/workbench/{_key('aaaaaaaaaaa')}")).text
        script = (await client.get("/static/console.js")).text

    keys = re.search(r'<p id="workbench-keys">(.*?)</p>', page, re.S)
    assert keys, "the mode says nothing about its keys"
    for key in ("enter", "esc", "space", "tab"):
        assert key in keys.group(1).lower(), key

    assert "workbench-keys" not in card, "the card carries them again"

    # Enter is handled apart from the other keys: the shared handler
    # ignores anything typed in a field, and the fast path here is
    # correct-then-enter without reaching for the mouse.
    assert 'event.key !== "Enter" || !inWorkbench()' in script
    assert "form.requestSubmit()" in script


async def test_a_card_you_left_gives_up_its_place_in_the_queue(tmp_path):
    """The model waits fifteen seconds between calls to Shazam, and a job
    for a card that is gone spends that wait in front of the song you
    actually stopped on. Six skips used to cost a minute and a half.

    Cancelling reaches the job inside `asyncio.sleep`, so the place is
    free at once rather than when the abandoned call finishes.
    """

    _make_junk(tmp_path, "aaaaaaaaaaa")
    app = create_app(tmp_path)

    started = asyncio.Event()

    async def waits_forever(job):
        started.set()
        await asyncio.sleep(3600)

    async with _client(app) as client:
        # Nothing to cancel is not an error: the caller is saying "not
        # wanted", and a job that never started is not wanted either.
        answer = await client.post(f"/songs/{_key('bbbbbbbbbbb')}/shazam/cancel")
        assert answer.status_code == 200, answer.text
        assert answer.json() == {"cancelled": False}

        # Named by the file, like the route that cancels it.
        job = app.state.jobs.start(
            f"shazam:{_key('aaaaaaaaaaa')}", waits_forever)
        await asyncio.wait_for(started.wait(), 1)

        answer = await client.post(f"/songs/{_key('aaaaaaaaaaa')}/shazam/cancel")
        assert answer.json() == {"cancelled": True}, answer.text

        with contextlib.suppress(asyncio.CancelledError):
            await job.task

        assert job.state is JobState.CANCELLED, job.state


async def test_stepping_on_cancels_the_card_it_leaves(tmp_path):
    """The page is the only side that knows a card has been left: the
    server sees a job it was asked for and nothing since."""

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    body = re.search(r"function play\(i\) \{(.*?)\n  \}", script, re.S)
    assert body, "play() moved"
    assert "const leaving" in body.group(1), (
        "play() cannot say which card it is leaving"
    )
    assert "/shazam/cancel" in body.group(1), body.group(1)
    # Not while merely listening: outside the workbench nothing asked.
    assert "inWorkbench() && leaving" in body.group(1), body.group(1)

    # And the bet on the next song is held back the same way, or walking
    # a run would place one per step.
    assert re.search(r"prefetchClock = window\.setTimeout\(placeBets, \d+\)",
                     script), "the prefetch fires on every step"


async def test_an_asked_for_step_leaves_the_edits_behind(tmp_path):
    """Skip is the answer to "are you done with this one", so it moves
    whatever is in the fields.

    The panel holds unsaved edits and stops following the player, which
    is right when a track simply ended — that must not wipe what you were
    typing. In the workbench it was neither right nor visible: taking
    Shazam's answer marks the form dirty, so one click on Use this and
    then Skip left the audio walking on with the card stuck behind it,
    and the card has no room for the line that says the panel is holding.
    """

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    body = re.search(r"function move\(step, asked\) \{(.*?)\n  \}",
                     script, re.S)
    assert body, "move cannot tell an asked-for step from a track ending"
    assert "asked && inWorkbench()" in body.group(1), body.group(1)
    assert "forgetEdits()" in body.group(1), body.group(1)

    # Every caller that is the user asking says so; the one that is a
    # track ending does not.
    assert "move(1)" not in script and "move(-1)" not in script, (
        "a step the user asked for still goes through as a passive one"
    )
    assert script.count("move(1, true)") == 3, (
        "Skip, the right arrow, and the save that means done with this one"
    )
    assert script.count("move(-1, true)") == 2, "previous and the left arrow"
    assert "move(direction)" in script, "a track ending must still hold"

    # And letting go is one function, so the flag and the sign it puts on
    # the panel cannot come apart. Twice: the declaration and the one
    # place that clears it.
    assert script.count("dirty = false") == 2, (
        "a second place lets go of the flag without clearing the sign"
    )


async def test_the_panel_wanted_counts_as_much_as_the_song(tmp_path):
    """The workbench could open on a song the inspector was already
    showing and load nothing at all.

    You got the plain panel full frame — no listing, no nav, and no Done
    — and nothing on screen could leave the mode, so the page had to be
    reloaded. Comparing only the song id is what did it.
    """

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    body = script[script.index("function inspect(key)"):]
    body = body[: body.index("\n  }")]

    assert "showing === wanted" in body, (
        "inspect() decides on the song alone, so asking for a different "
        "panel on the same song loads nothing"
    )
    assert '"/fragments/" + wanted' in body, body[-300:]


async def test_a_tab_is_a_way_out_of_the_workbench(tmp_path):
    """The tabs switch the pane under them and the workbench covers that
    pane entirely, so asking for a tab is asking to be back in the layout
    that has one. It is also the escape hatch if the panel ever fails to
    arrive."""

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    handler = script[script.index('closest("#tabs [data-tab]")'):]
    handler = handler[: handler.index("\n      return;")]

    assert "leaveWorkbench()" in handler, (
        "clicking a tab leaves the workbench on screen with its panes "
        "hidden behind it"
    )
