"""How the console looks, and the layout it looks that way in.

There was briefly a compact/comfortable switch here. The layout that
replaced it — inspector above the listing, nav to one side — gives the
listing the full width of the main column, which is what compact was
buying, so the switch and its second set of values are gone.
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



def _dark_block(css: str) -> str:
    """The dark palette.

    It used to live in a `prefers-color-scheme` query; the theme switch
    turned it into an attribute, because a media query cannot express
    "unless the reader said otherwise".
    """

    found = re.search(
        r':root\[data-theme="dark"\] \{(.*?)\n\}', css, re.DOTALL
    )
    assert found, "no dark palette"

    return found.group(1)

def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
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

    # The ring is gone, and suppressed rather than deleted — dropping the
    # rule would hand it back to the browser, which is the platform blue
    # this file exists to keep out. A field still says focus, with its own
    # border and halo.
    assert re.search(r"\n:focus-visible \{ outline: none; \}", css), (
        "focus falls back to the operating system's own ring"
    )
    field = re.search(r"input:focus-visible \{([^}]*)\}", css)
    assert field, "a field no longer says when it has the focus"
    assert "border-color: var(--accent)" in field.group(1), field.group(1)
    # The border alone. A wash around it added a second edge for no
    # information, and at one pixel it said nothing at all.
    assert "box-shadow" not in field.group(1), field.group(1)


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

    dark = _dark_block(css)
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


async def test_dark_text_is_not_near_white(tmp_path):
    """Near-white on near-black glares, and on 900 rows every line is
    shouting. The ramp is deliberately softened."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    dark = _dark_block(css)
    value = re.search(r"--text:\s*#([0-9a-fA-F]{6})", dark).group(1)
    channels = [int(value[i:i + 2], 16) for i in (0, 2, 4)]

    assert max(channels) <= 210, (
        f"#{value} is {max(channels)}/255 at its brightest — that is glare, "
        "not text"
    )
    # And still readable: softening must not become mud.
    assert min(channels) >= 150, f"#{value} is too dim to read"


async def test_a_shazam_score_is_coloured_by_confidence(tmp_path, monkeypatch):
    """92% and 54% call for very different amounts of trust. Rendering
    them as identical grey text hides that."""

    async def fake(self, shazam_match_threshold=50, **kwargs):
        self.shazam_artist = "THE PHARCYDE"
        self.shazam_title = "Passin Me By"
        self.shazam_cover_art_url = ""
        self.shazam_match_score = 91.0

    monkeypatch.setattr("pypl2mp3.libs.song.SongModel.shazam_song", fake)
    _make_song(tmp_path, "UNKNOWN", "Something", "aaaaaaaaaaa", junk=True)

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text
        await client.post("/songs/aaaaaaaaaaa/shazam", headers=HX)

        for _ in range(60):
            body = (
                await client.get("/fragments/shazam/aaaaaaaaaaa", headers=HX)
            ).text
            if "Listening" not in body:
                break

    assert "score-high" in body, body

    for band in ("--score-high", "--score-mid", "--score-low"):
        assert band in css, band

    dark = _dark_block(css)
    for band in ("--score-high", "--score-mid", "--score-low"):
        assert band in dark, f"{band} has no dark value"

    # Three bands that resolve to one colour would be three names for
    # nothing.
    values = {
        band: re.search(band + r":\s*([^;]+)", dark).group(1).strip()
        for band in ("--score-high", "--score-mid", "--score-low")
    }
    assert len(set(values.values())) == 3, values


async def test_colour_marks_state_rather_than_decorating(tmp_path):
    """Every hue in the file has to answer for itself."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    # The one element that moves constantly carries the accent.
    fill = re.search(r"#seek \.fill \{([^}]*)\}", css).group(1)
    assert "var(--accent)" in fill, "the progress fill is still grey"

    # A running job is a state, not dimmed text.
    assert ".job-running { color: var(--busy)" in css

    # The playing row is named by colour, not only by a border.
    assert "tbody tr.playing .row-title { font-weight: 700; " \
           "color: var(--accent); }" in css


async def test_the_main_column_is_one_surface_and_the_side_one_another(
    tmp_path,
):
    """Which things belong together, said in background.

    The song, its transport and the listing under them are one thing you
    work in, so they share one background and the side column takes the
    other. Four panels with four surfaces read as four boxes that happen
    to touch.

    This is the direction that once produced "all the songs are
    selected" — but that was the listing alone on a tinted band with the
    inspector *and* the nav brighter on either side of it. The inspector
    now shares the listing's background exactly, so there is no band and
    no trough: one continuous surface, one distinct column.
    """

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    def background(selector):
        block = re.search(
            re.escape(selector) + r"\s*\{(.*?)\n\}", css, re.DOTALL
        )
        assert block, selector
        found = re.search(r"background:\s*var\((--[\w-]+)\)", block.group(1))
        assert found, f"{selector} paints no background"

        return found.group(1)

    column = {sel: background(sel) for sel in ("#inspector", "#player", "#list")}
    assert len(set(column.values())) == 1, (
        f"the main column is not one surface: {column}"
    )
    assert background("#nav") != background("#list"), (
        "the side column is the same surface as the listing, so nothing "
        "separates them"
    )

    # Both surfaces are real colours from both palettes, so neither theme
    # can end up painting two of these the same by omission.
    for theme, block in (
        ("light", r':root, :root\[data-theme="light"\]'),
        ("dark", r':root\[data-theme="dark"\]'),
    ):
        found = re.search(block + r" \{(.*?)\n\}", css, re.DOTALL)
        assert found, theme
        values = dict(re.findall(r"(--[\w-]+):\s*([^;]+);", found.group(1)))
        for name in {background("#list"), background("#nav")}:
            assert name in values, f"{name} has no {theme} value"
        assert values[background("#list")] != values[background("#nav")], (
            f"in the {theme} theme the listing and the side column are the "
            "same colour"
        )


async def test_buttons_inside_text_carry_no_box(tmp_path):
    """The nav is a list of names, not a stack of cards. A border or a
    shadow round each one turns 453 artists into 453 boxes."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    quiet = re.search(
        r"\.quiet, #nav button.*?\{(.*?)\n\}", css, re.DOTALL
    )
    assert quiet, "no rule for the borderless buttons"
    assert "border-color: transparent" in quiet.group(1)
    assert "box-shadow: none" in quiet.group(1), (
        "the raised buttons' shadow leaks onto every nav entry"
    )


async def test_the_layout_puts_the_song_above_the_listing(tmp_path):
    """Inspector on top of the main column, listing beneath it, nav to
    the side. The listing gets the column's full width, which is what
    the compact density used to buy."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text
        css = (await client.get("/static/console.css")).text

    areas = re.search(r"grid-template-areas:(.*?);", css, re.DOTALL).group(1)
    assert '"header header"' in areas
    assert '"main   nav"' in areas

    # The inspector and the listing share one column, in that order.
    # What sits between them is the transport, asserted separately.
    main = re.search(r'<div id="main">(.*?)\n    </div>', body, re.DOTALL)
    assert main, "the two are not in one column"
    assert main.group(1).index('id="inspector"') < main.group(1).index('id="list"')

    # The listing is the only row that grows: everything above it takes
    # the height it needs, so with nothing selected it has the column.
    rows = re.search(r"grid-template-rows:\s*([^;]+)", 
                     re.search(r"#main \{(.*?)\n\}", css, re.DOTALL).group(1)
                     ).group(1)
    assert rows.endswith("minmax(0, 1fr)"), rows
    assert "1fr" not in rows.replace("minmax(0, 1fr)", ""), (
        f"more than the listing grows: {rows}"
    )


async def test_the_listing_is_placed_by_its_own_column(tmp_path):
    """`grid-area: list` named an area the parent no longer defines,
    which made an implicit track and squeezed the listing into a
    fraction of its column."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    block = re.search(r"#list \{([^}]*)\}", css).group(1)
    assert "grid-area" not in block, block


async def test_the_density_switch_is_gone(tmp_path):
    """Dropped with the compact density it controlled."""

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text
        css = (await client.get("/static/console.css")).text
        script = (await client.get("/static/console.js")).text

    assert 'id="density"' not in body
    assert "data-density" not in body
    assert "data-density" not in css
    assert "pypl2mp3.density" not in body + script


async def test_the_cover_sits_beside_the_fields(tmp_path):
    """Stacked above them it would push the form off the screen."""

    _make_song(tmp_path, "UNKNOWN", "Something", "aaaaaaaaaaa", junk=True)

    async with _client(create_app(tmp_path)) as client:
        panel = (await client.get("/fragments/inspector/aaaaaaaaaaa")).text
        css = (await client.get("/static/console.css")).text

    assert 'class="inspector-cover"' in panel
    assert 'class="inspector-detail"' in panel
    assert panel.index("inspector-cover") < panel.index("inspector-detail")

    body = re.search(r"#inspector-body \{([^}]*)\}", css).group(1)
    assert "display: flex" in body, body


async def test_the_inspector_shows_a_short_duration(tmp_path):
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        panel = (await client.get("/fragments/inspector/aaaaaaaaaaa")).text

    assert "00:00:00" not in panel, "the padded form is back"


