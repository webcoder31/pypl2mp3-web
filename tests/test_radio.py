"""The radio: a listing ordered as a walk, and the panel beside it."""

import re
from pathlib import Path

import httpx
import pytest
from mutagen.id3 import ID3, TXXX

from pypl2mp3.libs.features import FEATURE_COUNT, TIMBRE, store_features
from pypl2mp3.services.find_song import song_key
from pypl2mp3.web.app import create_app

PLAYLIST_ID = "PL0000000000000000000000000000001"
PLAYLIST = f"Owner - Alpha [{PLAYLIST_ID}]"
_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _song(repo: Path, at: int, timbre: float, artist="ARTIST") -> str:
    """One song at a chosen place along the timbre axis."""

    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)

    vid = f"{at:011d}"
    path = folder / f"{artist} - Song {at} [{vid}].mp3"
    path.write_bytes(_MP3_FRAME * 8)

    frames = ID3()
    frames.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
    frames.save(path)

    vector = [0.0] * FEATURE_COUNT
    for dim in range(TIMBRE.start, TIMBRE.stop):
        vector[dim] = timbre
    store_features(path, vector)

    return song_key(PLAYLIST_ID, vid)


def _line(repo: Path, count: int = 6) -> list[str]:
    """Songs evenly spaced along one axis, so the walk is predictable."""

    return [_song(repo, at, float(at)) for at in range(count)]


def _client(repo: Path):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(repo)),
        base_url="http://test",
    )


def _ids(page: str) -> list[str]:
    return re.findall(r'data-song-id="(\w+)"', page)


def _offered(panel: str) -> list[str]:
    """The neighbours only. The panel lives inside the inspector now, and
    that carries the inspected song's own id as well."""

    return re.findall(
        r'class="neighbour[^"]*"[^>]*data-song-id="(\w+)"', panel, re.S
    )


async def test_the_radio_orders_the_listing_as_a_walk(tmp_path):
    """Chosen from a song in the middle, the listing steps outwards
    rather than staying where the alphabet left it."""

    keys = _line(tmp_path)

    async with _client(tmp_path) as client:
        page = (await client.get(
            f"/fragments/list?order=radio&start={keys[3]}"
        )).text

    found = _ids(page)

    assert found[0] == "00000000003", "the walk does not start where asked"
    assert found[1] in ("00000000002", "00000000004")
    assert len(found) == 6 and len(set(found)) == 6


async def test_the_radio_without_a_starting_song_begins_anywhere(tmp_path):
    """Choosing the radio while nothing plays is the ordinary case — the
    icon is there before the music is — and it used to mean the top of
    the listing. The same song every time, and since every step after it
    follows from it, the same walk every time: a library with nine
    hundred ways in offered one.

    Somewhere at random instead, and only from the songs the space
    knows. A key it does not know is ignored and the walk falls back to
    the top, which is the thing this is here to stop.
    """

    _line(tmp_path, count=12)

    seen = set()
    async with _client(tmp_path) as client:
        for _ in range(10):
            page = (await client.get("/fragments/list?order=radio")).text
            seen.add(_ids(page)[0])

    assert len(seen) > 1, (
        f"ten runs all began on {seen}, so the start is not being drawn"
    )


async def test_the_walk_is_the_same_whenever_it_is_told_where_to_begin(
    tmp_path,
):
    """The listing is refetched for every filter keystroke, every save
    and every playlist change. If each one drew a fresh start the rows
    would reshuffle under the reader — so the start is drawn once and
    carried, and asking with it must give the same walk back every
    time."""

    keys = _line(tmp_path, count=12)

    async with _client(tmp_path) as client:
        walks = [
            _ids((await client.get(
                f"/fragments/list?order=radio&start={keys[7]}"
            )).text)
            for _ in range(4)
        ]

    assert walks[0][0] == "00000000007", walks[0][0]
    assert all(walk == walks[0] for walk in walks), walks


async def test_the_page_carries_back_where_the_walk_began(tmp_path):
    """The page cannot work out where the server started: the walk is
    drawn there and the rows arrive already in it. So the answer comes
    back in the form, and every refetch after the first asks for that
    walk by name.

    In radio order the first row is the start by construction, so there
    is nothing to hand back separately — the field and the first row are
    the same key.
    """

    _line(tmp_path, count=12)

    async with _client(tmp_path) as client:
        page = (await client.get("/?order=radio")).text

    field = re.search(
        r'id="start-field"[^>]*value="([^"]*)"', page, re.S
    )
    assert field, "the form does not carry the start back"

    rows = re.findall(r'data-song-key="(\w+)"', page)
    assert field.group(1), "the start came back empty"
    assert field.group(1) == rows[0], (field.group(1), rows[:2])


async def test_a_song_with_no_vector_is_last_in_the_walk(tmp_path):
    """Where a song its playlist has dropped goes, and for the same
    reason: it has no place in the order the others are in."""

    _line(tmp_path, count=3)

    folder = tmp_path / PLAYLIST
    bare = folder / "ARTIST - Song 9 [00000000009].mp3"
    bare.write_bytes(_MP3_FRAME * 8)
    frames = ID3()
    frames.add(TXXX(encoding=3, desc="YouTube ID", text="00000000009"))
    frames.save(bare)

    async with _client(tmp_path) as client:
        page = (await client.get("/fragments/list?order=radio")).text

    assert _ids(page)[-1] == "00000000009"


async def test_the_walk_stays_inside_the_filter(tmp_path):
    """The radio may only offer what it could actually play, and what it
    could play is what the listing holds."""

    _line(tmp_path, count=4)
    _song(tmp_path, 9, 0.5, artist="SOMEBODY ELSE")

    async with _client(tmp_path) as client:
        page = (await client.get(
            "/fragments/list?order=radio&artist=SOMEBODY+ELSE"
        )).text

    assert _ids(page) == ["00000000009"]


