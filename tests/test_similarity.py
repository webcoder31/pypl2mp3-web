"""Distances between songs, driven on vectors written by hand.

No audio here at all. What this module gets right or wrong is the
arithmetic of comparing forty numbers, and the extractor's own tests
already say the forty numbers mean something.
"""

import numpy as np
import pytest

from pypl2mp3.libs.features import (
    COLOUR,
    DYNAMICS,
    FEATURE_COUNT,
    RHYTHM,
    TIMBRE,
)
from pypl2mp3.services.similarity import Space, WEIGHTS, standardise

_BLOCKS = {"timbre": TIMBRE, "rhythm": RHYTHM,
           "colour": COLOUR, "dynamics": DYNAMICS}


def _vector(**facets) -> list[float]:
    """A vector that is zero everywhere except where you say."""

    out = np.zeros(FEATURE_COUNT, dtype=np.float32)
    for name, value in facets.items():
        out[_BLOCKS[name]] = value

    return [float(v) for v in out]


def test_a_column_that_never_moves_does_not_divide_by_zero():
    """Every song in a selection can share a value — one playlist, one
    producer, one loudness war. A spread of zero must leave the column
    flat, not infinite."""

    vectors = np.ones((5, FEATURE_COUNT), dtype=np.float32)

    out = standardise(vectors)

    assert np.isfinite(out).all()
    assert np.abs(out).max() == pytest.approx(0.0)


def test_the_facet_with_more_dimensions_does_not_win_by_counting():
    """26 timbre dimensions against 3 dynamics ones. A raw euclidean
    distance would hand the timbre two thirds of the vote for no musical
    reason at all — which is the whole argument for the facet detour."""

    space = Space.build([
        ("me",      "v1", _vector(timbre=0.0, dynamics=0.0)),
        ("timbre",  "v2", _vector(timbre=1.0, dynamics=0.0)),
        ("dynamic", "v3", _vector(timbre=0.0, dynamics=1.0)),
    ])

    found = {n.key: n.distance for n in space.neighbours("me", count=2)}

    # The same per-facet gap, so the ratio must be the ratio of the
    # weights and nothing else.
    assert found["timbre"] / found["dynamic"] == pytest.approx(
        WEIGHTS["timbre"] / WEIGHTS["dynamics"], rel=0.05
    )


def test_a_song_is_never_its_own_neighbour():
    space = Space.build([
        ("a", "v1", _vector(timbre=0.0)),
        ("b", "v2", _vector(timbre=1.0)),
    ])

    assert [n.key for n in space.neighbours("a")] == ["b"]


def test_the_same_recording_in_two_playlists_is_never_a_neighbour():
    """Eight songs here sit in two playlists: two keys, one audio, a
    distance of zero. Without this rule each would be its own eternal
    neighbour number one and the radio would play it twice in a row."""

    space = Space.build([
        ("in-alpha", "same", _vector(timbre=0.0)),
        ("in-beta",  "same", _vector(timbre=0.0)),
        ("other",    "v9",   _vector(timbre=5.0)),
    ])

    assert [n.key for n in space.neighbours("in-alpha")] == ["other"]


def test_neighbours_come_only_from_the_set_you_asked_for():
    """The radio may only offer what it could actually play, and what it
    could play is what the listing holds."""

    space = Space.build([
        ("a", "v1", _vector(timbre=0.0)),
        ("b", "v2", _vector(timbre=0.1)),
        ("c", "v3", _vector(timbre=9.0)),
    ])

    found = space.neighbours("a", count=5, among={"a", "c"})

    assert [n.key for n in found] == ["c"]


def test_the_nearest_comes_first():
    space = Space.build([
        ("a",    "v1", _vector(timbre=0.0)),
        ("far",  "v2", _vector(timbre=9.0)),
        ("near", "v3", _vector(timbre=0.5)),
    ])

    assert [n.key for n in space.neighbours("a")] == ["near", "far"]


def test_a_neighbour_says_which_facet_brings_it_close():
    """The explanation is not a second computation: it is the four
    numbers the distance was made of."""

    space = Space.build([
        ("a", "v1", _vector(rhythm=0.0, timbre=0.0)),
        ("b", "v2", _vector(rhythm=0.0, timbre=4.0)),
        ("c", "v3", _vector(rhythm=4.0, timbre=4.0)),
    ])

    assert space.neighbours("a", count=1)[0].facet == "rhythm"


def test_the_percentile_says_how_close_that_is_for_this_library():
    """A distance has no meaning on its own. Its rank among every pair
    in the selection does, and it is the same number whatever units the
    features happen to be in."""

    entries = [(f"s{i}", f"v{i}", _vector(timbre=float(i))) for i in range(10)]
    space = Space.build(entries)

    nearest = space.neighbours("s0", count=1)[0]

    assert 0.0 <= nearest.percentile <= 100.0
    assert nearest.percentile > 80.0


def test_the_furthest_pair_is_at_the_bottom_of_the_scale():
    """The other end of the same claim, so the scale is anchored twice
    rather than only where it flatters."""

    entries = [(f"s{i}", f"v{i}", _vector(timbre=float(i))) for i in range(10)]
    space = Space.build(entries)

    furthest = space.neighbours("s0", count=9)[-1]

    assert furthest.key == "s9"
    assert furthest.percentile < 20.0


def test_a_space_with_one_song_has_no_neighbours():
    space = Space.build([("alone", "v1", _vector(timbre=1.0))])

    assert space.neighbours("alone") == []


def test_a_key_nobody_knows_has_no_neighbours():
    space = Space.build([("a", "v1", _vector(timbre=1.0))])

    assert space.neighbours("ghost") == []