async def test_a_label_sits_beside_its_field(tmp_path):
    """Three stacked pairs cost twice the height, in a panel that shares
    its column with the listing."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    rule = re.search(
        r"#inspector label, \.workbench-detail label \{(.*?)\n\}",
        css, re.DOTALL,
    )
    assert rule, "no rule for the label rows"
    block = rule.group(1)

    assert "display: grid" in block, (
        "flex leaves the label's bare text node in the flow, so each "
        "input starts wherever its word ended"
    )
    columns = re.search(r"grid-template-columns:\s*([^;]+)", block).group(1)
    assert re.match(r"^[\d.]+rem\s", columns), (
        f"the label column is not a fixed width ({columns!r}), so the "
        "three inputs will not share a left edge"
    )


async def test_the_cover_field_is_short_and_says_it_wants_a_url(tmp_path):
    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        panel = (await client.get("/fragments/inspector/aaaaaaaaaaa")).text

    label = re.search(r"<label>([^<]*)<input[^>]*cover_art_url", panel,
                      re.DOTALL)
    assert label, "no cover field"
    assert label.group(1).strip() == "Cover", label.group(1)

    placeholder = re.search(
        r'name="cover_art_url"[^>]*placeholder="([^"]*)"', panel, re.DOTALL
    )
    assert placeholder, "the field says nothing about what it wants"
    assert "http" in placeholder.group(1), (
        f"{placeholder.group(1)!r} does not say a URL is expected"
    )


async def test_the_two_panels_keep_the_same_fields(tmp_path):
    """The inspector and the workbench edit the same three tags. Letting
    their markup drift is how one of them quietly stops matching."""

    _make_song(tmp_path, "UNKNOWN", "Something", "aaaaaaaaaaa", junk=True)

    async with _client(create_app(tmp_path)) as client:
        panels = [
            (await client.get(f"/fragments/{which}/aaaaaaaaaaa")).text
            for which in ("inspector", "workbench")
        ]

    def fields(page):
        return re.findall(
            r"<label>\s*([^<]*?)\s*<input[^>]*name=\"(\w+)\"[^>]*"
            r"(?:placeholder=\"([^\"]*)\")?",
            page,
            re.DOTALL,
        )

    assert fields(panels[0]), "no fields in the inspector"
    assert fields(panels[0]) == fields(panels[1]), (
        f"inspector {fields(panels[0])} vs workbench {fields(panels[1])}"
    )


async def test_junkize_stands_with_the_other_song_actions(tmp_path):
    """Neither it nor Ask Shazam submits the form; both act on the song
    as it already is. Save is the only thing the form is for."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        panel = (await client.get("/fragments/inspector/aaaaaaaaaaa")).text

    tools = re.search(
        r'<p class="inspector-tools">(.*?)</p>', panel, re.DOTALL
    ).group(1)
    assert "/junkize" in tools, "Junkize is not beside Ask Shazam"
    assert "/shazam" in tools

    form = panel[panel.index("<form") : panel.index("</form>")]
    assert "/junkize" not in form, "it is still inside the form as well"

    # Destructive and not undoable, wherever it sits.
    button = re.search(r"<button[^>]*junkize[^>]*>", tools, re.DOTALL)
    assert button and "hx-confirm" in button.group(0), button


async def test_a_junk_song_is_offered_no_junkize(tmp_path):
    """It is already junk; the button would do nothing but destroy the
    filename it has left."""

    _make_song(tmp_path, "UNKNOWN", "Something", "aaaaaaaaaaa", junk=True)

    async with _client(create_app(tmp_path)) as client:
        panel = (await client.get("/fragments/inspector/aaaaaaaaaaa")).text

    assert "/junkize" not in panel


async def test_the_filename_sits_beside_the_button_that_rewrites_it(tmp_path):
    """Saving renames the file, so this is the line about to change."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        panel = (await client.get("/fragments/inspector/aaaaaaaaaaa")).text
        css = (await client.get("/static/console.css")).text

    actions = re.search(
        r'<p class="inspector-actions">(.*?)</p>', panel, re.DOTALL
    ).group(1)
    assert 'type="submit"' in actions
    assert "filename" in actions, "the filename is on a line of its own"
    assert actions.index("submit") < actions.index("filename")

    # A name can run to a hundred characters and must not push Save off
    # the row.
    rule = re.search(
        r"\.inspector-actions \.filename \{([^}]*)\}", css
    ).group(1)
    assert "text-overflow: ellipsis" in rule, rule
    assert "min-width: 0" in rule, rule
    assert 'title="' in panel, "truncated with no way to read the whole"


async def test_the_transport_sits_under_the_song_it_plays(tmp_path):
    """The inspector follows the queue, so the art, the tags and the
    transport all describe the same track. Grouping them beats the
    convention of pinning the bar to the foot of the window."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text
        css = (await client.get("/static/console.css")).text

    main = re.search(r'<div id="main">(.*?)\n    </div>', body, re.DOTALL)
    assert main, "no main column"
    inside = main.group(1)

    for part in ('id="inspector"', 'id="player"', 'id="list"'):
        assert part in inside, f"{part} left the main column"

    assert (
        inside.index('id="inspector"')
        < inside.index('id="player"')
        < inside.index('id="list"')
    ), "the three are not in that order"

    # Only the listing grows; everything above it takes the height it
    # needs. Asserted as a shape rather than a literal, so adding a row
    # — as the toolbar did — does not make this a lie.
    rows = re.search(
        r"grid-template-rows:\s*([^;]+)",
        re.search(r"#main \{(.*?)\n\}", css, re.DOTALL).group(1),
    ).group(1)
    assert rows.endswith("minmax(0, 1fr)"), rows
    assert "1fr" not in rows.replace("minmax(0, 1fr)", ""), rows

    # Placed by #main now. Naming an area the page grid no longer
    # defines makes an implicit track, which is how the listing once
    # ended up rendering at 40% of its column.
    player = re.search(r"#player \{([^}]*)\}", css).group(1)
    assert "grid-area" not in player, player
    assert "grid-template-areas" in css and "player" not in re.search(
        r"grid-template-areas:(.*?);", css, re.DOTALL
    ).group(1), "the page grid still reserves a row for it"


async def test_spacing_comes_from_a_scale(tmp_path):
    """Padding chosen per rule drifts, and that drift is what reads as
    careless — the same argument as the type scale."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    steps = set(re.findall(r"(--space-\d):", css))
    assert 4 <= len(steps) <= 7, steps

    scale = set(re.findall(r"--space-\d:\s*([\d.]+rem)", css))
    literal = {
        value
        for declaration in re.findall(r"\bpadding:\s*([^;]+)", css)
        for value in declaration.split()
        if value.endswith("rem")
    }
    assert literal <= scale, (
        f"padding written outside the scale: {sorted(literal - scale)}"
    )


async def test_every_main_block_shares_one_inset(tmp_path):
    """Four panels with four different margins read as four boxes that
    happen to touch, rather than as one page."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    def horizontal(selector):
        block = re.search(
            re.escape(selector) + r"\s*\{(.*?)\n\}", css, re.DOTALL
        ).group(1)
        value = re.search(r"\bpadding:\s*([^;]+)", block).group(1).split()
        # padding: a | a b | a b c | a b c d — the left is the 4th, or
        # the 2nd, or the 1st.
        return value[3] if len(value) == 4 else value[1] if len(value) > 1 \
            else value[0]

    insets = {
        selector: horizontal(selector)
        for selector in ("#header", "#nav", "#inspector", "#player")
    }
    assert set(insets.values()) == {"var(--block-pad-x)"}, insets

    # And the listing's rows line up with them, or the left edge of the
    # page zigzags between the panel above and the row below.
    assert "--row-pad-x: var(--block-pad-x)" in css


async def test_the_playlist_buttons_say_what_they_do(tmp_path):
    """Side by side in a 16rem column they came out as "Check fo…" and
    "Import n…", which is two truncations and no information."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    block = re.search(
        r"#nav \.playlist-actions \{([^}]*)\}", css
    ).group(1)
    assert "flex-direction: column" in block, block

    # They inherit the nav's flex: 1, which is what split the width.
    # Read every rule that names them, not the first: they are also
    # filled by a rule they share with Save, and which of the two comes
    # first in the file is not what this test is about.
    declared = "".join(
        body
        for selector, body in re.findall(
            r"\n([^\n{}]+(?:,\n[^\n{}]+)*)\{([^}]*)\}", css
        )
        if "#nav .playlist-actions button" in selector
    )
    assert "flex: none" in declared, declared


async def test_the_toolbar_carries_the_queue_readout(tmp_path):
    """Where you are, what comes next, and what to do with the selection
    — all about the queue, so they share one row. The counter replaces
    the song count, which said the same number less usefully."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text
        fragment = (await client.get("/fragments/list")).text

    bar = re.search(r'<div id="toolbar">(.*?)</div>', body, re.DOTALL)
    assert bar, "no toolbar"
    inside = bar.group(1)

    for part in ('id="player-position"', 'id="player-next"',
                 'data-queue-action="play"'):
        assert part in inside, part
    assert (
        inside.index('id="player-position"')
        < inside.index('id="player-next"')
        < inside.index("data-queue-action")
    ), "counter, preview, then the actions"

    assert "song(s)" not in body, "the old count is still rendered too"


