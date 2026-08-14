"""The density switch, and the transport that replaced the browser's.

Two densities, one skeleton. The whole point is that compact and
comfortable differ only in CSS values — the moment either needs its own
markup, its own route or its own test, the switch stops being cheap and
starts being a fork.
"""

import re
from pathlib import Path

import httpx

from pypl2mp3.web.app import create_app

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"
OTHER = "Owner - Beta [PL0000000000000000000000000000002]"
HX = {"HX-Request": "true"}

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _make_song(repo: Path, artist, title, vid, junk=False, playlist=PLAYLIST):
    folder = repo / playlist
    folder.mkdir(parents=True, exist_ok=True)
    suffix = " (JUNK)" if junk else ""
    (folder / f"{artist} - {title} [{vid}]{suffix}.mp3").write_bytes(
        _MP3_FRAME * 8
    )


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_the_page_offers_both_densities(tmp_path):
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text

    assert 'data-density="comfortable"' in body
    assert 'data-density="compact"' in body


async def test_the_choice_is_applied_before_the_first_paint(tmp_path):
    """console.js loads at the end of the document. Waiting for it would
    show one density and then visibly snap to the other."""

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text

    head = body[: body.index("</head>")]
    assert "localStorage.getItem" in head, (
        "the stored density is read too late to prevent a flash"
    )
    assert "documentElement.dataset.density" in head


async def test_the_choice_is_remembered(tmp_path):
    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text
        script = (await client.get("/static/console.js")).text

    assert "pypl2mp3.density" in body, "the head reads no stored preference"
    assert "localStorage.setItem" in script, "clicking it forgets immediately"


async def test_both_densities_are_only_values(tmp_path):
    """The claim this whole feature rests on.

    If a density block carried rules rather than custom properties, the
    two layouts would start drifting and the switch would become a fork.
    """

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    block = re.search(
        r':root\[data-density="compact"\]\s*\{(.*?)\}', css, re.DOTALL
    )
    assert block, "compact defines nothing"

    declarations = [
        line.strip()
        for line in block.group(1).split(";")
        if line.strip() and not line.strip().startswith("/*")
    ]
    assert declarations, "compact is empty"
    assert all(d.startswith("--") for d in declarations), (
        f"compact carries rules, not just values: "
        f"{[d for d in declarations if not d.startswith('--')]}"
    )


async def test_the_two_densities_define_the_same_names(tmp_path):
    """A value defined in one and missing from the other silently falls
    back to whatever comfortable said — a difference nobody chose."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    def names(selector):
        block = re.search(
            re.escape(selector) + r"[^{]*\{(.*?)\n\}", css, re.DOTALL
        )
        assert block, selector
        return set(re.findall(r"(--[\w-]+)\s*:", block.group(1)))

    comfortable = names(':root, :root[data-density="comfortable"]')
    compact = names(':root[data-density="compact"]')

    assert comfortable == compact, (
        f"only in comfortable: {comfortable - compact}; "
        f"only in compact: {compact - comfortable}"
    )


async def test_one_markup_serves_both(tmp_path):
    """No template may branch on density: that is the fork this avoids."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        fragment = (await client.get("/fragments/list")).text
        page = (await client.get("/")).text

    rows = re.findall(r"<tr[^>]*data-song-id.*?</tr>", fragment, re.DOTALL)
    assert rows, "no rows"
    for row in rows:
        assert "compact" not in row, row
        assert "comfortable" not in row, row

    # Only the switch itself may name a density.
    outside = re.sub(r'<div id="density".*?</div>', "", page, flags=re.DOTALL)
    assert "data-density" not in outside, (
        "something other than the switch renders per-density markup"
    )


async def test_the_player_is_not_the_browser_s_own(tmp_path):
    """<audio controls> draws a large rounded pill no stylesheet can
    reach. It was the one shape on the page nobody had designed."""

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text

    player = re.search(r"<audio[^>]*>", body).group(0)
    assert "controls" not in player, player

    assert 'id="transport"' in body, "nothing replaced the browser's chrome"
    assert 'id="seek"' in body, "no way to scrub"
    assert 'id="player-elapsed"' in body and 'id="player-total"' in body, (
        "the times went with the native controls"
    )


