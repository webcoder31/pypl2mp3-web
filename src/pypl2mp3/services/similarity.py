#!/usr/bin/env python3
"""
PYPL2MP3: YouTube playlist MP3 converter and player,
with Shazam song identification and tagging capabilities.

How close two songs are, and along which axis.

Distances are computed per facet before they are combined. 26 of the 40
dimensions describe the timbre and 3 the dynamics, so a plain euclidean
distance would hand the timbre two thirds of the vote by counting rather
than by musical argument. Reducing each facet to one number first makes
the weights below mean what they say.

The detour pays twice: those four numbers are also the explanation. That
a neighbour is close "by rhythm" is not a commentary added afterwards,
it is the smallest of the four.

Nothing here is stored. The standardization belongs to a selection, and
a selection changes with every filter.

Copyright 2024 © Thierry Thiers <webcoder31@gmail.com>
License: CeCILL-C (http://www.cecill.info)
Repository: https://github.com/webcoder31/pypl2mp3
"""

# Python core modules
from dataclasses import dataclass

# Third-party packages
import numpy as np

# Local packages
from pypl2mp3.libs.features import (
    COLOUR,
    DYNAMICS,
    FEATURE_COUNT,
    RHYTHM,
    TIMBRE,
)


FACETS = {
    "timbre": TIMBRE,
    "rhythm": RHYTHM,
    "colour": COLOUR,
    "dynamics": DYNAMICS,
}

# The timbre leads because "it sounds the same" means the timbre first,
# and because it is where the signal is: measured on all 944 songs
# against the artist ruler, the timbre alone finds another song by the
# same artist 14.3 times better than chance, where the rhythm manages
# 5.7, the colour 5.6 and the dynamics 3.8.
#
# Held back from going further on purpose. The artist ruler structurally
# flatters the timbre — the same artist is the same voice, very nearly
# by definition — so following it to its conclusion would give a switch
# marked "timbre" and three that do nothing. The other three are kept at
# a weight the measurement does not ask for, because a radio that
# follows only the timbre is a radio with one tempo.
#
# 16.5x against the artist, where equal weights give 13.3 and this
# was 15.5 at .45. Checked with `scripts/measure_similarity.py`.
WEIGHTS = {
    "timbre": 0.60,
    "colour": 0.15,
    "rhythm": 0.15,
    "dynamics": 0.10,
}


@dataclass(frozen=True)
class Neighbour:
    """One song's proximity to another, and what makes it so."""

    key: str
    distance: float
    percentile: float
    facet: str


def standardise(vectors: np.ndarray) -> np.ndarray:
    """Centre each column on its median and scale it by its spread.

    Median and interquartile range rather than mean and deviation: one
    outlier — a five-second track, a silent file — would otherwise set
    the scale for the whole library.

    Args:
        vectors: (songs, FEATURE_COUNT).

    Returns:
        The same shape, standardized down each column.
    """

    low, middle, high = np.percentile(vectors, [25, 50, 75], axis=0)
    spread = high - low

    # A column every song shares carries no information, and dividing by
    # its spread would turn that nothing into an infinity.
    spread[spread < 1e-9] = 1.0

    return (vectors - middle) / spread


def facet_distances(vectors: np.ndarray) -> dict[str, np.ndarray]:
    """One full distance matrix per facet.

    Args:
        vectors: (songs, FEATURE_COUNT), already standardized.

    Returns:
        A (songs, songs) matrix for each facet name.
    """

    out = {}

    for name, block in FACETS.items():
        part = vectors[:, block]

        # The expansion of (a - b)² so the whole matrix is three matrix
        # operations rather than a Python loop over 890 000 pairs.
        square = (part ** 2).sum(axis=1)
        spread = square[:, None] + square[None, :] - 2 * (part @ part.T)

        # Divided by the facet's width so the four numbers are
        # comparable: this is a distance per dimension, not a total.
        out[name] = np.sqrt(np.clip(spread, 0, None) / part.shape[1])

    return out


