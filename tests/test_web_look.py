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


async def test_dark_text_is_not_near_white(tmp_path):
    """Near-white on near-black glares, and on 900 rows every line is
    shouting. The ramp is deliberately softened."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    dark = css[css.index("prefers-color-scheme: dark"):]
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

    dark = css[css.index("prefers-color-scheme: dark"):]
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


async def test_the_listing_is_the_bright_surface_not_the_chrome(tmp_path):
    """Reported as "all the songs are selected", and it was exactly that.

    The listing had --bg and the panels either side had --surface, so in
    the light theme 927 rows sat on a tinted band between two white
    columns. Content is bright; the chrome around it steps back.
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

    assert background("#list") == "--surface", (
        "the songs sit on the page colour while the chrome is raised"
    )
    for chrome in ("#nav", "#inspector", "#header", "#player"):
        assert background(chrome) == "--bg", (
            f"{chrome} is brighter than the content it frames"
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
    button = re.search(
        r"#nav \.playlist-actions button \{([^}]*)\}", css
    ).group(1)
    assert "flex: none" in button, button


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


async def test_the_listing_header_is_tinted_apart_from_its_rows(tmp_path):
    """Header and rows are both surfaces, so a difference in lightness
    alone reads as a rendering artefact. A trace of the accent says the
    row belongs to the selection it describes."""

    async with _client(create_app(tmp_path)) as client:
        css = (await client.get("/static/console.css")).text

    bar = re.search(r"#toolbar \{(.*?)\n\}", css, re.DOTALL).group(1)
    assert "background: var(--header-bg)" in bar, bar

    listing = re.search(r"#list \{([^}]*)\}", css).group(1)
    assert "--header-bg" not in listing, "the header no longer stands apart"

    for theme, block in (
        ("light", css[: css.index("prefers-color-scheme: dark")]),
        ("dark", css[css.index("prefers-color-scheme: dark") :]),
    ):
        value = re.search(r"--header-bg:\s*#([0-9a-fA-F]{6})", block)
        assert value, f"{theme} has no header colour"

        red, green, blue = (
            int(value.group(1)[i : i + 2], 16) for i in (0, 2, 4)
        )
        assert green > red and green >= blue, (
            f"{theme} #{value.group(1)} is not green-tinted"
        )
        # Tinted, not coloured: a saturated band would shout louder than
        # anything it contains.
        assert max(red, green, blue) - min(red, green, blue) <= 24, (
            f"{theme} #{value.group(1)} is too saturated for a background"
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
