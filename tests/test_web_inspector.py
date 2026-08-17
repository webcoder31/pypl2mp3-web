"""The inspector: fixing a song without leaving the page."""

import re
from pathlib import Path

import httpx
from mutagen.id3 import ID3, TXXX

from pypl2mp3.web.app import create_app

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"
HX = {"HX-Request": "true"}

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _make_song(repo: Path, artist, title, vid, junk=False):
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    suffix = " (JUNK)" if junk else ""
    path = folder / f"{artist} - {title} [{vid}]{suffix}.mp3"
    path.write_bytes(_MP3_FRAME * 8)

    frames = ID3()
    frames.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
    frames.save(path)

    return path


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_the_inspector_carries_the_song_and_its_form(tmp_path):
    _make_song(tmp_path, "UNKNOWN", "Something", "aaaaaaaaaaa", junk=True)

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/fragments/inspector/aaaaaaaaaaa")).text

    assert "/songs/aaaaaaaaaaa/cover" in body, "no cover art"
    assert 'name="artist"' in body
    assert 'name="title"' in body
    assert 'name="cover_art_url"' in body
    assert 'data-song-id="aaaaaaaaaaa"' in body, (
        "console.js needs this to know which song is on show"
    )


async def test_the_inspector_is_a_fragment_and_holds_no_player(tmp_path):
    """It is swapped into #inspector; a second <audio> would fight the bar."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/fragments/inspector/aaaaaaaaaaa")).text

    assert "<audio" not in body, "the inspector brought its own player back"
    for tag in ("<html", "<body", "<head"):
        assert tag not in body, tag


async def test_the_inspector_does_not_call_shazam_on_load(tmp_path, monkeypatch):
    """Shazam costs seconds and waits fifteen more between calls."""

    called = []

    async def spy(self, **kwargs):
        called.append(self)

    monkeypatch.setattr("pypl2mp3.libs.song.SongModel.shazam_song", spy)
    _make_song(tmp_path, "UNKNOWN", "Something", "aaaaaaaaaaa", junk=True)

    async with _client(create_app(tmp_path)) as client:
        assert (
            await client.get("/fragments/inspector/aaaaaaaaaaa")
        ).status_code == 200

    assert called == [], "opening the panel must not identify the song"


async def test_an_unknown_song_has_no_inspector(tmp_path):
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        assert (
            await client.get("/fragments/inspector/zzzzzzzzzzz")
        ).status_code == 404


async def test_saving_tells_the_listing_to_refetch(tmp_path):
    """A fixed junk song must leave a junk-filtered view, not sit in it
    looking repaired. Only the server knows whether it still belongs, so
    the console is told to ask again."""

    _make_song(tmp_path, "UNKNOWN", "Something", "aaaaaaaaaaa", junk=True)

    async with _client(create_app(tmp_path)) as client:
        response = await client.post(
            "/songs/aaaaaaaaaaa/fix",
            headers=HX,
            data={"artist": "THE PHARCYDE", "title": "Passin Me By"},
        )

    assert response.status_code == 200
    assert response.headers.get("HX-Trigger") == "songsChanged"


async def test_saving_returns_the_updated_panel_not_a_row(tmp_path):
    _make_song(tmp_path, "UNKNOWN", "Something", "aaaaaaaaaaa", junk=True)

    async with _client(create_app(tmp_path)) as client:
        body = (
            await client.post(
                "/songs/aaaaaaaaaaa/fix",
                headers=HX,
                data={"artist": "THE PHARCYDE", "title": "Passin Me By"},
            )
        ).text

    assert 'value="THE PHARCYDE"' in body, "the panel shows the old artist"
    assert 'name="title"' in body, "this is not the inspector"
    assert "⚠" not in body, "the song is still flagged as junk"


async def test_the_listing_refetches_on_that_signal(tmp_path):
    """The signal is useless if nothing listens for it."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text

    listing = re.search(r"<main[^>]*id=\"list\"[^>]*>", body, re.DOTALL)
    assert listing, "no listing element"
    assert 'hx-trigger="songsChanged from:body"' in listing.group(0)
    assert 'hx-get="/fragments/list"' in listing.group(0)
    assert 'hx-include="#filters"' in listing.group(0), (
        "refetching without the filters would drop the current selection"
    )