class Space:
    """A selection of songs, and the distances between them."""

    def __init__(self, keys, videos, totals, facets, pairs, typical=None):
        self._keys = keys
        self._videos = videos
        self._at = {key: at for at, key in enumerate(keys)}
        self._totals = totals
        self._facets = facets
        self._pairs = pairs
        self._typical = np.zeros(0) if typical is None else typical

    @classmethod
    def build(cls, entries) -> "Space":
        """Compute every distance in a selection.

        Args:
            entries: (key, youtube_id, vector) for each song that has
                one. Songs without a vector are simply absent, which is
                what gives them no neighbours and sends them to the end
                of a course.

        Returns:
            A Space. 944 songs cost 120 ms to build — four full distance
            matrices and a sort of 445 000 pairs — and 0.1 ms to ask a
            neighbourhood of, both measured.

        Raises:
            ValueError: if a vector is not FEATURE_COUNT numbers wide.
        """

        keys = [key for key, _, _ in entries]
        videos = [video for _, video, _ in entries]

        if not keys:
            return cls([], [], np.zeros((0, 0)), {}, np.zeros(0),
                       np.zeros(0))

        raw = np.array([vector for _, _, vector in entries], dtype=np.float64)
        if raw.shape[1] != FEATURE_COUNT:
            raise ValueError(
                f"a vector is {FEATURE_COUNT} numbers, not {raw.shape[1]}"
            )

        facets = facet_distances(standardise(raw))
        totals = sum(WEIGHTS[name] * matrix for name, matrix in facets.items())

        # Every distance in the selection, once and in order, so a
        # percentile is a rank in this library rather than a number out
        # of the air.
        above = np.triu_indices(len(keys), k=1)
        pairs = np.sort(totals[above]) if len(keys) > 1 else np.zeros(0)

        # And how close songs here usually get to anything at all: each
        # song's distance to its own nearest. This is what the five
        # marks are read against, because a raw percentile of all pairs
        # cannot be: over 944 songs every nearest neighbour sits in the
        # top fraction of a percent, and over eleven none of them
        # reaches even the 85th. A scale that says "five" for everything
        # or "one" for everything says nothing either way.
        typical = np.zeros(0)
        if len(keys) > 1:
            off = totals + np.diag(np.full(len(keys), np.inf))
            typical = np.sort(off.min(axis=1))

        return cls(keys, videos, totals, facets, pairs, typical)

    def knows(self, key: str) -> bool:
        """Whether this song has a vector, and so a place in the order."""

        return key in self._at

    def neighbours(self, key, count=5, among=None) -> list[Neighbour]:
        """The nearest songs to one, nearest first.

        Args:
            key: the song to describe.
            count: how many to return.
            among: restrict to these keys. The radio may only offer what
                it could actually play, and that is what the listing
                holds.

        Returns:
            At most `count` Neighbours, never including the song itself
            nor another copy of the same recording.
        """

        here = self._at.get(key)
        if here is None:
            return []

        mine = self._videos[here]
        row = self._totals[here]

        found = []

        for there in np.argsort(row, kind="stable"):
            if there == here:
                continue

            # Two keys, one recording: a distance of zero that would
            # make every duplicated song its own neighbour number one.
            if self._videos[there] == mine:
                continue

            if among is not None and self._keys[there] not in among:
                continue

            found.append(Neighbour(
                key=self._keys[there],
                distance=float(row[there]),
                percentile=self._percentile(row[there]),
                facet=self._closest_facet(here, there),
            ))

            if len(found) == count:
                break

        return found

    def closeness(self, distance: float) -> int:
        """How close that is, from 1 to 5, for this selection.

        Read against how close songs here usually get to anything —
        every song's distance to its own nearest — rather than against
        all pairs. Five means closer than most songs ever come to
        anything; one means these two are only each other's nearest for
        want of better.

        Self-calibrating on purpose: the same fixed percentiles cannot
        serve a library of 944 and a filter holding eleven.
        """

        if self._typical.size == 0:
            return 1

        # How many songs get closer to something than these two are.
        below = float(np.searchsorted(self._typical, distance))
        share = below / self._typical.size

        for mark, limit in enumerate((0.2, 0.4, 0.6, 0.8), start=1):
            if share < limit:
                return 6 - mark

        return 1

    def table(self, count: int = 8) -> dict:
        """Each song's nearest few, as positions into a list of keys.

        For the browser, so that steering the radio can replan the walk
        from where you steered it without a round trip — and without the
        Play next animation being lost to a full swap of the listing.

        Positions and not keys: 944 songs times eight keys of sixteen
        characters is 230 KB, and the same thing as small integers is
        thirty.

        Args:
            count: how many to keep for each song. Eight covers the
                first dozen steps after a steer, which is all anyone
                hears before steering again or letting it run.

        Returns:
            {"keys": [...], "near": [[position, ...], ...]}, the two
            lists in the same order.
        """

        if not self._keys:
            return {"keys": [], "near": []}

        # One sort of the whole matrix rather than one per song: 944 by
        # 944 is 30 ms here and a Python loop over it is seconds.
        order = np.argsort(self._totals, axis=1, kind="stable")

        near = []
        for here in range(len(self._keys)):
            mine = self._videos[here]
            kept = []

            for there in order[here]:
                if there == here or self._videos[there] == mine:
                    continue

                kept.append(int(there))
                if len(kept) == count:
                    break

            near.append(kept)

        return {"keys": list(self._keys), "near": near}

    def _percentile(self, distance: float) -> float:
        """How close this is, as a rank among every pair in the space.

        100 means closer than every other pair; 0, further than all of
        them.
        """

        if self._pairs.size == 0:
            return 0.0

        below = float(np.searchsorted(self._pairs, distance))

        return 100.0 * (1.0 - below / self._pairs.size)

    def _closest_facet(self, here: int, there: int) -> str:
        """Which axis brings these two together.

        The smallest of the four distances the total was made of — so
        the explanation costs a lookup, not a second computation.
        """

        return min(FACETS, key=lambda name: self._facets[name][here, there])


def chain(space: "Space", keys, start: str) -> list[str]:
    """Order a selection as a walk from each song to its nearest.

    The property the radio rests on: the song after any song is that
    song's nearest neighbour among those not yet passed. True by
    construction, so nothing has to decide it when a track ends — and
    "do nothing and the closest plays next" needs no code at all.

    Greedy and not optimal. The shortest path through 944 points is a
    travelling salesman, and the difference would be audible to nobody:
    what is heard is each step, and each step here is the best one
    available.

    Args:
        space: the distances, built over the same selection.
        keys: every row in the selection, in the order it arrived —
            including songs the space does not know.
        start: where to begin. A key nobody knows starts from the top.

    Returns:
        Every key, once. Songs with no vector come last, in the order
        they came in: they have no place in the order the others are in,
        which is where a song its playlist has dropped goes too.
    """

    known = [key for key in keys if space.knows(key)]
    unknown = [key for key in keys if not space.knows(key)]

    if not known:
        return unknown

    held = set(known)
    here = start if start in held else known[0]

    left = held
    left.discard(here)
    walk = [here]

    while left:
        # Asked of the space rather than worked out again, so the walk
        # inherits the rule that keeps two copies of one recording from
        # following each other.
        nearest = space.neighbours(here, count=1, among=left)

        here = nearest[0].key if nearest else next(iter(sorted(left)))
        left.discard(here)
        walk.append(here)

    return walk + unknown