async def test_the_panel_names_five_neighbours_nearest_first(tmp_path):
    keys = _line(tmp_path, count=8)

    async with _client(tmp_path) as client:
        panel = (await client.get(f"/fragments/inspector/{keys[0]}")).text

    found = _offered(panel)

    assert len(found) == 5
    assert found[0] == "00000000001", found


async def test_the_panel_says_how_close_and_along_which_axis(tmp_path):
    """The percentile is a rank among every pair in the selection, and
    the facet is the smallest of the four the distance was made of —
    both already computed, neither invented for the display."""

    keys = _line(tmp_path, count=8)

    async with _client(tmp_path) as client:
        panel = (await client.get(f"/fragments/inspector/{keys[0]}")).text

    assert re.search(r'data-closeness="\d', panel), panel[:400]

    # One of the four, and not "timbre" in particular: these fixtures
    # vary along the timbre alone, so the other three facets are
    # identical — and the facet reported is the one where the gap is
    # *smallest*, which is any of the three that are zero. Which axis
    # wins on real songs is what test_similarity pins down; what this
    # one holds is that the panel says an axis at all.
    facets = re.findall(r'class="neighbour-why">(\w+)<', panel)
    assert len(facets) == 5
    assert set(facets) <= {"timbre", "rhythm", "colour", "dynamics"}, facets

    # And the marks are not all the same, or they would say nothing.
    assert len(set(re.findall(r'data-closeness="(\d)"', panel))) > 1


async def test_the_panel_only_offers_what_the_filter_holds(tmp_path):
    """The radio may only offer what it could actually play, and what it
    could play is what the listing holds.

    The other artist's songs are placed *nearer* along the timbre axis
    than this artist's own second song, so a panel that ignored the
    filter would prefer them — which is what makes this discriminating
    rather than merely true. An earlier version put the filtered song
    last in the default order, where "nothing comes after it" explained
    the empty panel just as well as the filter did.
    """

    # Named to sort *before* the others, so that unfiltered this song
    # has the whole line still ahead of it. Named after them, "nothing
    # comes after it" explained the empty panel as well as the filter
    # did, and the test held nothing.
    _line(tmp_path, count=4)
    mine = _song(tmp_path, 8, 0.1, artist="AAA ELSE")
    _song(tmp_path, 9, 9.0, artist="AAA ELSE")

    async with _client(tmp_path) as client:
        panel = (await client.get(
            f"/fragments/inspector/{mine}?artist=AAA+ELSE"
        )).text

    assert _offered(panel) == ["00000000009"], panel


async def test_a_song_nobody_analysed_has_a_panel_that_says_so(tmp_path):
    """Rather than an empty box that looks like a failure to load."""

    folder = tmp_path / PLAYLIST
    folder.mkdir(parents=True)
    bare = folder / "ARTIST - Song 9 [00000000009].mp3"
    bare.write_bytes(_MP3_FRAME * 8)
    frames = ID3()
    frames.add(TXXX(encoding=3, desc="YouTube ID", text="00000000009"))
    frames.save(bare)

    async with _client(tmp_path) as client:
        panel = (await client.get(
            f"/fragments/inspector/{song_key(PLAYLIST_ID, '00000000009')}"
        )).text

    assert _offered(panel) == []
    assert "not been analysed" in panel or "no neighbours" in panel.lower()


async def test_in_the_walk_the_first_neighbour_is_the_next_row(tmp_path):
    """The invariant the whole design rests on. If this falls, "do
    nothing and the closest plays next" has become false — and that is
    the whole promise."""

    keys = _line(tmp_path, count=8)

    async with _client(tmp_path) as client:
        listing = (await client.get(
            f"/fragments/list?order=radio&start={keys[3]}"
        )).text
        panel = (await client.get(
            f"/fragments/inspector/{keys[3]}?order=radio&start={keys[3]}"
        )).text

    rows = re.findall(r'data-song-key="(\w+)"', listing)
    offered = re.findall(
        r'class="neighbour[^"]*"[^>]*data-song-key="(\w+)"', panel
    )

    assert offered, panel[:300]
    assert offered[0] == rows[1], (
        f"the panel offers {offered[0]} first, the listing plays {rows[1]}"
    )
    # Both states are rendered on every row and a class decides which
    # one shows, so that lining a song up by hand can move the mark
    # without a round trip. What must be true of the markup is that
    # exactly one row carries the class.
    assert panel.count("neighbour is-next") == 1, "exactly one NEXT"
    assert panel.index("is-next") < panel.index('data-song-key="%s"' % (
        offered[1] if len(offered) > 1 else offered[0]
    )), "the mark is not on the first"


async def test_the_map_places_every_song_and_colours_twelve_genres(tmp_path):
    """Position from the sound, colour from the genre: two independent
    sources, so the picture checks itself. Colours that clump mean the
    vectors caught something; colours peppered evenly mean they did
    not."""

    import json
    from mutagen.id3 import TCON

    keys = _line(tmp_path, count=8)
    folder = tmp_path / PLAYLIST
    for at, path in enumerate(sorted(folder.glob("*.mp3"))):
        frames = ID3(path)
        frames.add(TCON(encoding=3, text="Techno" if at < 4 else "Folk"))
        frames.save(path)

    async with _client(tmp_path) as client:
        said = (await client.get("/map/points")).json()

    assert len(said["points"]) == 8
    assert set(said["genres"]) == {"Techno", "Folk"}

    for one in said["points"]:
        assert len(one["at"]) == 3
        assert one["known"] is True
        assert one["shade"] >= 0
        assert one["key"] in keys