async def test_the_toolbar_is_not_swept_away_by_a_refetch(tmp_path):
    """It holds the player's own readout now. Inside the fragment, every
    filter keystroke would take it away and paint it back blank."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        fragment = (await client.get("/fragments/list")).text
        body = (await client.get("/")).text

    assert "toolbar" not in fragment, fragment[:200]
    assert "data-queue-action" not in fragment

    # And it is outside every swap region, like the player itself.
    regions = re.findall(
        r'id="([^"]+)"[^>]*data-swap-region', body
    )
    toolbar_at = body.index('id="toolbar"')
    for region in regions:
        opening = body.index(f'id="{region}"')
        assert not (opening < toolbar_at < body.index(">", opening)), region


async def test_the_counter_still_shows_the_selection_size(tmp_path):
    """It replaced "928 song(s)", so it has to say that when nothing is
    playing — otherwise the count simply disappeared."""

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    assert 'total + " songs"' in script, (
        "with nothing playing the slot goes blank and the count is lost"
    )


async def test_the_scrub_bar_keeps_its_own_line(tmp_path):
    """Lost once to an over-eager edit: the rules went, the bar collapsed
    to a few pixels between two other controls, and only the rendered
    page showed it."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    timeline = re.search(r"#timeline \{(.*?)\n\}", css, re.DOTALL)
    assert timeline, "the timeline has no rule at all"
    assert re.search(r"flex:\s*1\b", timeline.group(1)), (
        f"the bar does not take the room the buttons leave: "
        f"{timeline.group(1)}"
    )

    seek = re.search(r"#seek \{(.*?)\n\}", css, re.DOTALL)
    assert seek, "the scrub bar has no rule at all"
    assert "position: relative" in seek.group(1)
    for part in ("#seek .track", "#seek .fill"):
        assert part in css, part

    # No playhead: where the colour changes *is* the position, and a
    # marker sitting on that boundary draws a second line saying the
    # same thing.
    assert "#seek .head" not in css


async def test_the_player_is_one_row(tmp_path):
    """Three small buttons over a full-width bar spent a row on very
    little. Side by side the bar still has almost all the width."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    block = re.search(r"#player \{(.*?)\n\}", css, re.DOTALL).group(1)
    assert "flex-wrap: wrap" not in block, (
        "the bar can still break onto a second line"
    )

    timeline = re.search(r"#timeline \{(.*?)\n\}", css, re.DOTALL).group(1)
    assert "100%" not in timeline, timeline
    assert "order:" not in timeline, (
        "ordering only mattered while it wrapped"
    )


async def test_the_player_carries_no_second_video_link(tmp_path):
    """The inspector already has one, and it sits beside the song it
    points at."""

    _make_song(tmp_path, "ARTIST", "Song", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text
        panel = (await client.get("/fragments/inspector/aaaaaaaaaaa")).text
        script = (await client.get("/static/console.js")).text

    player = re.search(r'<footer id="player".*?</footer>', body, re.DOTALL)
    assert "youtu.be" not in player.group(0), player.group(0)
    assert "player-video" not in body

    assert "youtu.be" in panel, "the inspector lost its link too"

    # The keyboard shortcut has to survive the link it used to read.
    assert 'window.open(\n            "https://youtu.be/" + queue[index].id'\
        in script, "tab no longer knows which video to open"


async def test_the_toolbar_is_marked_off_by_its_rule(tmp_path):
    """It shares the rows' surface deliberately, so the 1px rule under it
    is the only thing separating the two. Losing that leaves the queue
    readout looking like a song.

    It used to carry a green tint instead, on the grounds that a band a
    shade lighter than its rows reads as a rendering artefact. That tint
    is on the page header now, and it is still the only tinted thing on
    screen.
    """

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    def block(selector):
        # [^}]* rather than a dot-all lazy match: #list is a one-liner, so
        # looking for a closing brace on its own line ran past it into the
        # next rules and this test passed on the wrong text.
        found = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert found, selector

        return found.group(1)

    bar = block("#toolbar")
    assert re.search(r"background:\s*var\(--content-bg\)", bar), bar
    assert "border-bottom" in bar, (
        "nothing separates the queue readout from the songs under it"
    )

    assert re.search(r"background:\s*var\(--header-bg\)", block("#header")), (
        "the page header lost the tint that sets it apart from everything "
        "below it"
    )
    for theme, palette in (
        ("light", re.search(
            r':root, :root\[data-theme="light"\] \{(.*?)\n\}',
            css, re.DOTALL).group(1)),
        ("dark", _dark_block(css)),
    ):
        value = re.search(r"--header-bg:\s*#([0-9a-fA-F]{6})", palette)
        assert value, f"{theme} has no header colour"

        red, green, blue = (
            int(value.group(1)[i : i + 2], 16) for i in (0, 2, 4)
        )
        assert green > red and green >= blue, (
            f"{theme} #{value.group(1)} is not green-tinted"
        )


async def test_the_count_survives_the_lighter_header(tmp_path):
    """Measured in a browser: the dimmest text step fell to 3.1:1 on the
    tinted band, under the threshold for text this size. The counter
    carries a number, so it has to be read."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    rule = re.search(r"#player-position \{(.*?)\}", css, re.DOTALL).group(1)
    assert "var(--text-2)" in rule, rule
    assert "var(--text-3)" not in rule, (
        "the count is back on the dimmest step, which the header washes out"
    )


async def test_the_theme_offers_three_settings(tmp_path):
    """Following the system is a preference in its own right, and a
    two-state toggle silently drops it."""

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text

    choices = re.findall(r'data-theme-choice="(\w+)"', body)
    assert choices == ["auto", "light", "dark"], choices


async def test_the_theme_is_an_attribute_not_a_media_query(tmp_path):
    """A media query cannot express "unless the reader said otherwise",
    which is exactly what the middle setting means."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    assert "prefers-color-scheme" not in css, (
        "the palette still answers to the system regardless of the switch"
    )
    assert ':root[data-theme="dark"]' in css
    assert ':root, :root[data-theme="light"]' in css


async def test_both_themes_define_the_same_colours(tmp_path):
    """A colour named in one and missing from the other falls back to
    whatever the light block said — a difference nobody chose."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    def names(selector):
        block = re.search(
            re.escape(selector) + r"\s*\{(.*?)\n\}", css, re.DOTALL
        )
        assert block, selector
        return set(re.findall(r"(--[\w-]+)\s*:", block.group(1)))

    light = names(':root, :root[data-theme="light"]')
    dark = names(':root[data-theme="dark"]')

    assert dark, "the dark block defines nothing"
    assert dark <= light, f"only in dark: {sorted(dark - light)}"

    # Every colour the light block names must have a dark value; the
    # scale and the spacing are shared on purpose.
    colours = {
        name for name in light
        if not name.startswith(("--fs-", "--space-", "--font", "--pane-",
                                "--row-", "--nav-", "--btn-", "--field-",
                                "--toolbar-", "--block-", "--cover-",
                                "--wave-"))
    }
    assert colours <= dark, f"no dark value for: {sorted(colours - dark)}"


async def test_the_theme_is_applied_before_the_first_paint(tmp_path):
    """console.js loads at the end of the document. Waiting for it would
    show one theme and then visibly snap to the other."""

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text

    head = body[: body.index("</head>")]
    assert "pypl2mp3.theme" in head
    assert "prefers-color-scheme" in head, (
        "auto cannot resolve without asking the system"
    )
    assert "documentElement.dataset.theme" in head


async def test_an_explicit_theme_ignores_the_system_changing(tmp_path):
    """Auto follows; light and dark were asked for and must hold."""

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    handler = script[script.index('prefersDark.addEventListener("change"') :]
    handler = handler[: handler.index("\n  });")]
    assert 'themeChoice === "auto"' in handler, (
        "the system overrides a choice the reader made explicitly"
    )


async def test_the_theme_switch_marks_its_choice_in_text(tmp_path):
    """It is a preference, not an action. A filled segment would give it
    the weight of the one button on the page that writes to disk."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    chosen = re.search(
        r'#theme button\[aria-pressed="true"\] \{([^}]*)\}', css
    ).group(1)
    assert "background" not in chosen, chosen
    assert "color: var(--accent)" in chosen, chosen

    group = re.search(r"#theme \{([^}]*)\}", css).group(1)
    assert "border" not in group, (
        "the set is still boxed, which is what made it shout"
    )


def _filled_selectors(css):
    """Every selector painted with the accent as a background."""

    rules = re.findall(r"\n([^\n{}]+(?:,\n[^\n{}]+)*)\{([^}]*)\}", css)

    return [
        line.strip()
        for selector, body in rules
        if re.search(r"^\s*background: var\(--accent\);", body, re.M)
        for line in selector.split(",")
        if line.strip()
    ]


async def test_the_filter_button_is_not_filled(tmp_path):
    """Filtering is not a commitment and had no business looking like
    one: the listing narrows as you type and the button only repeats it.

    Stated as a ban rather than a whitelist, so a fourth panel that
    deserves a filled button can have one without editing this test —
    but nothing may quietly fill every submit button on the page.
    """

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    filled = _filled_selectors(css)
    assert filled, "nothing is filled at all"
    for selector in filled:
        assert "#filters" not in selector, f"{selector} fills Filter"
        assert selector != 'button[type="submit"]', (
            "this fills every submit button on the page, Filter included"
        )


async def test_a_playlist_button_is_filled_like_save(tmp_path):
    """Fetching a playlist's new songs is the point of the pane it sits
    in, the way saving is the point of the inspector. The two share one
    rule rather than two matching ones, so they cannot drift apart."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    filled = _filled_selectors(css)
    save = '#inspector button[type="submit"]'
    assert save in filled, filled
    assert "#nav .playlist-actions button" in filled, (
        "Check and Import are as quiet as the artist rows above them"
    )

    rules = re.findall(r"\n([^\n{}]+(?:,\n[^\n{}]+)*)\{", css)
    shared = [r for r in rules if save in r and ".playlist-actions" in r]
    assert shared, "they are filled by two separate rules that can drift"


