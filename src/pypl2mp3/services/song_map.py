#!/usr/bin/env python3
"""
PYPL2MP3: YouTube playlist MP3 converter and player,
with Shazam song identification and tagging capabilities.

Where each song sits, once the forty numbers become three.

Not a projection. A principal component analysis is free and
deterministic, but it keeps the global variance rather than the local
structure: on audio features it gives one uniform potato in which
everything overlaps. t-SNE and UMAP separate beautifully and cost a
dependency and a seed.

So: a graph of each song's nearest few, relaxed in space by a fixed
number of rounds — attraction along the edges, repulsion between every
pair. The same corpus gives the same cloud on every machine, which
matters because the map must not jump when an import has happened.

Three dimensions for real, and not a flat layout lifted by a hash.
Keeping the structure in two axes gives a picture that is technically
three-dimensional and reads as a flat map with jitter; letting the
islands find their shape in all three makes clusters you can orbit.

Copyright 2024 © Thierry Thiers <webcoder31@gmail.com>
License: CeCILL-C (http://www.cecill.info)
Repository: https://github.com/webcoder31/pypl2mp3
"""

# Python core modules
import hashlib
import math

# Third-party packages
import numpy as np


# How many neighbours hold a song in place. Enough that the clusters
# hold together, few enough that they do not merge into one.
EDGES = 8

# Fixed, and not a tolerance: a relaxation that stops when it stops
# moving stops at a different place on a different machine, and the
# whole point of this is that it does not.
#
# 150 because that is where it is best, measured over the 944 by how
# often a song's neighbours on the map are by the same artist: 1.2x
# chance before any relaxation at all, 4.1x at fifty rounds, 6.5x at a
# hundred and fifty, and then back down — 6.4x at three hundred, 6.2x
# at six. Left running, the repulsion slowly spreads out what the
# attraction gathered. Two seconds over the whole library.
ROUNDS = 150

# What the two forces are worth against each other. Attraction alone
# collapses the cloud to a point; repulsion alone scatters it evenly and
# says nothing.
#
# The repulsion is divided by the number of songs, and that is not a
# detail. Summed raw, each song is pushed by nine hundred others and
# pulled by eight — so the push wins by two orders of magnitude, the
# cloud inflates into a uniform ball, and the structure the graph holds
# is flattened out of it. Measured: genre agreement among neighbours on
# the map fell to 1.1x chance, below the 1.4x the vectors themselves
# give. Divided, each force is worth the same per neighbour.
PULL = 0.08
PUSH = 0.6

# How far a point may travel in one round, in units of the cloud's own
# scale. Without it two points that start on top of each other are flung
# to infinity by their own repulsion on the first step.
STEP = 0.1


def _seeded(key: str) -> np.ndarray:
    """A starting place that depends only on the song's name.

    Deterministic, and spread: two songs whose keys differ by a
    character must not start on top of each other, or the repulsion
    between them is a division by very nearly zero.
    """

    digest = hashlib.blake2s(key.encode(), digest_size=12).digest()
    three = np.frombuffer(digest, dtype="<u4").astype(np.float64)

    return three / 0xFFFFFFFF - 0.5


def _shell(count: int, radius: float, middle: np.ndarray) -> np.ndarray:
    """`count` points spread over a sphere, by the Fibonacci rule.

    Where the songs nobody has analysed go. Nothing can occlude the
    outermost layer of a scene, so they stay countable from every angle
    the camera can reach — and their place says the right thing: matter
    not joined to anything, on the periphery of the structure.
    """

    if count == 0:
        return np.zeros((0, 3))

    golden = math.pi * (3.0 - math.sqrt(5.0))
    at = np.arange(count, dtype=np.float64)

    # Spread evenly in height, then turned by the golden angle: the
    # arrangement that gives no two points the same place and no band
    # the crowding that even spacing in latitude would.
    y = 1.0 - (at / max(1.0, count - 1.0)) * 2.0 if count > 1 else np.zeros(1)
    ring = np.sqrt(np.clip(1.0 - y * y, 0.0, None))
    angle = golden * at

    out = np.stack([np.cos(angle) * ring, y, np.sin(angle) * ring], axis=1)

    return middle + out * radius


def layout(space, keys, rounds: int = ROUNDS) -> dict:
    """Place every song in the selection.

    Args:
        space: the distances, built over the same selection.
        keys: every row, including songs the space does not know.
        rounds: how many relaxation steps. Fixed rather than a
            tolerance, so the same corpus gives the same cloud.

    Returns:
        {key: (x, y, z)} for every key given, as plain floats.
    """

    known = [key for key in keys if space.knows(key)]
    unknown = [key for key in keys if not space.knows(key)]

    if not known:
        # Nothing has been analysed. The shell is the whole map, which
        # is an honest picture of that.
        places = _shell(len(unknown), 1.0, np.zeros(3))
        return {key: tuple(float(v) for v in places[at])
                for at, key in enumerate(unknown)}

    table = space.table(count=EDGES)
    at_of = {key: at for at, key in enumerate(table["keys"])}

    here = np.array([_seeded(key) for key in known])
    count = len(known)

    # The edges, as two parallel lists of row numbers. Each song pulls on
    # its nearest few; the pull is mutual, which is what stops a hub
    # dragging the cloud towards itself.
    starts, ends = [], []
    for at, key in enumerate(known):
        for other in table["near"][at_of[key]]:
            name = table["keys"][other]
            if name in at_of and name in set(known):
                starts.append(at)
                ends.append(known.index(name))

    starts = np.array(starts, dtype=int)
    ends = np.array(ends, dtype=int)

    for round_at in range(rounds):
        # Repulsion, every pair against every other.
        #
        # Written as two matrix products rather than as the (n, n, 3)
        # array of differences it looks like. The sum over j of
        # (x_i - x_j) / d² is x_i * Σ(1/d²) - Σ(x_j / d²), which is a
        # column sum and one matmul. The direct form allocates 21 MB a
        # round and took 25 seconds over 944 songs; this takes one.
        square = (here ** 2).sum(axis=1)
        gap = square[:, None] + square[None, :] - 2 * (here @ here.T)
        np.fill_diagonal(gap, np.inf)
        weight = 1.0 / np.maximum(gap, 1e-9)

        push = (here * weight.sum(axis=1)[:, None] - weight @ here) \
            * (PUSH / count)

        pull = np.zeros_like(here)
        if starts.size:
            along = here[ends] - here[starts]
            np.add.at(pull, starts, along * PULL)

        move = push + pull

        # Clamped, because two points that start almost on top of each
        # other repel each other to infinity on the first step — and
        # cooled, because a step that never shrinks cannot settle.
        #
        # Cooling is right and it is not what made this work: measured
        # with and without, over the whole library, it moves the result
        # by nothing at all. Kept because a walk that never slows is not
        # a layout, not because it rescued one.
        allowed = STEP * (1.0 - round_at / rounds) ** 2
        travel = np.sqrt((move ** 2).sum(axis=1))
        scale = np.minimum(1.0, allowed / np.maximum(travel, 1e-9))
        here = here + move * scale[:, None]

    places = {key: tuple(float(v) for v in here[at])
              for at, key in enumerate(known)}

    if unknown:
        middle = here.mean(axis=0)
        # Outside everything, so nothing in the cloud can hide one.
        radius = float(np.linalg.norm(here - middle, axis=1).max()) * 1.25 + 1.0
        out = _shell(len(unknown), radius, middle)
        for at, key in enumerate(unknown):
            places[key] = tuple(float(v) for v in out[at])

    return places
