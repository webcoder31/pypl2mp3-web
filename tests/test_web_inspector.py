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


async def test_the_shazam_block_says_which_element_it_replaces(tmp_path):
    """It sits inside the form, and htmx inherits `hx-target` from
    ancestors — so a block that only said `outerHTML` took the form's
    `#inspector` and every poll replaced the whole panel with itself.

    It swapped itself correctly for as long as it had no ancestor with an
    opinion, which is why moving it broke it and nothing said so: the
    first swap looked right, and the second one ate the page.
    """

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        panel = (await client.get(
            "/fragments/inspector/aaaaaaaaaaa", headers=HX)).text

    form = re.search(r"<form[^>]*>", panel).group(0)
    assert 'hx-target="#inspector"' in form, (
        "this test's premise is gone: the form no longer sets a target"
    )

    block = Path("src/pypl2mp3/web/templates/_shazam.html").read_text()
    poll = block[block.index("{% if polling %}"):block.index("{% endif %}>")]

    assert 'hx-target="this"' in poll, (
        f"the poll inherits a target from the form it now lives in: {poll}"
    )


async def test_the_block_takes_the_fields_place_rather_than_pushing_them(
    tmp_path
):
    """Asking Shazam used to insert the answer above the form, which moved
    the three inputs down the panel at the moment you were about to read
    them — and moved them back when it went.

    They share one grid cell now. Both stay in it whichever is showing,
    because the hidden one is `visibility` and not `display`, so the slot
    is always as tall as the taller of the two. Measured in a browser:
    280px of panel before, during and after.
    """

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        panel = (await client.get(
            "/fragments/inspector/aaaaaaaaaaa", headers=HX)).text
        css = (await client.get("/static/console.css")).text

    slot = re.search(
        r'<div class="inspector-slot">(.*?)</div>\s*</div>', panel, re.DOTALL
    )
    assert slot, "the fields and the block no longer share a container"
    assert slot.group(1).index('id="shazam"') < slot.group(1).index(
        'class="inspector-fields"'
    ), "the sibling selector that hides the fields needs the block first"

    assert ".inspector-slot > * { grid-area: 1 / 1; }" in css, (
        "the two no longer stack in one cell, so the panel will jump"
    )
    assert "#shazam.showing + .inspector-fields { visibility: hidden; }" in css

    # And the fragment has to claim the class the selector waits for.
    # Without it the block simply draws over nothing and the fields stay
    # where they are, which looks exactly like the bug this replaced.
    block = Path("src/pypl2mp3/web/templates/_shazam.html").read_text()
    root = block[block.index("<div id=\"shazam\""):block.index(">", block.index("<div id=\"shazam\""))]
    assert "showing" in root, root
    # `display: none` would take the fields out of the grid and let the
    # slot collapse to the block's height.
    assert "display: none" not in re.search(
        r"#shazam\.showing \+ \.inspector-fields \{([^}]*)\}", css
    ).group(1)


async def test_the_answer_offers_both_ways_out(tmp_path):
    """Taking it fills the fields and lets Save through; dismissing leaves
    them as they were. Without the second, the only way to refuse an
    answer was to reload the panel."""

    block = Path("src/pypl2mp3/web/templates/_shazam.html").read_text()

    # The proposal itself, where both buttons have to sit side by side —
    # asked of that branch and not of the file, because every other
    # branch also carries a Dismiss and would answer for it.
    # Sliced on the template's own branch rather than matched with a
    # regex: `(.*?)</div>` stops at the first inner close, which is above
    # the buttons — so it read as if they were not there.
    proposal = block[
        block.index('<div class="proposal">'):block.index("{% else %}")
    ]

    assert "data-shazam-artist=" in proposal, proposal
    assert "data-shazam-dismiss" in proposal, (
        f"the answer can be taken but not refused: {proposal}"
    )

    # And every other terminal state can be dismissed too, not just the
    # one that proposes something: "Shazam does not recognise it" was a
    # dead end with no way back to the fields.
    for state in ("job-none", "job-error"):
        after = block[block.index(state):]
        assert "data-shazam-dismiss" in after[:400], state


async def test_save_waits_for_a_change(tmp_path):
    """A Save that is always available invites the click that rewrites a
    file with exactly what it already held — a rename, a timestamp, and
    the cover's cached address, for nothing."""

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        panel = (await client.get(
            "/fragments/inspector/aaaaaaaaaaa", headers=HX)).text
        js = (await client.get("/static/console.js")).text

    submit = re.search(r"<button type=\"submit\"[^>]*>Save</button>", panel)
    assert submit and "disabled" in submit.group(0), submit and submit.group(0)

    # Both doors have to open it: typing, and taking Shazam's answer. The
    # second is why this is a function and not a line — it was a flag with
    # one side effect, and a second caller was about to forget it.
    assert "function markDirty()" in js
    assert js.count("markDirty();") >= 2, (
        "only one of the two ways to change the form enables Save"
    )
    marks = re.search(r"function markDirty\(\) \{(.*?)\n  \}", js, re.DOTALL)
    assert "save.disabled = false" in marks.group(1), marks.group(1)


async def test_the_wait_wears_the_same_box_as_the_answer(tmp_path):
    """One becoming the other must move nothing. They share the class
    that gives the box its size and border; only the ground and the
    direction differ — grey rather than the accent tint, because there
    is nothing to accept yet and a green box that turns out to say "no
    match" has promised something it cannot keep.

    Measured in a browser: 480×111 for both.
    """

    block = Path("src/pypl2mp3/web/templates/_shazam.html").read_text()
    waiting = block[block.index("{% if state in"):block.index("{% elif state ==")]

    assert 'class="proposal waiting"' in waiting, waiting
    assert "Listening {{ elapsed }}s" in waiting, (
        "the wait no longer says how long it has been waiting"
    )

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    rule = re.search(
        r"#shazam\.showing \.proposal\.waiting \{([^}]*)\}", css
    ).group(1)

    for wanted in ("justify-content: center", "background: var(--sunken)"):
        assert wanted in rule, f"{wanted} missing: {rule}"


async def test_the_wait_shows_that_it_is_still_going(tmp_path):
    """An equaliser rather than a spinner: what is being waited on is
    listening to audio, and the shape says so before the word does. The
    number says how long, the bars say it has not stopped.
    """

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    block = Path("src/pypl2mp3/web/templates/_shazam.html").read_text()
    assert block.count("<rect") >= 4, "too few bars to read as an equaliser"

    bars = re.search(r"\n\.pulse rect \{([^}]*)\}", css).group(1)
    assert "animation: pulse-bar" in bars, bars
    # An SVG child's transform origin is the viewport's corner otherwise,
    # so every bar would scale from the top left and the icon fly apart.
    assert "transform-box: fill-box" in bars, bars
    # Out of phase, or it is one bar drawn six times.
    assert css.count(".pulse rect:nth-child(") >= 3, css.count(
        ".pulse rect:nth-child("
    )

    # Keyframes run straight through the blanket rule that neutralises
    # transitions, so this one has to be named.
    reduced = re.search(
        r"@media \(prefers-reduced-motion: reduce\) \{(.*?)\n\}", css, re.DOTALL
    ).group(1)
    assert ".pulse rect { animation: none; }" in reduced, reduced