async def test_ordinary_buttons_sit_back(tmp_path):
    """Secondary chrome: a hairline and the text, no surface of its own
    and no shadow lifting it off the page."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    rule = re.search(r"\nbutton \{(.*?)\n\}", css, re.DOTALL).group(1)
    assert "box-shadow" not in rule, rule
    assert "background: none" in rule, rule
    assert "border: 1px solid var(--line)" in rule, (
        "the border is still the strong one, which reads as a raised key"
    )


async def test_the_cover_is_a_fixed_square(tmp_path):
    """YouTube art arrives in every shape. A box that resized with it
    made the fields below jump each time you changed song."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    size = re.search(r"--cover-size:\s*([^;]+);", css).group(1).strip()
    assert size == "280px", size

    rule = re.search(
        r"\.inspector-cover \.cover \{([^}]*)\}", css, re.DOTALL
    ).group(1)
    assert "width: var(--cover-size)" in rule, rule
    assert "height: var(--cover-size)" in rule, (
        "only the width is pinned, so a 16:9 thumbnail still sets the height"
    )
    assert "object-fit: cover" in rule, (
        "without it a non-square image is stretched to fit the box"
    )


async def test_the_toolbar_icons_are_drawn_not_typed(tmp_path):
    """⤨ and ⚒ exist in Unicode but not in every system font, and where
    they do they render at whatever size that font decided — which was
    too small to read."""

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text
        css = (await client.get("/static/console.css")).text

    bar = re.search(r'<div id="toolbar">(.*?)</div>', body, re.DOTALL).group(1)
    assert bar.count("<svg") == 3, "not every action has a drawn icon"
    assert "⤨" not in bar and "⚒" not in bar and "▶" not in bar, bar

    # Sized against the label, not in absolute pixels: an icon smaller
    # than the word beside it is the problem being fixed.
    icon = re.search(r"\.icon \{([^}]*)\}", css).group(1)
    assert "em" in icon, icon
    assert "currentColor" in bar, "the icons do not follow the text colour"


async def test_shuffle_says_whether_the_queue_is_shuffled(tmp_path):
    """It reorders the queue once rather than switching a mode on, so
    the honest state to report is what order the queue is in."""

    async with _client(create_app(tmp_path)) as client:
        body = (await client.get("/")).text
        script = (await client.get("/static/console.js")).text
        css = (await client.get("/static/console.css")).text

    button = re.search(
        r'<button[^>]*data-queue-action="shuffle"[^>]*>', body, re.DOTALL
    ).group(0)
    assert 'aria-pressed="false"' in button, button

    assert 'button.setAttribute("aria-pressed"' in script, (
        "nothing ever updates the state it starts in"
    )
    # The toolbar builds the queue for all three of its buttons, so the
    # order it reports has to be the one it chose — not a constant.
    handler = script[script.index('queueButton.dataset.queueAction') :]
    handler = handler[: handler.index("return;")]
    decision = re.search(
        r"setQueue\([^;]*?,\s*0,\s*([^)]+)\)", handler, re.DOTALL
    )
    assert decision, handler
    assert decision.group(1).strip() == "random", (
        f"the toolbar reports {decision.group(1).strip()!r} whichever "
        "button was pressed, so Play all leaves the light on"
    )
    assert re.search(r"const random = action === \"shuffle\"", handler), (
        "nothing ties that value to which button was pressed"
    )

    # And the other two ways of building a queue leave it in order.
    assert "setQueue(entries, 0, false)" in script
    assert re.search(r"setQueue\(\s*entries,\s*entries\.findIndex", script)

    pressed = re.search(
        r'#toolbar button\[aria-pressed="true"\] \{([^}]*)\}', css
    ).group(1)
    assert "background" not in pressed, (
        "a fill would make the report look like the primary action"
    )
    assert "color: var(--accent)" in pressed


async def test_the_inspector_uses_the_width_it_has(tmp_path):
    """It was capped at 34rem, which broke a 70-character title over two
    lines while 600px of the column sat empty beside it."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    detail = re.search(
        r"\.inspector-detail \{([^}]*)\}", css, re.DOTALL
    ).group(1)
    assert "max-width" not in detail, (
        f"the panel is capped again, and the title with it: {detail}"
    )

    # The cap moves to the fields, which is what it was for: a text box
    # a thousand pixels wide is unreadable, a title is not.
    label = re.search(
        r"#inspector label, \.workbench-detail label \{(.*?)\n\}",
        css, re.DOTALL,
    ).group(1)
    assert "max-width" in label, (
        "nothing stops the fields stretching the whole column"
    )


async def test_the_side_column_scales_with_the_window(tmp_path):
    """Fixed at 16rem it was cramped on a wide screen and still took a
    fifth of a narrow one. Bounded on both sides: the floor keeps the
    longest playlist name legible, the ceiling stops it eating the
    listing on a very wide display."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    value = re.search(r"--pane-nav:\s*([^;]+);", css).group(1).strip()
    clamp = re.match(
        r"clamp\(\s*([\d.]+)rem\s*,\s*([\d.]+)vw\s*,\s*([\d.]+)rem\s*\)", value
    )
    assert clamp, f"{value} is not bounded on both sides"

    floor, preferred, ceiling = (float(g) for g in clamp.groups())
    assert floor < ceiling, value
    # A floor below what it replaced would be a narrowing, not a widening.
    assert floor >= 16, f"the floor {floor}rem is under the old fixed width"
    # And it must actually reach the ceiling on a screen someone owns.
    assert ceiling * 16 / (preferred / 100) <= 3000, (
        f"{ceiling}rem is unreachable below 3000px, so it is not a "
        "ceiling but a decoration"
    )


async def test_the_junk_checkbox_names_what_it_filters(tmp_path):
    """It read "junk only", which names the adjective and leaves out the
    noun — beside a search box and a Filter button, "only" could have
    been about playlists or artists as easily as about songs."""

    async with _client(create_app(tmp_path)) as client:
        page = (await client.get("/")).text

    label = re.search(
        r'<input type="checkbox" name="junk".*?>([^<]*)</label>',
        page,
        re.DOTALL,
    )
    assert label, page
    words = label.group(1).strip().lower()
    assert "junk" in words and "song" in words, (
        f"{words!r} does not say that what it keeps are songs"
    )


async def test_the_unfiltered_row_names_what_it_covers(tmp_path):
    """It used to read "All", one word sitting above a list of playlists
    where it could as easily have meant "all of them selected" as "none
    of them filtering".

    Both halves are asserted, not the sentence: the wording may change,
    but a row that says only "all songs" leaves out that they come from
    every playlist, and one that says only "all playlists" describes the
    list underneath it rather than the selection.
    """

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        nav = (await client.get("/fragments/nav")).text

    row = re.search(
        r'<button[^>]*data-playlist=""[^>]*>(.*?)</button>', nav, re.DOTALL
    )
    assert row, nav
    label = re.search(r'class="entry">(.*?)</span>', row.group(1), re.DOTALL)
    words = label.group(1).lower()
    assert "song" in words, f"{words!r} does not say what it selects"
    assert "playlist" in words, f"{words!r} does not say where from"


async def test_a_nav_row_is_one_button(tmp_path):
    """The count used to sit outside it, so the highlight stopped short
    of the row's edge — and hovering the count lit up something a click
    there would not act on."""

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        nav = (await client.get("/fragments/nav")).text
        css = (await client.get("/static/console.css")).text

    rows = re.findall(r"<li[^>]*>(.*?)</li>", nav, re.DOTALL)
    assert rows, "no rows"
    for row in rows:
        if "count" not in row:
            continue
        button = re.search(r"<button.*?</button>", row, re.DOTALL)
        assert button, row
        assert "count" in button.group(0), (
            "the count is outside the button, so part of the row is not "
            "clickable while all of it lights up"
        )

    rule = re.search(r"#nav button \{(.*?)\n\}", css, re.DOTALL).group(1)
    assert "width: 100%" in rule, (
        f"the button does not span its row: {rule}"
    )
    assert "justify-content: space-between" in rule, rule


async def test_the_nav_label_truncates_and_the_count_does_not(tmp_path):
    """453 artists, some with very long names, and a count that must
    stay readable at the right edge."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    entry = re.search(r"#nav button \.entry \{([^}]*)\}", css).group(1)
    assert "text-overflow: ellipsis" in entry, entry
    assert "min-width: 0" in entry, (
        "without it a long name refuses to shrink and pushes the count out"
    )

    count = re.search(r"#nav \.count \{([^}]*)\}", css, re.DOTALL).group(1)
    assert "flex: 0 0 auto" in count, count


async def test_the_waveform_is_drawn_inside_the_slider(tmp_path):
    """The claim the whole feature rests on.

    Click, drag and the arrow keys are bound to #seek and measured from
    its box. Drawing the waveform inside it means none of that had to be
    rewritten; drawing it beside #seek would have left a picture you
    cannot seek on and a control you cannot see.
    """

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        page = (await client.get("/")).text

    seek = re.search(r'<div id="seek"(.*?)</div>', page, re.DOTALL)
    assert seek, "no seek bar at all"
    assert 'id="waveform"' in seek.group(1), (
        "the canvas is outside the slider, so the bars and the hit area "
        "are two different rectangles"
    )


async def test_the_plain_bar_stays_as_the_fallback(tmp_path):
    """Peaks take half a second to compute the first time, and a file
    that cannot be decoded never gets any. Neither case may leave an
    empty box where the position used to be."""

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        page = (await client.get("/")).text
        css = (await client.get("/static/console.css")).text

    seek = re.search(r'<div id="seek"(.*?)</div>', page, re.DOTALL).group(1)
    assert 'class="track"' in seek and 'class="fill"' in seek, (
        "the fallback bar was deleted along with the redesign"
    )

    # Hidden by a rule, not by markup: the fallback has to be in the page
    # already when a fetch fails.
    hidden = re.search(
        r"#seek\.has-waveform \.track,\s*\n?#seek\.has-waveform \.fill \{"
        r"([^}]*)\}",
        css,
    )
    assert hidden and "display: none" in hidden.group(1), css[-600:]


async def test_a_waveform_arriving_does_not_move_the_page(tmp_path):
    """It arrives a beat after the song starts. If the box grew to fit
    it, every play would shove the listing down and back."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    box = re.search(r"\n#seek \{([^}]*)\}", css).group(1)
    assert "height: var(--wave-height)" in box, box

    for selector, body in re.findall(
        r"\n([^\n{}]+(?:,\n[^\n{}]+)*)\{([^}]*)\}", css
    ):
        if "has-waveform" in selector:
            assert "height:" not in body, (
                f"{selector.strip()} resizes the box when peaks land: {body}"
            )