async def test_nothing_on_the_page_is_a_pill(tmp_path):
    """Rounded corners are capped at 2px, deliberately."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    for value in re.findall(r"border-radius:\s*([^;}]+)", css):
        for part in value.split():
            if part.endswith("px"):
                assert float(part[:-2]) <= 2, value
            else:
                assert part in ("0", "50%"), value


async def test_the_transport_reports_and_seeks(tmp_path):
    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    assert 'addEventListener("timeupdate"' in script, "the clock never ticks"
    assert "audio.currentTime =" in script, "the bar cannot seek"
    assert "isFinite(audio.duration)" in script, (
        "seeking before metadata arrives would set currentTime to NaN"
    )


async def test_the_seek_bar_does_not_also_change_track(tmp_path):
    """It is a slider: arrows must move the playhead, not the queue."""

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    handler = script[script.index('seek.addEventListener("keydown"'):]
    handler = handler[: handler.index("\n  });")]
    assert "stopPropagation" in handler, (
        "an arrow key would seek and skip at the same time"
    )


async def test_durations_lose_their_empty_hours(tmp_path):
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        fragment = (await client.get("/fragments/list")).text

    assert "00:00:00" not in fragment, "the padded form is still rendered"


async def test_the_playlist_column_goes_when_it_says_nothing(tmp_path):
    """Repeating one playlist's name down 874 rows teaches nothing. It
    earns its place only when the selection spans more than one."""

    _make_song(tmp_path, "ARTIST", "One", "aaaaaaaaaaa")
    _make_song(tmp_path, "ARTIST", "Two", "bbbbbbbbbbb", playlist=OTHER)

    async with _client(create_app(tmp_path)) as client:
        everything = (await client.get("/fragments/list")).text
        scoped = (
            await client.get(
                "/fragments/list?playlist=PL0000000000000000000000000000001"
            )
        ).text

    assert 'class="playlist"' in everything, (
        "with two playlists in view, the name is the only way to tell them "
        "apart"
    )
    assert 'class="playlist"' not in scoped, (
        "the same name repeated down every row of one playlist"
    )


async def test_a_junkized_row_matches_the_rows_around_it(tmp_path):
    """It comes back on its own, so it has to know what the page is
    showing. htmx sends that in HX-Current-URL."""

    _make_song(tmp_path, "ARTIST", "One", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        scoped = await client.post(
            "/songs/aaaaaaaaaaa/junkize",
            headers={
                **HX,
                "HX-Current-URL": (
                    "http://test/?playlist=PL0000000000000000000000000000001"
                ),
            },
        )

    assert 'class="playlist"' not in scoped.text, (
        "the replaced row shows a playlist its neighbours do not"
    )


async def test_every_control_is_drawn_by_the_stylesheet(tmp_path):
    """The check that should have existed from the start.

    A page that leaves buttons, inputs or checkboxes to the browser gets
    the browser's chrome — bevels, gradients, its own corner radius, its
    own focus ring — and no amount of layout work rescues it. The first
    version of console.css styled three controls out of nineteen, and
    the result was reported as looking like a website from 2000.
    """

    _make_song(tmp_path, "UNKNOWN", "Song", "aaaaaaaaaaa", junk=True)

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text
        pages = [
            (await client.get("/")).text,
            (await client.get("/fragments/inspector/aaaaaaaaaaa")).text,
            (await client.get("/fragments/workbench/aaaaaaaaaaa")).text,
        ]

    def block(selector):
        found = re.search(re.escape(selector) + r"\s*\{(.*?)\n\}",
                          css, re.DOTALL)
        assert found, f"no rule for {selector}"
        return found.group(1)

    # Native appearance has to be switched off in each rule that paints a
    # widget; the platform otherwise draws its own under ours. Counting
    # occurrences across the file is not enough — one rule can hold both
    # the prefixed and unprefixed form while another holds neither.
    for selector in ("button",
                     'input[type="search"], input[type="text"], '
                     'input[type="url"]'):
        assert "appearance: none" in block(selector), (
            f"{selector} still wears the platform's chrome"
        )

    # Every input type the templates actually use must be named.
    used = set()
    for page in pages:
        used.update(re.findall(r'<input[^>]*type="([a-z]+)"', page))
    used.discard("hidden")

    for kind in sorted(used):
        assert f'input[type="{kind}"]' in css, (
            f"<input type={kind}> is left to the browser"
        )

    # A checkbox cannot be repainted; accent-color is the only handle on
    # it, so naming the selector without it changes nothing.
    if "checkbox" in used:
        assert "accent-color" in block('input[type="checkbox"]'), (
            "the checkbox keeps the platform's own colour"
        )

    # And the states a control needs to feel like a control.
    for rule in ("button:hover", "button:active", ":focus-visible"):
        assert rule in css, rule

    # The platform's focus ring is the loudest default of all.
    assert "outline: 2px solid var(--accent)" in css, (
        "focus falls back to the operating system's blue ring"
    )


async def test_the_page_has_designed_surfaces(tmp_path):
    """`Canvas` is the browser's own white. A flat white page with 1px
    grey hairlines is the look this pass exists to leave behind."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    assert "background: Canvas" not in css, (
        "a region still paints itself with the browser's default"
    )
    for name in ("--bg:", "--surface:", "--sunken:", "--hover:"):
        assert name in css, name

    dark = css[css.index("prefers-color-scheme: dark"):]
    for name in ("--bg:", "--surface:", "--text:"):
        assert name in dark, f"{name} has no dark value"


async def test_type_sizes_come_from_a_scale(tmp_path):
    """Twelve arbitrary sizes is not a scale; it is noise."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    steps = set(re.findall(r"(--fs-[a-z]+):", css))
    assert 4 <= len(steps) <= 8, steps

    literal = set(re.findall(r"font-size:\s*([\d.]+rem)", css))
    scale = set(re.findall(r"--fs-[a-z]+:\s*([\d.]+rem)", css))
    assert literal <= scale, (
        f"sizes written outside the scale: {sorted(literal - scale)}"
    )