async def test_a_song_nobody_analysed_is_on_the_map_and_says_so(tmp_path):
    """It has no place in the cloud, so it goes on the shell around it —
    and the point carries the fact, because a grey dot in the crowd and
    a grey dot on the shell mean different things."""

    _line(tmp_path, count=4)

    folder = tmp_path / PLAYLIST
    bare = folder / "ARTIST - Song 9 [00000000009].mp3"
    bare.write_bytes(_MP3_FRAME * 8)
    frames = ID3()
    frames.add(TXXX(encoding=3, desc="YouTube ID", text="00000000009"))
    frames.save(bare)

    async with _client(tmp_path) as client:
        said = (await client.get("/map/points")).json()

    unknown = [one for one in said["points"] if not one["known"]]
    assert len(unknown) == 1
    assert unknown[0]["id"] == "00000000009"


async def test_the_map_stays_inside_the_filter(tmp_path):
    _line(tmp_path, count=4)
    _song(tmp_path, 9, 0.5, artist="SOMEBODY ELSE")

    async with _client(tmp_path) as client:
        said = (await client.get("/map/points?artist=SOMEBODY+ELSE")).json()

    assert [one["id"] for one in said["points"]] == ["00000000009"]


async def test_the_same_selection_is_placed_once_and_a_new_one_afresh(
    tmp_path
):
    """Two seconds of numpy over the library, so asking twice for the
    same songs must not pay it twice.

    And the narrow selection is asked for first, on purpose: a cache
    that answers every question with the same drawer would then be
    handed songs it has never placed. Asking the same thing twice
    proves nothing — it was the first version of this test, and it
    passed with the key replaced by a constant.
    """

    _line(tmp_path, count=4)
    _song(tmp_path, 9, 0.5, artist="SOMEBODY ELSE")

    async with _client(tmp_path) as client:
        narrow = (await client.get(
            "/map/points?artist=SOMEBODY+ELSE"
        )).json()
        whole = (await client.get("/map/points")).json()
        again = (await client.get("/map/points")).json()

    assert len(narrow["points"]) == 1
    assert len(whole["points"]) == 5

    assert [one["at"] for one in whole["points"]] == \
           [one["at"] for one in again["points"]], "placed twice"


async def test_saving_a_song_brings_its_neighbours_back_with_it(tmp_path):
    """Saving re-renders the whole panel, and the panel now holds the
    five nearest. Without the selection travelling with the POST they
    came back empty, which the panel reported as "this song has not been
    analysed yet" — a sentence about the file, for what was really a
    missing argument. The file is untouched: a save keeps the vector and
    the waveform through the rename, which is why they live in the MP3.
    """

    keys = _line(tmp_path, count=8)

    async with _client(tmp_path) as client:
        before = (await client.get(f"/fragments/inspector/{keys[0]}")).text
        assert len(_offered(before)) == 5

        after = (await client.post(
            f"/songs/{keys[0]}/fix",
            data={"artist": "AAA RENAMED", "title": "Also Renamed",
                  "cover_art_url": ""},
            headers={"HX-Request": "true"},
        )).text

    assert "not been analysed" not in after, after[:400]
    assert len(_offered(after)) == 5, _offered(after)


async def test_the_save_form_carries_the_selection_and_not_the_filter_artist(
    tmp_path
):
    """Both forms have an `artist` field. Posting the filter's alongside
    the song's — which `hx-include` would do — would write the name you
    were filtering by onto the song you were correcting."""

    keys = _line(tmp_path, count=4)

    async with _client(tmp_path) as client:
        panel = (await client.get(
            f"/fragments/inspector/{keys[0]}?artist=ARTIST&q=Song"
        )).text

    action = re.search(r'<form hx-post="([^"]+)"', panel).group(1)

    assert action.startswith(f"/songs/{keys[0]}/fix?"), action
    assert "artist=ARTIST" in action and "q=Song" in action, action
    assert "hx-include" not in panel, "the filters are in the body too"


async def test_the_last_song_of_a_listing_still_has_neighbours(tmp_path):
    """Nothing comes after it, and "only what is ahead" then left the
    panel empty for no reason a reader could see. Behind is better than
    nothing: a song you have passed can still be lined up."""

    keys = _line(tmp_path, count=6)

    async with _client(tmp_path) as client:
        listing = (await client.get("/fragments/list")).text
        last = re.findall(r'data-song-key="(\w+)"', listing)[-1]
        panel = (await client.get(f"/fragments/inspector/{last}")).text

    assert len(_offered(panel)) == 5, _offered(panel)
    assert "Nothing else" not in panel


def test_the_whole_neighbour_row_lines_a_song_up():
    """The same rule the listing follows: a click anywhere on a row acts
    on that row. The button is where the two states are said, not the
    only place they can be reached — and both go through one function,
    so they cannot come to disagree about what a click does."""

    source = Path("src/pypl2mp3/web/static/console.js").read_text()

    assert source.count("function lineUpOrTakeOut(") == 1
    # Twice: once from the button, once from the row around it.
    assert source.count("lineUpOrTakeOut(") == 3, (
        "the button and the row do not both go through it"
    )

    row = re.search(
        r'closest\("#neighbours \.neighbour:not\(\.is-next\)"\);\n(.*?)\n    \}',
        source, re.S,
    )
    assert row, "a click on the row itself does nothing"

    # And the row already next is left out: it is where the walk was
    # going anyway, so there is nothing for a click to ask for.
    assert ":not(.is-next)" in source
    assert 'closest("button, a")' in row.group(1), (
        "the button inside the row would fire twice, or the link would "
        "be swallowed"
    )