async def test_the_cover_dissolves_between_songs(tmp_path):
    """The panel is replaced wholesale on every song, so the outgoing
    picture leaves with it and a transition has nothing to hold on to.
    The old one is kept as the container's background for the length of
    the fade and the new one comes up over it — a dissolve rather than a
    blank square between two songs.
    """

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text
        js = (await client.get("/static/console.js")).text

    fade = re.search(
        r"\n\.inspector-cover \.cover, \.workbench-cover \.cover \{"
        r"([^}]*)\}",
        css,
    )
    assert fade, "nothing fades"
    # A transition and not a keyframe animation: the reduced-motion rule
    # at the foot of the stylesheet neutralises durations, and an
    # animation would walk straight past it.
    assert "transition: opacity" in fade.group(1), fade.group(1)
    assert "animation" not in fade.group(1), fade.group(1)
    assert re.search(
        r"@media \(prefers-reduced-motion: reduce\) \{\s*"
        r"\* \{ transition-duration: [^}]*\}",
        css,
    ), "the rule this choice relies on is gone"

    # Transparent only with the class on, never by default: if the script
    # never runs — no swap, an error, a browser that skips load — the
    # cover is simply there, which is what it was before any of this.
    hidden = [
        selector
        for selector, body in re.findall(
            r"\n([^\n{}]+(?:,\s*\n?[^\n{}]+)*)\{([^}]*)\}", css
        )
        if ".cover" in selector and re.search(r"opacity: 0(?!\.)", body)
    ]
    assert hidden and all("arriving" in one for one in hidden), (
        f"a cover can be invisible with no class asking for it: {hidden}"
    )

    # The script makes it transparent and then opaque, in that order.
    assert 'img.classList.add("arriving");' in js, js[:0]
    assert js.count('img.classList.remove("arriving");') == 2, (
        "only one of the two endings puts the picture back"
    )
    assert "box.style.backgroundImage = 'url(\"' + outgoing + '\")';" in js

    # And the picture underneath goes once its job is done: left there it
    # would show through the next transparent cover, and every panel
    # after that would carry a ghost.
    assert js.count('box.style.backgroundImage = "";') == 2, (
        "the outgoing picture is left behind"
    )

    # It has to outlast the fade, and the length of the fade is the
    # stylesheet's to say. Repeated here it would be a second number that
    # must agree with the first, which is a number that will not.
    assert "fadeMillis(img)" in js, (
        "the script carries its own idea of how long the fade lasts"
    )
    assert "transitionDuration" in js, js[:0]
    assert not re.search(r"}, \d+\);", js.split("function crossfadeCover")[1]
                         .split("\n  document.body")[0]), (
        "a literal delay is back inside the crossfade"
    )

    # Bound unguarded, this ran on the imports poll — once a second, on
    # markup with no cover in it at all.
    hook = re.search(
        r'document\.body\.addEventListener\("htmx:afterSwap", function \(event\) \{'
        r"(.*?)\n  \}\);",
        js,
        re.DOTALL,
    )
    assert hook and "crossfadeCover(box)" in hook.group(1), "no guarded hook"
    assert ".inspector-cover, .workbench-cover" in hook.group(1), hook.group(1)


async def test_the_transport_says_which_way_the_queue_is_walked(tmp_path):
    """Pressing the back button does not step back once — it turns the
    player round, and a track ending then carries on backwards. The
    toolbar says so in words, but it is at the top of the page and the
    transport is at the bottom, which put the only sign of it three
    hundred pixels from the hand that did it.

    Written in one place, beside the readout that says the same thing in
    words: two writers would drift.
    """

    async with _client(create_app(tmp_path)) as client:
        js = (await client.get("/static/console.js")).text
        css = (await client.get("/static/console.css")).text

    # The attribute is set where the readout is, and cleared where the
    # readout goes blank: nothing is playing, so there is no walk.
    assert (
        'transport.dataset.direction = direction < 0 ? "backward" : "forward";'
        in js
    ), "the mark and the words could disagree"
    assert 'transport.removeAttribute("data-direction");' in js, (
        "an idle player still points somewhere"
    )
    written = js.count("transport.dataset.direction")
    assert written == 1, f"more than one writer for the mark: {written}"

    marked = re.search(
        r"\n(#transport\[data-direction[^{]*)\{([^}]*)\}", css
    )
    assert marked, "the mark is not drawn"
    selector, body = marked.groups()
    assert 'data-direction="forward"' in selector, selector
    assert 'data-direction="backward"' in selector, selector
    assert '[data-player-action="next"]' in selector, selector
    assert '[data-player-action="previous"]' in selector, selector

    # The icon carries it, not the frame. Both step buttons hold the
    # accent border at all times — they are a pair, and a border that
    # comes and goes makes them look like two different kinds of control
    # rather than one control in two states.
    assert "color: var(--accent)" in body, body
    assert "background" not in body, body
    assert "border" not in body, (
        f"the frame moves with the direction, so the pair never rests: "
        f"{body}"
    )

    pair = re.search(
        r'\n#transport \[data-player-action="previous"\],\s*\n'
        r'#transport \[data-player-action="next"\] \{([^}]*)\}',
        css,
    )
    assert pair, "the two step buttons are not framed alike"
    # Muted, not the full accent: at full strength two green frames
    # beside the filled play button made the transport the loudest thing
    # in the row, and the frames are there to hold it together rather
    # than to be read.
    assert "border-color: var(--accent-line)" in pair.group(1), pair.group(1)

    # The side not in use takes the same green, not grey: grey against
    # green reads as disabled, two different things, where the pair is
    # one thing pointing one way. One step above the frame, though — at
    # the frame's own value the glyph came out at 1.7:1 against the
    # player on a light screen, a shape you have to look for.
    button = re.search(r"\n#transport button \{([^}]*)\}", css).group(1)
    assert "color: var(--accent-dim)" in button, button
    assert "--accent-dim" != "--accent-line"  # they are two roles

    # And it exists in both palettes. Nothing else here would notice a
    # variable defined in one and not the other: the glyph would simply
    # inherit the light value onto the dark page.
    defined = len(re.findall(r"^  --accent-dim: ", css, re.MULTILINE))
    assert defined == 2, f"--accent-dim is set in {defined} palette(s)"

    # Except with nothing playing: there is no walk to point at, so the
    # whole transport goes neutral — frame and glyph both, the way the
    # play button already did on its own.
    idle = re.search(r"\n#player\.idle #transport button \{([^}]*)\}", css)
    assert idle, "an idle player keeps a lit transport"
    assert "border-color: var(--line-strong)" in idle.group(1), idle.group(1)
    assert "color: var(--text-3)" in idle.group(1), (
        f"an idle transport keeps green glyphs above a grey frame: "
        f"{idle.group(1)}"
    )


