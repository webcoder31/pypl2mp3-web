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