async def test_the_neighbour_name_recedes_and_the_row_answers_the_pointer(
    tmp_path
):
    """Five names read at a glance, not word by word, so they are quieter
    than the body text — and the row says it can be clicked before it is.
    """

    _line(tmp_path, count=6)

    async with _client(tmp_path) as client:
        css = (await client.get("/static/console.css")).text

    name = re.search(r"\n\.neighbour-name \{([^}]*)\}", css)
    assert name and "var(--text-green)" in name.group(1), name

    # Defined in both themes, or the dark one falls back to nothing.
    assert css.count("--accent-dim:") == 2, "one theme has no value for it"

    assert re.search(r"\n\.neighbour:hover \{[^}]*var\(--hover\)", css), (
        "the row does not tint under the pointer"
    )
    assert re.search(r"\n\.neighbour \{[^}]*cursor: pointer", css), (
        "the row does not say it can be clicked"
    )


async def test_the_save_button_is_not_offered_from_the_neighbours(tmp_path):
    """There is nothing to save from that face, and a disabled button is
    an offer withdrawn rather than an offer not made. A word stands in
    its place — in the same cell, so the row is as wide as the wider of
    the two and the filename beside it holds its place when the face
    changes. Measured in a browser: 88px of cell and the filename at the
    same x, both ways.
    """

    keys = _line(tmp_path, count=6)

    async with _client(tmp_path) as client:
        panel = (await client.get(f"/fragments/inspector/{keys[0]}")).text
        css = (await client.get("/static/console.css")).text

    cell = re.search(
        r'<span class="inspector-save">(.*?)</span>\s*</span>', panel, re.S
    )
    assert cell, "the button and its stand-in no longer share a container"
    assert 'type="submit"' in cell.group(1)
    # The arrow the player's preview uses, pointing at what it names —
    # and in its own element, because it sits in the space between
    # rather than tight against the word.
    assert "MP3 file" in cell.group(1)
    assert 'class="save-arrow"' in cell.group(1)
    assert "→" in cell.group(1)

    assert ".inspector-save > * { grid-area: 1 / 1; }" in css, (
        "the two no longer stack, so the filename will move"
    )
    for selector in (
        r"#inspector-body:not\(\.showing-edit\) \.inspector-save button",
        r"#inspector-body\.showing-edit \.save-label",
    ):
        rule = re.search(selector + r" \{([^}]*)\}", css, re.S)
        assert rule, f"{selector} is gone"
        assert "visibility: hidden" in rule.group(1), selector


async def test_the_next_mark_is_the_size_of_the_buttons_beside_it(tmp_path):
    """"Next" is a shorter word than "Play next", so a mark sized to its
    own text would make the column jog from row to row. Both fill the
    column instead. Measured in a browser: 72px by 17px each, right
    edges to the pixel.

    Filled rather than outlined, and not a button at all: nothing is
    being withheld there, only stated. Which is also why that row is the
    one row a click does not act on — it is where the walk was going
    anyway.
    """

    _line(tmp_path, count=8)

    async with _client(tmp_path) as client:
        css = (await client.get("/static/console.css")).text

    both = re.search(
        r"\.neighbour-do button,\n\.neighbour-do \.up-next \{([^}]*)\}", css
    )
    assert both, "the mark and the buttons no longer share a size"
    assert "width: 100%" in both.group(1), both.group(1)

    mark = re.search(r"\n\.neighbour \.up-next \{([^}]*)\}", css)
    assert mark and "background: var(--accent)" in mark.group(1), mark

    quiet = re.search(
        r"\n\.neighbour\.is-next, \.neighbour\.is-next:hover \{([^}]*)\}", css
    )
    assert quiet and "cursor: default" in quiet.group(1), quiet