async def test_a_transport_button_is_big_enough_to_hit(tmp_path):
    """Sized to be hit, not merely clicked — and kept under the
    waveform's height, so making them comfortable does not make the whole
    player row taller."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    def rem(value):
        return float(value.removesuffix("rem"))

    button = re.search(r"\n#transport button \{([^}]*)\}", css).group(1)
    width = rem(re.search(r"width: ([\d.]+rem);", button).group(1))
    height = rem(re.search(r"height: ([\d.]+rem);", button).group(1))

    # 24 CSS px each way is the floor a pointer target is held to, and
    # these carry the three most-used gestures on the page.
    assert width * 16 >= 36, f"{width}rem is a narrow target"
    assert height * 16 >= 30, f"{height}rem is a short target"

    wave = float(
        re.search(r"--wave-height: (\d+)px;", css).group(1)
    )
    assert height * 16 <= wave, (
        f"a {height}rem button is taller than the {wave}px waveform beside "
        f"it, so the row grows to fit it"
    )


async def test_the_times_sit_in_the_band_under_the_baseline(tmp_path):
    """The reflection leaves the strip under the baseline quiet, which is
    the second thing the asymmetry buys. Either side of the box the two
    readouts were eighty pixels of width the picture now has instead.

    Out of flow whether or not peaks ever arrive: positioning them only
    once a waveform is showing would move the whole control the moment it
    landed.
    """

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    frame = re.search(r"\n#timeline \{([^}]*)\}", css).group(1)
    assert "position: relative" in frame, frame

    label = re.search(r"\n#timeline \.t \{([^}]*)\}", css).group(1)
    assert "position: absolute" in label, label
    assert re.search(r"bottom: (0|-\d+px);", label), label

    # What is under them is the seek control, and a click on the time is
    # a click on the timeline.
    assert "pointer-events: none" in label, label

    # Above the canvas, which needs saying: #seek is positioned too and
    # comes after these in the markup, so at equal z-index it paints over
    # them — the background was drawn and then covered, and the digits
    # only showed through where the bars happened to be transparent.
    assert re.search(r"z-index: [1-9]", label), label
    assert "position: relative" in re.search(
        r"\n#seek \{([^}]*)\}", css
    ).group(1), "the stacking this z-index answers to is gone"

    # On the player's own background: dim grey digits straight over the
    # played reflection were unreadable.
    assert "background: var(--content-bg)" in label, label

    # Qualified by #timeline, and that is load-bearing: the shared rule
    # is an id and a class, so a bare #player-elapsed loses to it and the
    # colour below never lands.
    ends = {
        name: body
        for name, body in re.findall(
            r"\n#timeline #player-(elapsed|total) \{([^}]*)\}", css
        )
    }
    assert set(ends) == {"elapsed", "total"}, ends
    assert "left:" in ends["elapsed"], ends
    assert "right:" in ends["total"], ends

    # One of them is where you are and moves; the other is a property of
    # the song and does not. The accent on the first says which is which
    # without a second word — and it is the colour of the bars behind it.
    assert "color: var(--accent)" in ends["elapsed"], ends["elapsed"]
    assert "color:" not in ends["total"], (
        f"both readouts the same colour says they are the same kind of "
        f"thing: {ends['total']}"
    )

    # And never conditional on the peaks having landed.
    for selector, body in re.findall(
        r"\n([^\n{}]+(?:,\n[^\n{}]+)*)\{([^}]*)\}", css
    ):
        if "has-waveform" in selector and re.search(r"\.t\b", selector):
            raise AssertionError(
                f"the readouts move when peaks land: {selector.strip()}"
            )


async def test_the_waveform_is_decoration_over_a_working_control(tmp_path):
    """The canvas carries no information a screen reader can use — the
    slider already reports the position as a number. Announcing it twice
    is worse than not announcing it."""

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        page = (await client.get("/")).text

    seek = re.search(r'<div id="seek"(.*?)</div>', page, re.DOTALL)
    assert 'role="slider"' in seek.group(0)
    assert 'tabindex="0"' in seek.group(0)
    assert 'aria-valuenow' in seek.group(0)

    canvas = re.search(r"<canvas[^>]*>", seek.group(1)).group(0)
    assert "aria-hidden" in canvas, canvas


async def test_the_reflection_is_shorter_and_fainter_than_the_crest(
    tmp_path,
):
    """The lower half is not the negative half of the signal — the peaks
    are absolute loudness and there is no negative half to draw. It is
    the same number a second time, shorter and fainter.

    Drawing it truthfully at full size would spend half the pixels
    repeating the shape above them, because for music the two sides are
    the same shape. The crest takes the larger share, and what the
    reflection buys in return is a baseline: bars standing on a line
    compare at a glance, where bars floating either side of a middle
    have to be compared in two directions at once.
    """

    async with _client(create_app(tmp_path)) as client:
        js = (await client.get("/static/console.js")).text

    mirror = float(re.search(r"const MIRROR = ([\d.]+);", js).group(1))
    ink = float(re.search(r"const MIRROR_INK = ([\d.]+);", js).group(1))
    assert 0 < mirror < 1, f"the reflection is not shorter: {mirror}"
    assert 0 < ink < 1, f"the reflection is not fainter: {ink}"

    body = re.search(
        r"\n  function paintWaveform\(\) \{(.*?)\n  \}\n", js, re.DOTALL
    ).group(1)

    # Two bars per peak, from the one number, on either side of a
    # baseline that is not the middle of the box.
    up, down = re.findall(r"brush\.fillRect\((.*)\);", body)
    assert "crest - up" in up, up
    assert "crest + gap" in down, down

    # On a whole number of device pixels, and stepped by one rather than
    # rounded to one. See the width test for what that buys.
    assert up.startswith("i * step"), up
    assert down.startswith("i * step"), down
    assert "bars[i] * crest" in body and "bars[i] * shadow" in body, body

    # And the baseline is where the split says, not halfway: a centred
    # drawing is exactly what this replaced.
    assert "(height - tall) / 2" not in body, "still drawn around a middle"


async def test_the_colour_boundary_moves_by_less_than_a_bar(tmp_path):
    """Rounded to a whole bar, the boundary sits still for the two-thirds
    of a second a four-minute song takes to cross one, then jumps. That
    jump was the whole of what made this look mechanical.

    The bar the playhead is inside is drawn twice — the played colour
    over the unplayed one, at the fraction of the bar already behind it.
    No animation and no timer: the position told instead of rounded.
    """

    async with _client(create_app(tmp_path)) as client:
        js = (await client.get("/static/console.js")).text

    body = re.search(
        r"\n  function paintWaveform\(\) \{(.*?)\n  \}\n", js, re.DOTALL
    ).group(1)

    assert "Math.round(done * bars.length)" not in body, (
        "the boundary is back to whole bars"
    )
    assert re.search(r"const into = .*mark - edge", body), body

    # The last bar is a real index: at the end of the song the fraction
    # reaches the count itself, and floor() alone would read past it.
    assert "Math.min(Math.floor(mark), bars.length - 1)" in body, body

    runs = re.findall(r"\n    band\(([^)]*)\);", body)
    assert runs == [
        "0, edge, played, 1",
        "edge, edge + 1, rest, 1",
        "edge, edge + 1, played, into",
        "edge + 1, bars.length, rest, 1",
    ], runs


async def test_a_bar_is_the_same_width_in_any_size_of_box(tmp_path):
    """The box is fluid — the window, the nav's clamp and the workbench
    all change it — and a fixed number of peaks spread across it made the
    bars thinner as it narrowed. Four hundred bars in six hundred pixels
    is half a pixel of bar and no gap at all, which is not a waveform but
    a smear.

    So the bar and the step to the next one are what stay fixed, and how
    many bars there are is what gives way. Same reading at any width,
    which is the whole point of a picture you are meant to aim at.
    """

    async with _client(create_app(tmp_path)) as client:
        js = (await client.get("/static/console.js")).text

    bar = int(re.search(r"const BAR = (\d+);", js).group(1))
    pitch = int(re.search(r"const PITCH = (\d+);", js).group(1))
    assert 0 < bar < pitch, f"no gap left between bars: {bar} of {pitch}"

    body = re.search(
        r"\n  function paintWaveform\(\) \{(.*?)\n  \}\n", js, re.DOTALL
    ).group(1)

    # How many bars follows from the width, and stops at the number of
    # peaks: past that there is nothing left to draw but detail nobody
    # measured.
    wanted = re.search(r"const wanted = (.*);", body).group(1)
    assert "Math.floor(width / (PITCH * dpr))" in wanted, wanted
    count = re.search(r"const count = (.*);", body).group(1)
    assert count == "Math.min(peaks.length, wanted)", count

    # The step is a whole number of device pixels. width / count is
    # 4.0135 at the size this is usually drawn, and rounding each bar's
    # own left edge instead gives the accumulated fraction back as one
    # five-pixel gap every seventy-five bars — a single wide gap in a
    # field of even ones, which is the first thing the eye finds. The
    # remainder is left unused at the right edge instead.
    step = re.search(r"const step = (.*);", body).group(1)
    assert "Math.floor(width / count)" in step, step

    # And when the box is wide enough to want more bars than there are
    # peaks, the step grows and the gap takes the slack — the bar keeps
    # its width, since fat bars are the thing this prevents.
    ink = re.search(r"const ink = ([^;]*);", body, re.DOTALL).group(1)
    assert "Math.min(Math.round(BAR * dpr), step" in " ".join(ink.split()), ink


async def test_the_bars_dropped_by_resampling_are_the_quiet_ones(tmp_path):
    """Reducing four hundred peaks to a hundred and fifty bars means
    choosing one number per group. The loudest, not the average: an
    average flattens a snare into the quiet either side of it, and where
    the loud parts are is the entire content of a waveform."""

    async with _client(create_app(tmp_path)) as client:
        js = (await client.get("/static/console.js")).text

    body = re.search(
        r"\n  function resample\(count\) \{(.*?)\n  \}\n", js, re.DOTALL
    ).group(1)

    assert "if (peaks[j] > top) top = peaks[j];" in body, body
    assert "/ (to - from)" not in body, "the groups are being averaged"

    # A group is never empty, however many bars are asked for.
    assert "Math.max(\n        from + 1," in body, body

    # And the answer is kept: this runs behind a repaint that happens
    # sixty times a second, and the shape only changes when the box or
    # the song does.
    assert "if (shown && shownCount === count) return shown;" in body, body
    fresh = re.search(
        r"\n  function loadWaveform\(id\) \{(.*?)\n  \}\n", js, re.DOTALL
    ).group(1)
    assert "shown = null;" in fresh, (
        "a new song would be drawn with the last one's bars"
    )


async def test_the_picture_follows_the_display_only_while_it_plays(tmp_path):
    """timeupdate fires four times a second — plenty for a clock, far too
    coarse for a boundary meant to slide. While the song plays the
    picture repaints on the display's own cadence instead, and the moment
    it stops so does the loop: a canvas redrawing sixty times a second
    behind a paused player is pure battery."""

    async with _client(create_app(tmp_path)) as client:
        js = (await client.get("/static/console.js")).text

    assert "window.requestAnimationFrame(followPlayhead)" in js
    assert "window.cancelAnimationFrame(frame)" in js

    bound = dict(
        re.findall(r'audio\.addEventListener\("(\w+)", (\w*Following)\)', js)
    )
    assert bound == {
        "play": "startFollowing",
        "pause": "stopFollowing",
        "ended": "stopFollowing",
    }, bound

    # Peaks routinely land after the song has started. Without this the
    # picture is correct and frozen until the next pause.
    arrival = re.search(
        r"function loadWaveform\(id\) \{(.*?)\n  \}\n", js, re.DOTALL
    ).group(1)
    assert "if (peaks && !audio.paused) startFollowing();" in arrival, arrival


async def test_the_player_leans_away_from_the_listing(tmp_path):
    """Which blocks belong together, said in whitespace.

    The inspector and the player share a background and are one thing —
    the song and the means to hear it. The listing is another, and says
    so by changing that background. Even padding all round would have
    given the seam inside the group as much room as the boundary between
    the two, which is the opposite of what the grouping means.
    """

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    scale = {
        name: float(value)
        for name, value in re.findall(r"(--space-\d): ([\d.]+)rem;", css)
    }
    assert scale, "no spacing scale to read"

    block = re.search(r"\n#player \{([^}]*)\}", css).group(1)
    padding = re.search(r"padding: ([^;]+);", block).group(1).split()
    assert len(padding) == 3, (
        f"padding is no longer top / sides / bottom: {padding}"
    )

    def rem(value):
        name = re.fullmatch(r"var\((--space-\d)\)", value)
        assert name, f"{value} is not on the spacing scale"

        return scale[name.group(1)]

    above, below = rem(padding[0]), rem(padding[2])
    assert below > above, (
        f"the player sits {above}rem from the song above it and {below}rem "
        "from the listing below, so the two boundaries read alike"
    )


async def test_the_inspector_is_visible_from_either_tab(tmp_path):
    """It sits above the tab strip, not inside a pane.

    That is what lets a click on an import row open a song without
    leaving the list of thirty you were reading — and why the click must
    not switch tabs to show you something already on screen.
    """

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        page = (await client.get("/")).text
        css = (await client.get("/static/console.css")).text
        script = (await client.get("/static/console.js")).text

    assert page.index('id="inspector"') < page.index('id="tabs"'), (
        "the inspector is below the tab strip, so a pane could cover it"
    )

    hidden = re.findall(
        r'body\[data-tab="[a-z]+"\]\s*([^{,]+)[,{]', css
    )
    assert not any("#inspector" in selector for selector in hidden), (
        f"a tab hides the inspector: {hidden}"
    )

    opener = script[script.index(".import-row[data-song-id]"):]
    opener = opener[: opener.index("\n    }")]
    assert "showTab" not in opener, (
        "opening a song from an import row switches tabs, which takes you "
        "away from the list to show what was already visible"
    )


async def test_an_icon_button_lays_its_contents_out_in_a_row(tmp_path):
    """Left to itself an inline svg sits on the text baseline: it hangs
    low against the letters and adds the descender's worth of height.

    That made Play this two pixels taller than the plain buttons beside
    it, with its glyph off centre. The rule is keyed on carrying an icon
    rather than on where the button happens to live, so the next one does
    not repeat it.
    """

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    rule = re.search(r"\nbutton:has\(\.icon\) \{([^}]*)\}", css)
    assert rule, (
        "icon buttons are laid out by location, so a button with an icon "
        "somewhere new inherits nothing"
    )
    assert "inline-flex" in rule.group(1), rule.group(1)
    assert "align-items: center" in rule.group(1), rule.group(1)


async def test_the_header_band_is_as_deep_above_as_below(tmp_path):
    """A border is part of the band the eye sees.

    The rule under the header is on its bottom edge only, so equal
    padding left the painted band a pixel deeper below the content than
    above it. The top pays for the line.
    """

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    block = re.search(r"\n#header \{(.*?)\n\}", css, re.DOTALL).group(1)

    border = re.search(r"border-bottom:\s*(\d+)px", block)
    assert border, block

    shared = re.search(r"\n  padding:\s*([^;]+);", block)
    assert shared, "the header no longer takes the inset every block shares"
    assert shared.group(1).split()[0] == "var(--block-pad-y)", shared.group(1)

    top = re.search(r"padding-top:\s*([^;]+);", block)
    assert top, "nothing pays for the rule under the header"
    assert top.group(1) == f"calc(var(--block-pad-y) + {border.group(1)}px)", (
        f"the top does not account for the {border.group(1)}px rule below: "
        f"{top.group(1)}"
    )


async def test_the_panel_says_when_it_is_holding_edits(tmp_path):
    """The mention is rendered always and revealed by the page, because
    only the page knows whether anything has been typed."""

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        panel = (await client.get("/fragments/inspector/aaaaaaaaaaa")).text
        css = (await client.get("/static/console.css")).text

    assert 'class="held"' in panel, panel[:400]

    hidden = re.search(r"\n\.held \{([^}]*)\}", css)
    shown = re.search(r"#inspector\.holding-edits \.held \{([^}]*)\}", css)
    assert hidden and "display: none" in hidden.group(1), css[-400:]
    assert shown and "display: inline" in shown.group(1), css[-400:]


async def test_nothing_to_play_offers_nothing(tmp_path):
    """The three buttons act on the selection. With nothing selected they
    stayed lit and did nothing, which reads as a broken page rather than
    an empty one."""

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    assert "button.disabled = empty" in script, (
        "the queue actions are never disabled, so an empty listing still "
        "offers to play itself"
    )


async def test_the_listing_follows_the_song_but_only_when_it_changes(tmp_path):
    """944 rows is 51 000 pixels: after a few skips the row that is lit
    is nowhere near the screen.

    Once per song, not per repaint — otherwise scrolling off to look at
    something else yanks the page straight back. `nearest` then does
    nothing when the row is already in view.
    """

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    assert 'scrollIntoView({ block: "nearest" })' in script, (
        "the listing never follows what is playing"
    )
    follow = script[script.index("if (currentId !== followed)"):]
    follow = follow[: follow.index("\n    }")]
    assert "followed = currentId" in follow, (
        "nothing remembers which song was followed, so every repaint "
        "scrolls the list back"
    )


async def test_select_all_answers_the_rows_as_well_as_commanding_them(
    tmp_path,
):
    """Left one-way it stayed ticked after every row had been unticked,
    saying the opposite of what the list showed."""

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    assert "paintPickAll" in script, "nothing ever reads the rows back"
    body = script[script.index("function paintPickAll()"):]
    body = body[: body.index("\n  }")]
    assert "all.checked = ticked === boxes.length" in body, body
    assert "indeterminate" in body, (
        "some ticked and some not is neither state, and HTML already has "
        "a third for it"
    )


async def test_the_two_counts_say_which_is_which(tmp_path):
    """944 in the header and 8 in the toolbar, meaning different things,
    with nothing on screen distinguishing them."""

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        page = (await client.get("/")).text
        script = (await client.get("/static/console.js")).text

    assert "in library" in page, "the header does not say what it counts"
    assert 'data-total=' in page, (
        "the toolbar has no way to know the library's size"
    )
    assert '" of " + library' in script, (
        "the toolbar reports a bare count, which reads as a total"
    )


async def test_the_junk_figure_does_what_it_looks_like(tmp_path):
    """An orange number that did nothing, beside a checkbox that did
    exactly the thing it looked like it offered."""

    _make_song(tmp_path, "UNKNOWN", "Song", "aaaaaaaaaaa", junk=True)

    async with _client(create_app(tmp_path)) as client:
        page = (await client.get("/")).text
        css = (await client.get("/static/console.css")).text
        script = (await client.get("/static/console.js")).text

    assert '<button type="button" id="junk-count"' in page, page[:600]
    rule = re.search(r"\n#junk-count \{([^}]*)\}", css)
    assert rule and "cursor: pointer" in rule.group(1), css[-400:]
    # And it is still drawn as the number it was, not as a button.
    assert "border: none" in rule.group(1), rule.group(1)
    assert 'input[name="junk"]' in script, "the click filters nothing"


async def test_the_listing_says_when_it_is_being_replaced(tmp_path):
    """A filter keystroke costs 300ms of settling plus about 280ms of
    fetching and laying out 944 rows. For over half a second the old
    list sits there looking like the answer."""

    async with _client(create_app(tmp_path)) as client:
        page = (await client.get("/")).text
        css = (await client.get("/static/console.css")).text

    form = re.search(r'<form id="filters"(.*?)>', page, re.DOTALL)
    assert form and 'hx-indicator="#list"' in form.group(1), form.group(1)

    rule = re.search(r"\n#list\.htmx-request \{([^}]*)\}", css)
    assert rule and "opacity" in rule.group(1), css[-400:]


async def test_the_side_column_gives_way_when_the_listing_is_squeezed(
    tmp_path,
):
    """Its clamp floor is 17rem, generous at 1600px and a third of the
    window at 820. Below the breakpoint the listing is what is scarce."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    wide = re.search(r"\n  --pane-nav: clamp\(([^)]+)\);", css)
    assert wide, css[:600]

    narrow = re.search(
        r"@media \(max-width: 60rem\) \{(.*?)\n\}", css, re.DOTALL
    )
    assert narrow and "--pane-nav" in narrow.group(1), (
        "the side column keeps its wide-screen floor on a narrow one"
    )