def test_an_empty_space_is_not_a_crash():
    """A junk-only filter over a library nobody has analysed yet."""

    assert Space.build([]).neighbours("anything") == []


def test_a_vector_of_the_wrong_width_is_refused():
    """Better here than as a shape error thirty lines into a matrix
    multiplication."""

    with pytest.raises(ValueError):
        Space.build([("a", "v1", [0.0] * (FEATURE_COUNT - 1))])


def test_the_chain_goes_from_each_song_to_its_nearest_unvisited():
    """The property the whole radio rests on: the row after any song is
    that song's nearest neighbour among those not yet passed. True by
    construction, which is why nothing has to decide it when a track
    ends."""

    from pypl2mp3.services.similarity import chain

    # On a line, so the nearest unvisited is always the next one along.
    entries = [(f"s{i}", f"v{i}", _vector(timbre=float(i))) for i in range(6)]
    space = Space.build(entries)

    order = chain(space, [k for k, _, _ in entries], "s3")

    assert order[0] == "s3"

    # Each step is the closest song not yet passed — worked out here
    # from the positions rather than asked of the same code under test.
    # On a line that means the nearest unused index, which is a leap
    # back to the other end once the walk reaches one of them: greedy is
    # not a shortest path, and the first version of this test wrongly
    # demanded that it were.
    seen = {3}
    for before, after in zip(order, order[1:]):
        at = int(before[1:])
        expected = min(
            (i for i in range(6) if i not in seen),
            key=lambda i: (abs(i - at), i),
        )
        assert int(after[1:]) == expected, (
            f"from s{at}, the nearest unpassed is s{expected}, not {after}"
        )
        seen.add(int(after[1:]))


def test_the_chain_visits_every_song_once():
    """It is an ordering of the selection, not a walk that can revisit —
    a song heard twice in one run of the radio is a bug that looks like
    a coincidence."""

    from pypl2mp3.services.similarity import chain

    entries = [(f"s{i}", f"v{i}", _vector(timbre=float(i % 4))) for i in range(9)]
    space = Space.build(entries)

    order = chain(space, [k for k, _, _ in entries], "s0")

    assert len(order) == 9
    assert len(set(order)) == 9


def test_a_song_with_no_vector_goes_to_the_end():
    """Exactly where a song its playlist has dropped goes, and for the
    same reason: it has no place in the order the others are in."""

    from pypl2mp3.services.similarity import chain

    entries = [(f"s{i}", f"v{i}", _vector(timbre=float(i))) for i in range(3)]
    space = Space.build(entries)

    order = chain(space, ["s0", "nothing", "s1", "nobody", "s2"], "s0")

    assert order[:3] == ["s0", "s1", "s2"]
    # And in the order they came in, rather than shuffled by absence.
    assert order[3:] == ["nothing", "nobody"]


def test_a_chain_from_a_song_nobody_knows_still_orders_everything():
    """The radio is chosen while nothing is playing, or while the
    playing song has just been filtered out of the listing."""

    from pypl2mp3.services.similarity import chain

    entries = [(f"s{i}", f"v{i}", _vector(timbre=float(i))) for i in range(4)]
    space = Space.build(entries)

    order = chain(space, [k for k, _, _ in entries], "ghost")

    assert len(order) == 4
    assert order[0] == "s0", "it should fall back to the first of the selection"


def test_the_chain_of_nothing_is_nothing():
    from pypl2mp3.services.similarity import chain

    assert chain(Space.build([]), [], "anything") == []


def test_the_chain_keeps_a_duplicate_out_of_its_own_way():
    """Two keys, one recording. The chain must still visit both — they
    are two rows — but never step straight from one to the other, which
    would play the same audio twice running."""

    from pypl2mp3.services.similarity import chain

    entries = [
        ("a", "same", _vector(timbre=0.0)),
        ("b", "same", _vector(timbre=0.0)),
        ("c", "v3", _vector(timbre=1.0)),
    ]
    space = Space.build(entries)

    order = chain(space, ["a", "b", "c"], "a")

    assert sorted(order) == ["a", "b", "c"]
    assert order[1] != "b", "the same recording plays twice running"


def test_the_table_names_each_song_s_nearest_few():
    """For the browser: steering the radio replans the walk from where
    you steered it, and doing that over the wire would cost the Play
    next animation a full swap of the listing."""

    from pypl2mp3.services.similarity import Space

    entries = [(f"s{i}", f"v{i}", _vector(timbre=float(i))) for i in range(6)]
    space = Space.build(entries)

    table = space.table(count=2)

    assert table["keys"] == [f"s{i}" for i in range(6)]
    assert len(table["near"]) == 6
    # On a line, the two nearest of s3 are s2 and s4, in either order.
    assert sorted(table["keys"][at] for at in table["near"][3]) == ["s2", "s4"]
    # And nobody is their own neighbour.
    for at, kept in enumerate(table["near"]):
        assert at not in kept


def test_the_table_keeps_a_duplicate_out_of_it():
    """The same rule the neighbours obey, and for the same reason: two
    keys over one recording would otherwise be each other's first
    suggestion for ever."""

    from pypl2mp3.services.similarity import Space

    space = Space.build([
        ("a", "same", _vector(timbre=0.0)),
        ("b", "same", _vector(timbre=0.0)),
        ("c", "v3", _vector(timbre=1.0)),
    ])

    table = space.table(count=3)
    first = table["near"][table["keys"].index("a")]

    assert table["keys"].index("b") not in first


def test_the_table_of_nothing_is_nothing():
    from pypl2mp3.services.similarity import Space

    assert Space.build([]).table() == {"keys": [], "near": []}