def test_the_map_is_drawn_on_a_plain_2d_canvas():
    """Every browser has a 2D context; a WebGL one is a privilege. A
    point cloud asks a renderer for very little — a rotation, a
    projection, a depth order and a shaded circle each — so it does not
    need the privilege.

    It is also the only rendering path anyone here can check: the
    browser these are driven in has its GPU process switched off, which
    is the fault the map was reported with, and the WebGL version was
    never once watched running. It went, and with it 760 KB of
    three.js.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    assert "drawn = build(said);" in source
    assert "getContext(\"2d\")" in source, "the cloud is not drawn on a 2D canvas"

    # Past the header, which says in prose why three.js went — the
    # code is what must not reach for it. The library, not the word:
    # banning "three" outright failed on a comment counting periods,
    # which is a test governing prose rather than behaviour.
    code = source[source.index("*/") + 2:]
    for gone in ('"three', "three.module", "three-orbit",
                 "webglrenderer", "import "):
        assert gone not in code.lower(), f"{gone} is still in the map"

    page = Path("src/pypl2mp3/web/templates/console.html").read_text()
    assert "importmap" not in page, "the page still names modules nothing imports"

    flat = source[source.index("function build("):]
    flat = flat[:flat.index("\nfunction showLegend(")]

    # One place asks for frames, and it re-arms only when something
    # moved. Every frame is rasterised by the processor on the machine
    # this was written for, so the accounting has to be exact.
    assert flat.count("requestAnimationFrame") == 1, (
        "more than one place asks for frames, so one of them is a loop"
    )
    assert "if (easing || gone) return;" in flat, (
        "frames can be asked for twice over, which is two loops"
    )
    assert re.search(
        r"if \(moved\) \{\n\s*redraw\(\);\n\s*keepEasing\(\);", flat
    ), "the loop re-arms whether or not anything moved"

    # Far to near, which is the whole of what a depth buffer did.
    assert "b.depth - a.depth" in flat, "the points are not depth-sorted"

    # The mark is a card facing the reader: a rectangle in the
    # proportion a bank card has, corners just off square, one flat
    # colour. It was a shaded sphere and then a shaded cube on the way
    # here, and both were wrong for the same reason — the page they sit
    # on is flat, and the map already carries its own depth.
    assert "const CARD = 1.586;" in source
    assert "const ROUND = 0.11;" in source
    assert "function card(ink, x, y, wide, tall, round)" in source, (
        "the outline is not a shape the drawing can reuse"
    )
    # Nothing round is built where the mark is cut. The one radial
    # gradient in the drawing is the pool of accent the cloud sits in,
    # which is laid under everything and shades no object — scoping
    # this to block() rather than banning the call outright, because a
    # ban on the call fired on that background wash and would have been
    # loosened instead of sharpened.
    cut = source[source.index("function block(tint, fade)"):]
    cut = cut[:cut.index("\n  }")]
    assert "createRadialGradient" not in cut, (
        "the mark is being modelled as a solid again"
    )
    assert flat.count("createRadialGradient") == 1, (
        "a second radial gradient has appeared in the drawing"
    )

    # Area kept, so changing the shape did not quietly change how heavy
    # the cloud is: half the width times root of the ratio, half the
    # height divided by it.
    assert "const WIDER = Math.sqrt(CARD);" in source


def test_the_map_calls_nothing_it_does_not_own():
    """map.js is a module and console.js is not, so a name console.js
    holds is not a name map.js can call — and a name nobody holds is a
    ReferenceError the moment the tab opens, not when the file loads.

    Taking three.js out sliced `filters()` away with it. Every test
    passed; the map was dead in the first minute in a browser, which is
    what this now asks instead.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    code = re.sub(r"//[^\n]*", "", code)
    # "rgba(0, 0, 0, 0)" is a colour, not a call.
    code = re.sub(r'"(?:[^"\\]|\\.)*"', '""', code)
    code = re.sub(r"'(?:[^'\\]|\\.)*'", "''", code)

    called = set(re.findall(r"(?<![.\w$])([a-z][A-Za-z0-9_$]*)\s*\(", code))
    held = set(re.findall(r"function\s+([A-Za-z0-9_$]+)\s*\(", code))
    held |= set(re.findall(
        r"(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*=\s*function", code))

    # `if (`, `for (` and the rest read as calls to this and are not.
    grammar = {"if", "for", "while", "switch", "catch", "return",
               "typeof", "function"}
    # The ones the browser itself provides. Each was added on purpose,
    # which is the point of the list.
    browser = {"fetch", "getComputedStyle", "requestAnimationFrame",
               "parseFloat"}

    assert called - held - grammar - browser == set(), (
        "the map calls a name it does not define and the browser does not"
    )


def test_the_map_settles_rather_than_stopping_dead():
    """A wheel notch and a flick are gestures, not jumps. The zoom is a
    spring — it arrives about a tenth past where the wheel asked and
    comes back, which is the bounce — and a drag lets go of its spin
    rather than freezing where the fingers were.

    Simulated over ninety frames before it was written: k=0.22, d=0.62
    overshoots 11% and is settled by frame 19, a third of a second.
    Looser constants bounced twice as far and took half again as long.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    assert "const SPRING = 0.22;" in source
    assert "const DAMP = 0.62;" in source
    assert "zooming = (zooming + gap * SPRING) * DAMP;" in source, (
        "the zoom is not a spring, so it cannot overshoot and come back"
    )

    # The wheel moves the target, never the eye: moving both is how a
    # spring is given nothing to pull against.
    roll = source[source.index("function roll("):]
    roll = roll[:roll.index("\n  }")]
    assert "wantAway *=" in roll and "away *=" not in roll, roll

    # And the spin the pointer handed over runs down instead of being
    # dropped.
    assert "turning *= GLIDE;" in source
    assert "if (spun && !stillness.matches) keepEasing();" in source, (
        "a flick does not carry, or carries for somebody who asked for "
        "no animation"
    )


def test_the_cloud_turns_by_itself_and_stops_under_the_hand():
    """A still projection of a sphere does not say which islands are in
    front. A turn does, without anyone having to take hold of it — one
    revolution in 87 seconds, at a rate that does not vary. A rate that
    wandered was meant to read as less mechanical and read as a wobble.

    The axis drifts as well, and at its own constant rate: a radian
    either way, 29 degrees in half a minute, a full sweep in four
    minutes. It reverses at the ends rather than being clamped there,
    because a drag can leave the tilt outside the range and clamping
    would snap it back the moment the pointer left.

    The breath goes right inside the cloud: from the 2.4 radii that
    frame it down to 0.47, halfway to the middle, and back, over 81
    seconds. Probed through the module at the first, much smaller
    setting, the eye swung 1.71 to 2.44 radii — the 1.425 the arithmetic
    predicts, bounded, no drift — which is the same mechanism, only
    wider and no longer symmetrical.

    It is a frame a tick while it runs, so it runs only where somebody
    could be looking and is not already touching: measured in a browser,
    60 frames a second at rest, 0 with the pointer on the map, 0 on
    another tab, 60 again on coming back.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    assert "resting = onScreen && !pointerOn && !stillness.matches;" in source, (
        "the drift does not stop for the pointer, the tab, or somebody "
        "who asked for no animation"
    )
    assert "let moved = resting;\n    if (resting) drift();" in source, (
        "the drift is not what keeps the loop alive at rest"
    )

    assert "yaw += TURN;" in source, "the turn is not at a constant rate"
    assert "pitch += TIP * tilting;" in source, (
        "the axis is fixed, or drifts at a rate that varies"
    )
    assert re.search(
        r"if \(tilting > 0 \? pitch >= SWING : pitch <= -SWING\)"
        r" tilting = -tilting;", source
    ), "the tilt is turned round by something other than its own travel"

    # Clamping the tilt inside drift() is the bug this shape avoids: a
    # drag may leave it past SWING, and a clamp would jump it back.
    walk_for_clamp = source[source.index("function drift() {"):]
    walk_for_clamp = walk_for_clamp[:walk_for_clamp.index("\n  }")]
    assert "Math.max(-1.45" not in walk_for_clamp, walk_for_clamp
    assert "pitch = Math.max" not in walk_for_clamp, walk_for_clamp
    assert "const DIVE = 1.5;" in source and "const RISE = 0.12;" in source, (
        "the breath no longer reaches inside the sphere"
    )

    walk = source[source.index("function drift() {"):]
    walk = walk[:walk.index("\n  }")]

    # The breath is a factor of where the eye was left, not of where it
    # has got to: compounding a factor frame after frame is a drift, and
    # this one has to come back.
    assert "home * breath()" in walk, walk

    # And the place the wheel asked for comes along, so the spring sees
    # no gap and does not fight the breath every frame.
    assert "wantAway = away;" in walk, walk

    # Resuming takes its reference from the eye's own place, so it never
    # jumps — the wheel may have moved it while the drift was stopped.
    assert "if (resting && !was) home = away / breath();" in source

    # Off the tab, nobody is looking.
    assert "else if (drawn) drawn.showing(false);" in source