async def test_the_junk_mark_leads_and_the_count_ends_the_line(tmp_path):
    """Everywhere else on the page the warning comes before the thing it
    warns about — a junk row, a junk song in the panel.

    It also puts the counts back on the one right edge they line up on:
    trailing the mark pushed a flagged playlist's number left of every
    other, so a column of tabular numerals no longer lined up anywhere.
    """

    _make_song(tmp_path, "ARTIST", "Fine", "aaaaaaaaaaa")
    _make_song(tmp_path, "UNKNOWN", "Junk", "bbbbbbbbbbb", junk=True)

    async with _client(create_app(tmp_path)) as client:
        nav = (await client.get("/fragments/nav")).text

    count = re.search(
        r'<span class="count [^"]*junk[^"]*">\s*(.*?)\s*</span>', nav, re.DOTALL
    )
    assert count, nav
    body = count.group(1).strip()
    assert body.startswith("⚠"), f"the mark trails the number: {body!r}"
    assert body.rstrip().endswith("2"), body


async def test_both_lists_in_the_nav_say_how_long_they_are(tmp_path):
    """The artists heading counted itself and the playlists one did not,
    though they are the same kind of heading over the same kind of
    list."""

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")
    _make_song(tmp_path, "IAMX", "Spit", "bbbbbbbbbbb", playlist=OTHER)

    async with _client(create_app(tmp_path)) as client:
        nav = (await client.get("/fragments/nav")).text

    headings = re.findall(r"<h2>(.*?)</h2>", nav, re.DOTALL)
    assert len(headings) == 2, headings
    for heading in headings:
        assert "—" in heading, f"{heading.strip()!r} does not count itself"

    playlists = next(h for h in headings if "Playlist" in h)
    assert playlists.strip().endswith("2"), (
        f"two playlists on disk, heading says {playlists.strip()!r}"
    )


