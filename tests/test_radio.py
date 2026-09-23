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
        panel = (await client.get(f"/fragments/neighbours/{keys[0]}")).text

    found = _ids(panel)

    assert len(found) == 5
    assert found[0] == "00000000001", found


async def test_the_panel_says_how_close_and_along_which_axis(tmp_path):
    """The percentile is a rank among every pair in the selection, and
    the facet is the smallest of the four the distance was made of —
    both already computed, neither invented for the display."""

    keys = _line(tmp_path, count=8)

    async with _client(tmp_path) as client:
        panel = (await client.get(f"/fragments/neighbours/{keys[0]}")).text

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
            f"/fragments/neighbours/{mine}?artist=AAA+ELSE"
        )).text

    assert _ids(panel) == ["00000000009"], panel


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
            f"/fragments/neighbours/{song_key(PLAYLIST_ID, '00000000009')}"
        )).text

    assert _ids(panel) == []
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
            f"/fragments/neighbours/{keys[3]}?order=radio&start={keys[3]}"
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