def test_distance_is_said_with_air_rather_than_with_gloss():
    """A map says how far away a thing is by making it smaller and
    paler, not by modelling a solid. Each colour is cut once per depth
    step, mixed towards the colour of the page behind the cloud — a
    mix, not a transparency, so the cards stay opaque and nothing shows
    through anything.

    The steps are read off the cloud's own near and far walls as the
    eye stands at that moment. The breath moves the eye by a factor of
    five, and a fixed scale would wash the whole picture out at the far
    end of it.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    assert "const STEPS = 8;" in source and "const HAZE = 0.5;" in source

    # Cut into the sprite, not laid over each card as it lands: a value
    # per point is a gradient per point per frame.
    cut = source[source.index("function block(tint, fade)"):]
    cut = cut[:cut.index("\n  }")]
    assert "ink.globalAlpha = fade;" in cut
    assert "ink.fillStyle = paper_colour;" in cut, cut

    # Off the eye's own distance, not an absolute one.
    assert "const nearest = Math.max(0.1, away - reach);" in source
    assert "const depth = Math.max(0.0001, (away + reach) - nearest);" in source

    # The sprites carry the page's colour inside them, so a theme change
    # has to rebuild them or the far side goes on fading towards a white
    # that is no longer there.
    assert "function retint()" in source
    assert 'attributeFilter: ["data-theme"]' in source


def test_two_cards_of_one_colour_say_which_is_in_front():
    """Drawn far to near, two cards of the same colour that overlap read
    as one odd shape. A slope of light across each one settles it: the
    near card's lit corner meets the far one's shaded end and the join
    shows by itself.

    A rule between them was tried twice and thrown away twice — in the
    page's colour it cut a white gash through every crowd, and in a
    darker shade of the card it drew a border round things that are not
    bordered anywhere else on this page. A slope draws nothing.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    assert "const SLOPE_UP = 0.14;" in source
    assert "const SLOPE_DOWN = 0.17;" in source

    # Two passes. One gradient from white to black interpolates through
    # a grey with alpha in the middle, which puts a smudge across the
    # centre of every card.
    cut = source[source.index("function block(tint, fade)"):]
    cut = cut[:cut.index("\n  }")]
    assert cut.count("createLinearGradient") == 2, cut

    # And nothing is drawn under the card any more.
    for gone in ("CASING", "DARKER", "edgesFor"):
        assert gone not in source, f"the rule is back as {gone}"


def test_the_cloud_leaves_the_frame_instead_of_being_cut_by_it():
    """A cloud that turns and breathes keeps pushing songs past the edge
    of the frame, and a card that meets it is simply cut in half — a
    straight line through a thing that has none. Four bands of the
    page's own colour, one a side, fade the last stretch instead.

    Laid over the whole cloud once rather than worked out card by card,
    and in the page's colour, so on open ground it does nothing and
    nothing has to be made translucent to get it.

    Measured in a browser: on the three outermost columns of the frame,
    0.4% of pixels differ from the page's colour, against 83.7% in a
    band across the middle.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    assert "const FEATHER = 0.14;" in source
    assert "function weave()" in source
    for side in ("top", "bottom", "left", "right"):
        assert side + ": band(" in source, f"the {side} edge is not feathered"

    # And the pointer does not find a song the veil has taken: clicking
    # apparently empty ground would otherwise start something invisible.
    assert "if (veiled(px, py) > 0.75) continue;" in source


def test_the_name_of_a_song_is_drawn_on_the_map_and_not_under_it():
    """The readout used to be a line of text below the frame, which
    reserved a line of the page whether or not anything was under the
    pointer. The name is drawn on the canvas now, beside the card it
    belongs to and level with its middle — a caption attached to the
    thing, the way a place name sits beside its dot.

    `#map-hover` stays as the spoken version of the same thing. A canvas
    says nothing to a screen reader, so taking the element out would
    have left the map with no accessible readout at all; it is hidden
    rather than removed.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()
    css = Path("src/pypl2mp3/web/static/console.css").read_text()
    page = Path("src/pypl2mp3/web/templates/console.html").read_text()

    assert 'paper.textAlign = "left";' in source
    assert 'paper.textBaseline = "middle";' in source
    assert "const BESIDE = 5;" in source

    # A line of text in a card's colour over a crowd of cards is
    # unreadable on its own. The page's colour behind it, as a fat
    # stroke under the letters, is what a map does with a place name
    # over a forest.
    assert "paper.strokeStyle = paper_colour;" in source
    assert "paper.strokeText(name, atX, atY);" in source

    assert '<p id="map-hover" aria-live="polite">' in page, (
        "the map has no accessible readout left"
    )
    hidden = re.search(r"\n#map-hover \{([^}]*)\}", css)
    assert hidden and "clip-path: inset(50%)" in hidden.group(1), hidden
    assert "min-height" not in hidden.group(1), (
        "it is still holding a line of the page open"
    )