async def test_the_search_box_filters_as_you_type(tmp_path):
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text

    form = re.search(r"<form[^>]*id=\"filters\"[^>]*>", body, re.DOTALL)
    assert form, "no filter form"
    trigger = re.search(r'hx-trigger="([^"]+)"', form.group(0)).group(1)

    assert "keyup" in trigger, "filtering still needs a click on a button"
    assert "changed" in trigger, (
        "without `changed`, arrow keys and modifiers refetch an "
        "unchanged query"
    )
    assert "delay:" in trigger, "a request per keystroke on 900 songs"
    assert "submit" in trigger, "pressing enter must not be a dead end"


async def test_shazam_answers_in_the_panel_rather_than_as_json(
    tmp_path, monkeypatch
):
    """The user's words: "je ne vois pas à quoi sert le JSON affiché"."""

    async def fake(self, shazam_match_threshold=50, **kwargs):
        self.shazam_artist = "THE PHARCYDE"
        self.shazam_title = "Passin Me By"
        self.shazam_cover_art_url = "http://example.invalid/art.jpg"
        self.shazam_match_score = 88.0

    monkeypatch.setattr("pypl2mp3.libs.song.SongModel.shazam_song", fake)
    _make_song(tmp_path, "UNKNOWN", "Something", "aaaaaaaaaaa", junk=True)

    async with _client(create_app(tmp_path)) as client:
        started = await client.post("/songs/aaaaaaaaaaa/shazam", headers=HX)

        assert started.status_code == 200
        assert "job_id" not in started.text, "raw JSON is back"
        assert 'id="shazam"' in started.text

        # Poll until the job settles, the way the fragment does.
        for _ in range(60):
            body = (
                await client.get("/fragments/shazam/aaaaaaaaaaa", headers=HX)
            ).text
            if "Listening" not in body:
                break

    assert "88% match" in body, body
    assert "THE PHARCYDE - Passin Me By" in body


async def test_the_proposal_fills_the_form_instead_of_writing_the_tags(
    tmp_path, monkeypatch
):
    """Shazam is confident about remixes it has never heard."""

    async def fake(self, shazam_match_threshold=50, **kwargs):
        self.shazam_artist = "THE PHARCYDE"
        self.shazam_title = "Passin Me By"
        self.shazam_cover_art_url = ""
        self.shazam_match_score = 88.0

    monkeypatch.setattr("pypl2mp3.libs.song.SongModel.shazam_song", fake)
    path = _make_song(tmp_path, "UNKNOWN", "Something", "aaaaaaaaaaa", junk=True)

    async with _client(create_app(tmp_path)) as client:
        await client.post("/songs/aaaaaaaaaaa/shazam", headers=HX)
        for _ in range(60):
            body = (
                await client.get("/fragments/shazam/aaaaaaaaaaa", headers=HX)
            ).text
            if "Listening" not in body:
                break

    assert 'data-shazam-artist="THE PHARCYDE"' in body, (
        "the proposal must reach the form, not be applied behind the user"
    )
    assert path.exists(), "identifying a song must not rename its file"
    assert ID3(path).getall("TPE1") == [], "identifying wrote the tags"