async def test_the_scope_line_sits_with_the_heading_it_qualifies(tmp_path):
    """It says what the count above it covers, so the two belong
    together rather than reading as a heading and then a remark."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    heading = re.search(r"\n#nav h2 \{([^}]*)\}", css).group(1)
    scope = re.search(r"\n#nav \.scope \{([^}]*)\}", css).group(1)

    below = re.search(r"margin: 0 0 var\((--space-\d)\)", heading)
    assert below, heading
    assert "calc(-1 *" in scope, (
        f"the scope line keeps the heading's full margin under it: {scope}"
    )


async def test_the_scope_line_offers_no_second_way_out(tmp_path):
    """The first row of this column is already exactly that escape, and
    one is enough."""

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        nav = (
            await client.get(
                "/fragments/nav?playlist=PL0000000000000000000000000000001"
            )
        ).text

    note = re.search(r'<p class="scope">(.*?)</p>', nav, re.DOTALL)
    assert note, nav
    assert "<button" not in note.group(1), note.group(1)
    assert note.group(1).strip().startswith("In playlist"), note.group(1)


async def test_the_whole_library_row_is_not_a_fourth_playlist(tmp_path):
    """It sits above the list rather than in it, so weight is what says
    so — otherwise it reads as one more playlist that happens to be
    first. Its count carries the same weight: the label and the number
    are one statement.
    """

    _make_song(tmp_path, "IAMX", "Kiss", "aaaaaaaaaaa")

    async with _client(create_app(tmp_path)) as client:
        nav = (await client.get("/fragments/nav")).text
        css = (await client.get("/static/console.css")).text

    assert 'class="whole-library' in nav, nav[:400]

    rule = re.search(
        r"\n#nav \.whole-library button,\s*\n#nav \.whole-library \.count \{"
        r"([^}]*)\}",
        css,
    )
    assert rule, "the row and its count are weighted apart, so they can drift"
    assert "font-weight: 600" in rule.group(1), rule.group(1)

    # And a playlist that is merely selected is not what this marks: the
    # current row already has its own weight, from its own rule.
    current = re.search(r"\n#nav li\.current button \{([^}]*)\}", css)
    assert current and "font-weight: 600" in current.group(1), css[-400:]


async def test_the_side_column_is_the_frame(tmp_path):
    """Where chrome stops and content starts.

    The nav is the frame. Everything in the main column — the song, its
    transport, the toolbar and the rows — is on the content surface, and
    the tab strip paints nothing of its own, so it takes whatever is
    behind it, which is that same surface.
    """

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    def rule(selector):
        found = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert found, selector

        return found.group(1)

    def background(selector):
        colour = re.search(r"background:\s*var\((--[\w-]+)\)", rule(selector))
        assert colour, f"{selector} paints no background"

        return colour.group(1)

    assert background("#nav") == "--frame-bg", background("#nav")
    for content in ("#toolbar", "#inspector", "#player", "#list"):
        assert background(content) == "--content-bg", (
            f"{content} is not on the content surface"
        )
    assert background("#header") != background("#nav"), (
        "the page header lost the tint that sets it apart from the frame"
    )

    # The strip paints nothing, so it cannot disagree with what is under
    # it — but it keeps the rule that marks where the panes begin.
    assert "background" not in rule("#tabs"), rule("#tabs")
    assert "border-bottom" in rule("#tabs"), rule("#tabs")


async def test_the_two_palettes_assign_the_surfaces_oppositely(tmp_path):
    """On a light screen the content wants the whiter surface and the
    frame the tinted one; on a dark screen it is the frame that lifts.

    Named as roles rather than picked at each selector, so the swap is
    two lines in a palette instead of a dozen scattered decisions — and
    so that a theme cannot accidentally give both roles the same surface.
    """

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    palettes = {
        "light": re.search(
            r':root, :root\[data-theme="light"\] \{(.*?)\n\}', css, re.DOTALL
        ).group(1),
        "dark": _dark_block(css),
    }

    roles = {}
    for theme, block in palettes.items():
        found = dict(
            re.findall(r"(--(?:content|frame)-bg):\s*var\((--[\w-]+)\)", block)
        )
        assert set(found) == {"--content-bg", "--frame-bg"}, (
            f"the {theme} palette does not assign both roles: {found}"
        )
        assert found["--content-bg"] != found["--frame-bg"], (
            f"the {theme} palette gives content and frame the same surface"
        )
        roles[theme] = found

    assert roles["light"]["--content-bg"] == roles["dark"]["--frame-bg"], (
        f"the two palettes do not swap the surfaces: {roles}"
    )
    assert roles["light"]["--frame-bg"] == roles["dark"]["--content-bg"], roles


async def test_a_field_stands_off_its_surroundings_in_both_themes(tmp_path):
    """A field level with the surface it sits on has only its border left
    to say it is a field, and that border is a hairline at 9% opacity.

    The two palettes get there from opposite directions: on a light
    screen the field sits below the white content, on a dark one it lifts
    above it. Both are one step of about ten, measured, so neither theme
    ends up with a field nobody can see.
    """

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    field = re.search(
        r'input\[type="search"\], input\[type="text"\], input\[type="url"\] '
        r"\{([^}]*)\}",
        css,
    )
    assert field, "no rule paints the fields"
    assert "background: var(--sunken)" in field.group(1), field.group(1)

    def luminance(value):
        digits = value.strip().lstrip("#")
        red, green, blue = (int(digits[i:i + 2], 16) for i in (0, 2, 4))

        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    for theme, block in (
        ("light", re.search(
            r':root, :root\[data-theme="light"\] \{(.*?)\n\}',
            css, re.DOTALL).group(1)),
        ("dark", _dark_block(css)),
    ):
        values = dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6});", block))
        assert "--sunken" in values, f"{theme} has no field colour"

        content = values["--surface" if theme == "light" else "--bg"]
        step = abs(luminance(values["--sunken"]) - luminance(content))
        assert step > 6, (
            f"in the {theme} theme a field is {step:.1f} from the surface it "
            "sits on, which leaves only a 9% hairline to mark it"
        )


async def test_a_clicked_transport_button_hands_the_focus_back(tmp_path):
    """Chrome does not ring a button clicked with the pointer, but it
    rings it the moment the next key is pressed. So clicking next and
    then reaching for the arrow keys lit up a button that had nothing to
    do with the change — the arrows are handled on the document.

    event.detail is the click count, and it is 0 when a button is
    activated from the keyboard. Blurring only when it is not is what
    leaves Tab and Enter working exactly as they did, ring included.
    """

    async with _client(create_app(tmp_path)) as client:
        script = (await client.get("/static/console.js")).text

    handler = script[script.index('closest("[data-player-action]")'):]
    handler = handler[: handler.index("\n      return;")]

    assert "playerButton.blur()" in handler, (
        "a clicked transport button keeps the focus, so the next key press "
        "rings it"
    )
    assert "event.detail > 0" in handler, (
        "the focus is dropped however the button was activated, which "
        "breaks operating it from the keyboard"
    )


async def test_the_last_field_leads_somewhere_visible(tmp_path):
    """Tab from the last field lands on Save, the only place a keyboard
    can reach outside the fields themselves. Taking the ring away left
    that one step blind.

    Drawn inside the button, in the button's own text colour: an accent
    ring around an accent fill would be the ring that was removed, and it
    would light up again after a pointer click. This one cannot —
    clicking Save submits the form, and the panel that replaces it takes
    the button with it.
    """

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    rule = re.search(
        r'#inspector button\[type="submit"\]:focus-visible,\s*\n'
        r'\.workbench-detail button\[type="submit"\]:focus-visible \{'
        r"([^}]*)\}",
        css,
    )
    assert rule, "the step out of the fields is invisible again"
    assert "solid var(--accent-text)" in rule.group(1), rule.group(1)
    # Negative, not an exact figure: how thick the ring reads and how much
    # green it leaves around itself are a matter of taste, and pinning the
    # numbers made this test fail on every adjustment while checking
    # nothing. What it must never be is zero or positive — that draws the
    # ring outside the button, which is the accent-on-accent ring that was
    # removed.
    assert re.search(r"outline-offset: -\d+px", rule.group(1)), (
        "the ring is drawn outside the button, which is the ring that was "
        "removed"
    )

    # And it stays the exception: no other button gets one back.
    rings = [
        selector
        for selector, body in re.findall(
            r"\n([^\n{}]+(?:,\n[^\n{}]+)*)\{([^}]*)\}", css
        )
        if ":focus-visible" in selector
        # (?!none) after optional space, and \S so the space itself
        # cannot satisfy it: written as [^;n] this matched "outline:
        # none" through the space and counted every suppression as a ring.
        and re.search(r"outline:\s*(?!none)\S", body)
    ]
    assert len(rings) == 1, f"more than the one step has a ring: {rings}"