def test_the_map_names_a_few_songs_while_it_turns():
    """A map nobody is touching is nine hundred anonymous marks, and the
    one thing a reader wants of it — what is this? — needs a hand on the
    mouse to ask. One name a second, each staying three, so three are up
    at any moment and each is a second older than the last. A set of
    three arriving and leaving together read as a slideshow.

    Each card wears the same ring the pointer makes while its name is
    up: at this size a card is a few pixels, and a name hanging over a
    field of them says nothing about which.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    assert "const EVERY = 60;" in source
    assert "const LIFE = 180;" in source
    assert "const NAMES = 3;" in source

    walk = source[source.index("if (!resting) {"):]
    walk = walk[:walk.index("\n    for (let i = 0; i < order.length")]

    # Each on its own age, so the one going and the one coming overlap
    # instead of blinking.
    assert "named.push({ at: seen.at, x: px, y: py, born: clock });" in walk
    assert "return clock - one.born < LIFE;" in walk

    assert "paper.strokeStyle = seen.tint;" in source, "named cards wear no ring"


def test_a_song_is_not_named_twice_within_the_minute():
    """The walk starts from the front of the cloud, and the front of a
    cloud turning this slowly is much the same from one second to the
    next — so the same few songs were named over and over.

    With a memory the walk goes a little deeper to find the next one.
    Measured in a browser over 110 seconds: 118 names, 105 distinct, and
    the closest a song came to being named twice was 77 apart, against a
    floor of 60.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    assert "const AGAIN = 3600;" in source
    assert "const when = told.get(seen.at);" in source
    assert "if (when !== undefined && clock - when < AGAIN) continue;" in source
    assert "told.set(seen.at, clock);" in source


def test_a_song_is_only_named_when_its_card_is_big_enough_to_point_at():
    """Not a zoom level, though that is what it amounts to: what stops a
    name being attachable is that the thing it points at is a speck.

    Measured through the module, the widest card in the cloud comes to
    1.2 pixels at the far end of the wheel, 3.0 at four radii, 7.5 at
    the distance the map opens on, and 36 from inside. Sampled over a
    whole breath at the opening framing it runs 5.7 to 36.3, and a
    threshold of eight leaves names being chosen 77% of that cycle
    against 100% at five — measured on screen afterwards, names are up
    90% of the time, because one already chosen lives out its three
    seconds.

    It gates the choosing only, so a name already up does not blink off
    the moment the wheel turns.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    assert "const NAMEABLE = 8;" in source
    assert "if (2 * big * FILL * WIDER < NAMEABLE * grain) continue;" in source

    # In the choosing, not in the drawing. Anchored on a line only the
    # drawing has: `named.forEach(` also opens the one-liner in weave()
    # that clears the cut names, and slicing from there took seven
    # thousand characters of unrelated code with it — this assertion
    # passed with the gate moved straight into the drawing.
    drawing = source[source.index("const seen = flat[one.at];"):]
    drawing = drawing[:drawing.index("\n      });")]
    assert "NAMEABLE" not in drawing, drawing


def test_a_name_is_cut_to_the_width_two_names_must_keep_apart():
    """Measured on the library, in the face the map draws in: the median
    name is 188 pixels wide, three quarters are under 263, and the
    longest — Franco Micalizzi's "Trinity: titoli (feat. …) [Remastered
    2022]" — runs to 698, two thirds of the frame.

    A quarter of the frame, so the limit follows the window rather than
    being right at one size. At the width this was written for that is
    250 pixels and it shortens about three names in ten.

    It is the same number as the gap two names must keep to be allowed
    on one line, and deliberately so: a limit and a spacing that did not
    agree would let two "separated" names overlap anyway.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    assert "longest = Math.max(120 * grain, wide / 4);" in source
    assert "return Math.abs(other.x - px) > longest" in source, (
        "the spacing is a number of its own again"
    )

    cut = source[source.index("function fits(name)"):]
    cut = cut[:cut.index("\n    }")]
    assert "paper.measureText(name).width <= longest" in cut
    assert 'return cut.replace(' in cut and '"…"' in cut, cut


