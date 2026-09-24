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


async def test_the_radio_without_a_starting_song_starts_at_the_top(tmp_path):
    """Choosing the radio while nothing plays is the ordinary case: the
    icon is there before the music is."""

    _line(tmp_path)

    async with _client(tmp_path) as client:
        page = (await client.get("/fragments/list?order=radio")).text

    assert _ids(page)[0] == "00000000000"


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