async def test_polling_stops_once_shazam_has_answered(
    tmp_path, monkeypatch
):
    """A terminal fragment carries no hx-trigger, so the browser stops."""

    async def fake(self, shazam_match_threshold=50, **kwargs):
        self.shazam_artist = "A"
        self.shazam_title = "B"
        self.shazam_cover_art_url = ""
        self.shazam_match_score = 90.0

    monkeypatch.setattr("pypl2mp3.libs.song.SongModel.shazam_song", fake)
    _make_song(tmp_path, "UNKNOWN", "Something", "aaaaaaaaaaa", junk=True)

    async with _client(create_app(tmp_path)) as client:
        await client.post("/songs/aaaaaaaaaaa/shazam", headers=HX)
        for _ in range(60):
            body = (
                await client.get("/fragments/shazam/aaaaaaaaaaa", headers=HX)
            ).text
            if "Listening" not in body:
                break

    assert "hx-trigger" not in body, "the browser keeps polling forever"


async def test_shazam_without_a_job_is_a_404_not_an_empty_panel(tmp_path):
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        assert (
            await client.get("/fragments/shazam/aaaaaaaaaaa")
        ).status_code == 404


async def test_the_script_guards_unsaved_edits_before_following_the_player(
    tmp_path,
):
    """A wiring check, not a behaviour check.

    Whether the guard actually holds needs a browser engine. What this
    catches is the guard being deleted: the panel follows the playing
    song, so a track ending mid-sentence would otherwise wipe whatever
    was being typed.
    """

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    assert "/fragments/inspector/" in script, "the panel never follows"
    guard = script[script.index("function inspect(id)"):]
    guard = guard[: guard.index("\n  }")]
    assert "if (dirty)" in guard, "no guard on unsaved edits"
    assert "return" in guard, guard[:200]

    # And it says so. Holding the panel back is deliberate — a track
    # ending mid-sentence must not wipe what you were typing — but doing
    # it in silence left the panel looking stuck on the wrong song.
    assert "holding-edits" in guard, (
        "the panel stops following the player without saying why"
    )
    assert 'event.target.closest("#inspector")' in script, (
        "nothing marks the panel dirty when you type in it"
    )


async def test_the_panel_offers_to_play_what_it_shows(tmp_path):
    """Two cursors are allowed here — inspecting a song without cutting
    the one you are listening to is deliberate, and the junk fix-link
    exists for exactly that — but nothing said which was which. The
    player went on with its own song while the panel described another,
    and pressing play resumed the first.
    """

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        panel = (await client.get("/fragments/inspector/aaaaaaaaaaa")).text
        css = (await client.get("/static/console.css")).text
        script = (await client.get("/static/console.js")).text

    assert "play-this" in panel, panel[:400]

    # Rendered always and hidden by the page: the server cannot know what
    # is playing, because the queue lives in the browser.
    hidden = re.search(
        r"#inspector\.is-playing \.play-this \{([^}]*)\}", css
    )
    assert hidden and "display: none" in hidden.group(1), css[-400:]
    assert "is-playing" in script, "nothing ever sets the class"

    # And it carries the weight Save carries, because it commits to
    # something: it changes what you are listening to.
    # The resting rule, not the hover one — that carries the accent too,
    # so matching either let the fill be dropped without a test noticing.
    rules = [
        (selector, body)
        for selector, body in re.findall(
            r"\n([^\n{}]+(?:,\n[^\n{}]+)*)\{([^}]*)\}", css
        )
        if "#inspector .play-this" in selector and ":hover" not in selector
    ]
    assert rules, "the button has no resting rule at all"
    selector, body = rules[0]
    assert "background: var(--accent);" in body, body
    assert '#inspector button[type="submit"]' in selector, (
        "it is filled by a rule of its own, which can drift from Save's"
    )


async def test_playing_from_the_panel_uses_the_listing(tmp_path):
    """So the queue and what you can see stay the same thing. Falling
    back to a queue of one is for a song the listing does not hold —
    filtered out, or imported into a view that does not show it — and a
    button that sometimes does nothing would be worse."""

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    handler = script[script.index('closest("#inspector .play-this")'):]
    handler = handler[: handler.index("\n      return;")]
    assert "queueFromRows()" in handler, handler[:300]
    assert "setQueue" in handler, handler[:300]
    assert "at >= 0" in handler, (
        "the panel always plays the song alone, throwing away the queue"
    )