def test_a_name_is_written_in_its_card_s_colour_pushed_off_the_page():
    """The ring says which card; the name says what it is. Both in the
    card's own colour, so they read as one object.

    Pushed far enough from the page to be read, and which way is decided
    by the page rather than by a flag — the theme is a fact about the
    colour behind the letters. Measured across the thirteen colours,
    worst case: untouched they come to 1.75:1 on white, which is no
    contrast at all; darkened to 55% they reach 5.28, and lightened by a
    quarter on the dark theme, 6.26. Both clear the 4.5 that small text
    is held to.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    assert "const DARKEN = 0.55;" in source
    assert "const LIGHTEN = 0.25;" in source

    ink = source[source.index("function inkFor(tint)"):]
    ink = ink[:ink.index("\n  }")]
    assert "rgbOf(paper_colour)" in ink, (
        "the direction is taken from something other than the page"
    )
    assert "0.2126 * page[0]" in ink, ink


def test_the_breath_comes_home_after_the_wheel_has_moved_it():
    """The breath is a factor, and `home` is what it is a factor of.
    Riding for ever on wherever the wheel was left was the first version
    and it was wrong: zoom in once, leave, and the breath stayed shrunk
    around that spot, its far end never coming back out far enough to
    show the cloud again. A wheel is a look at something, not a new
    home.

    Taken from the eye's own place when the drift restarts, so nothing
    jumps, and then drawn back. Measured through the module: after
    zooming right in, the anchor resumes at 0.975 radii and reads 1.568
    three seconds later, 1.939 at six, and 2.124 at sixteen — against a
    resting 2.129.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    assert "const HOMING = 0.006;" in source
    assert "const settled = away / Math.exp(RISE);" in source, (
        "the breath has no natural distance to come back to"
    )
    assert "home += (settled - home) * HOMING;" in source

    # And still no jump on the way in.
    assert "if (resting && !was) home = away / breath();" in source


def test_the_drift_repaints_once_when_it_stops():
    """Nothing asks for another frame once the drift is off, so the last
    one drawn stays on screen — names and all. Putting the pointer on
    the map without aiming at anything left three names frozen there for
    as long as it stayed.

    Measured in a browser: 643 pixels of lettering while drifting, 0 the
    moment the pointer arrives, 0 two seconds later, 860 once it leaves.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    settle = source[source.index("function settle() {"):]
    settle = settle[:settle.index("\n  }")]
    assert "} else if (was) {" in settle, settle
    assert "paint();" in settle, settle


def test_the_cloud_sits_in_a_pool_of_the_page_s_own_colour():
    """The page has one colour of its own and spends it on the thing in
    hand. A soft wash of it under the cloud says the map belongs to the
    same page, and gives the eye a centre to read the turning against —
    a cloud on bare white has no horizon.

    Under the cards and never over them, so it cannot dull a colour the
    legend promises. The accent comes from the stylesheet, so it turns
    with the theme like everything else here.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    assert "const POOL_IS = 0.17;" in source

    # Laid down straight after the canvas is cleared, before a single
    # card. Drawn after them it would be a veil over the cloud.
    opening = source[source.index("paper.clearRect(0, 0, wide, tall);"):]
    opening = opening[:opening.index("for (let i = 0; i < order.length")]
    assert "paper.fillStyle = wash;" in opening, opening

    assert '.getPropertyValue("--accent")' in source, (
        "the pool has a colour of its own instead of the page's"
    )


def test_the_pool_is_as_big_as_the_cloud_it_sits_behind():
    """Its reach is not a number anyone chose: the cloud is a ball of
    radius `reach`, so at a distance of `away` it projects to
    `reach * lens / away`, and the pool is that. Two earlier versions
    set it by hand — one fixed, one on a ramp — and neither could
    follow a cloud that breathes.

    Checked against what is actually drawn, by measuring the furthest
    card on the canvas: 34px against 31 at twelve radii, 72 against 68
    at 5.6, and 154 against 155 at 2.6 — within a tenth, and exact
    where the map opens. Nearer than about two radii the real cloud
    bursts the frame while the formula goes on describing the ball,
    which is the useful thing to be behind.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    assert "reach * lens / Math.max(away, 1e-6)" in source, (
        "the pool's reach is a number of its own again"
    )
    # Clamped, because coming inside sends the projection to infinity.
    assert "const POOL_LEAST = 0.1;" in source
    assert "const POOL_MOST = 1.2;" in source


def test_the_pool_fades_from_the_cloud_s_surface_inwards():
    """A pool marks the middle of a thing you are looking at. Once you
    are well inside there is no middle left to mark — the cards pass to
    either side, and a wash pinned to the centre of the frame would be
    saying something about the frame.

    Neither bound is chosen either. Full down to 1.0, which is the
    cloud's own surface, so the fade begins exactly where the eye goes
    inside; spent by 0.3, just short of the 0.25 the wheel stops at.

    It began at 0.8 and 1.6, which started dimming while the eye was
    still well outside and left the pool wholly dark for 38% of the
    breath. At 0.3 and 1.0 it is at full strength for 53% of the cycle
    and never goes out: at the deepest of the dive it still stands at a
    quarter.
    """

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    assert "const POOL_GONE = 0.3;" in source
    assert "const POOL_FULL = 1.0;" in source
    assert re.search(
        r"const pooling = Math\.max\(0, Math\.min\(\n\s*"
        r"1, \(away / reach - POOL_GONE\) / \(POOL_FULL - POOL_GONE\)",
        source
    ), "the fade is no longer read off the eye's distance in radii"

    # The strength is an alpha on the one fill, not baked into the
    # gradient: the gradient is cut fresh each frame for its reach.
    assert "paper.globalAlpha = pooling;" in source


def test_a_drag_across_the_map_does_not_play_what_it_stops_over():
    """`dragging` is moved to the pointer on every step so that the
    turning is incremental. Comparing the release against it measured
    the last pixel rather than the journey, so every drag ended in a
    click — measured in a browser: one song playing after a 130-pixel
    drag, none after the fix."""

    source = Path("src/pypl2mp3/web/static/map.js").read_text()

    assert "let began = null;" in source
    assert re.search(r"spun = began && \(", source), (
        "the drag is judged against where it got to, not where it began"
    )
    assert "if (spun || over < 0) return;" in source
