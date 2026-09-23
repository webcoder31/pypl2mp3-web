"""Where each song sits, once the forty numbers become three.

Driven on vectors written by hand: what this module gets right or wrong
is a relaxation, and every wrong version of one is a source file that
reads perfectly well.
"""

import numpy as np
import pytest

from pypl2mp3.libs.features import FEATURE_COUNT, TIMBRE
from pypl2mp3.services.similarity import Space
from pypl2mp3.services.song_map import layout


def _vector(timbre: float) -> list[float]:
    out = [0.0] * FEATURE_COUNT
    for dim in range(TIMBRE.start, TIMBRE.stop):
        out[dim] = timbre
    return out


def _two_clumps(count: int = 24):
    """Two tight groups, far apart. If a layout cannot separate this it
    cannot separate anything.

    Twenty-four and not twelve: each song is held by its nearest EDGES,
    which is eight — so with six to a group every song is also joined to
    songs in the other one, and the graph knows nothing of the split it
    is being asked to show.
    """

    entries = []
    for at in range(count):
        near = 0.0 if at < count // 2 else 40.0
        entries.append((f"s{at}", f"v{at}", _vector(near + at * 0.01)))

    return entries


def test_the_same_corpus_gives_the_same_cloud():
    """A map that moves when nothing has changed cannot be trusted to
    mean anything when something has. No random seed anywhere, and a
    fixed number of rounds rather than a tolerance."""

    entries = _two_clumps()
    space = Space.build(entries)
    keys = [key for key, _, _ in entries]

    first = layout(space, keys)
    second = layout(space, keys)

    for key in keys:
        assert first[key] == second[key], key


def test_songs_that_sound_alike_end_up_near_each_other():
    """The whole point. Position comes from the sound, so two groups
    that sound nothing like each other must not overlap."""

    entries = _two_clumps()
    space = Space.build(entries)
    keys = [key for key, _, _ in entries]

    places = layout(space, keys)
    half = len(keys) // 2
    here = np.array([places[k] for k in keys[:half]])
    there = np.array([places[k] for k in keys[half:]])

    inside = max(
        np.linalg.norm(here - here.mean(axis=0), axis=1).max(),
        np.linalg.norm(there - there.mean(axis=0), axis=1).max(),
    )
    apart = np.linalg.norm(here.mean(axis=0) - there.mean(axis=0))

    assert apart > inside * 2, (
        f"the two groups are {apart:.2f} apart and {inside:.2f} wide"
    )


def test_the_cloud_has_three_dimensions_and_not_two():
    """Lifting a flat layout by a hash gives a picture that is
    technically three-dimensional and reads as a flat map with jitter,
    because the structure is still entirely in two of the axes."""

    entries = _two_clumps(36)
    space = Space.build(entries)
    keys = [key for key, _, _ in entries]

    places = np.array([layout(space, keys)[k] for k in keys])
    spread = places.std(axis=0)

    assert spread.min() > spread.max() * 0.15, (
        f"one axis carries almost nothing: {spread}"
    )


def test_a_song_with_no_vector_sits_on_a_shell_around_the_cloud():
    """Nothing can occlude the outermost layer of a scene, so they stay
    countable from every angle — and their place says the right thing:
    matter not joined to anything, on the periphery."""

    entries = _two_clumps()
    space = Space.build(entries)
    keys = [key for key, _, _ in entries] + ["nobody", "nothing"]

    places = layout(space, keys)

    assert set(places) == set(keys)

    known = np.array([places[k] for k, _, _ in entries])
    middle = known.mean(axis=0)
    furthest = np.linalg.norm(known - middle, axis=1).max()

    for orphan in ("nobody", "nothing"):
        out = np.linalg.norm(np.array(places[orphan]) - middle)
        assert out > furthest, f"{orphan} is inside the cloud"

    # And on a shell, so one is not hidden behind another.
    radii = [np.linalg.norm(np.array(places[k]) - middle)
             for k in ("nobody", "nothing")]
    assert radii[0] == pytest.approx(radii[1], rel=0.01)


def test_the_orphans_are_spread_rather_than_stacked():
    """A Fibonacci distribution, so ten of them are ten points and not
    one point drawn ten times."""

    space = Space.build(_two_clumps())
    keys = [f"s{at}" for at in range(24)] + [f"gone{at}" for at in range(10)]

    places = layout(space, keys)
    out = np.array([places[f"gone{at}"] for at in range(10)])

    assert len(np.unique(out.round(4), axis=0)) == 10


def test_a_map_of_nothing_is_nothing():
    assert layout(Space.build([]), []) == {}


def test_a_map_of_one_song_does_not_divide_by_zero():
    entries = [("alone", "v1", _vector(1.0))]

    places = layout(Space.build(entries), ["alone"])

    assert np.isfinite(places["alone"]).all()


def test_the_relaxation_is_what_places_them():
    """Not the hash they start from. Before any round the cloud is
    scattered by a digest and means nothing; the whole value of this
    module is in what the rounds do to that.

    Measured over the real library by how often a song's neighbours on
    the map are by the same artist: 1.2x chance at zero rounds, 6.5x at
    a hundred and fifty. Here the same question is asked of two clumps
    that must end up apart.
    """

    entries = _two_clumps(24)
    space = Space.build(entries)
    keys = [key for key, _, _ in entries]

    def parted(rounds):
        places = layout(space, keys, rounds=rounds)
        half = len(keys) // 2
        here = np.array([places[k] for k in keys[:half]])
        there = np.array([places[k] for k in keys[half:]])
        wide = max(
            np.linalg.norm(here - here.mean(axis=0), axis=1).max(),
            np.linalg.norm(there - there.mean(axis=0), axis=1).max(),
        )
        return np.linalg.norm(here.mean(axis=0) - there.mean(axis=0)) / wide

    assert parted(1) < 1.5, "the hash alone already separates them"
    assert parted(150) > 2.0, "the rounds do not separate them"
