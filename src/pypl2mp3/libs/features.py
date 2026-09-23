#!/usr/bin/env python3
"""
PYPL2MP3: YouTube playlist MP3 converter and player,
with Shazam song identification and tagging capabilities.

What a song sounds like, in forty numbers.

The vector lives in the MP3 itself, in a private ID3 frame, for the
reason the waveform does: this application renames files routinely —
saving a song rewrites its filename — and a store keyed on the path
would be orphaned by every correction. 160 bytes per song.

Raw values only. Normalizing means knowing the spread of the whole
library, which changes at every import; vectors normalized against an
older library would be wrong *relative to each other*, which is the one
kind of wrong nothing reports. So the frame says what is true of this
song alone, and the collection's statistics are recomputed on demand.

The version is part of the owner, so changing how a feature is computed
makes every existing frame invisible to `read_features` rather than
subtly wrong.

Copyright 2024 © Thierry Thiers <webcoder31@gmail.com>
License: CeCILL-C (http://www.cecill.info)
Repository: https://github.com/webcoder31/pypl2mp3
"""

# Python core modules
import math
from pathlib import Path
import struct
import subprocess
from typing import Sequence

# Third-party packages
from mutagen.id3 import PRIV
import mutagen
import mutagen.mp3
import numpy as np


# Four facets, and the slice each one occupies. Fixed for the lifetime
# of this version number: a reader disagreeing with the writer about
# where the rhythm starts would compare a tempo against a cepstral
# coefficient and report a distance for it.
TIMBRE = slice(0, 26)
RHYTHM = slice(26, 29)
COLOUR = slice(29, 37)
DYNAMICS = slice(37, 40)

FEATURE_COUNT = 40

FEATURE_OWNER = "https://github.com/webcoder31/pypl2mp3#features-1"


class FeatureError(Exception):
    """Raised when a song's features cannot be computed."""


def pack_features(values: Sequence[float]) -> bytes:
    """Lay a vector out as bytes for the frame.

    Args:
        values: exactly FEATURE_COUNT finite numbers.

    Returns:
        FEATURE_COUNT * 4 bytes, little-endian float32.

    Raises:
        ValueError: wrong length, or a value that is not finite.
    """

    if len(values) != FEATURE_COUNT:
        raise ValueError(
            f"a vector is {FEATURE_COUNT} numbers, not {len(values)}"
        )

    for at, value in enumerate(values):
        if not math.isfinite(value):
            raise ValueError(f"feature {at} is {value}")

    return struct.pack(f"<{FEATURE_COUNT}f", *values)


def unpack_features(data: bytes) -> list[float]:
    """The inverse of `pack_features`, for data of the right length."""

    return list(struct.unpack(f"<{FEATURE_COUNT}f", data))


def read_features(mp3: mutagen.mp3.MP3) -> list[float] | None:
    """Return the vector stored in an open MP3, or None if it has none.

    A frame of the wrong length is treated as absent: it is a truncated
    write or a layout this version does not speak, and reading it would
    mis-shape every distance this song takes part in.
    """

    for frame in mp3.tags.getall("PRIV") if mp3.tags else []:
        if (frame.owner == FEATURE_OWNER
                and len(frame.data) == FEATURE_COUNT * 4):
            return unpack_features(bytes(frame.data))

    return None


def store_features(song_path: Path, values: Sequence[float]) -> None:
    """Write a vector into an MP3's tags, replacing any earlier one.

    Other applications' private frames are preserved — the waveform's
    peaks among them. `delall` takes a frame type, not an owner, so the
    survivors have to be put back by hand.
    """

    data = pack_features(values)

    mp3 = mutagen.mp3.MP3(song_path)
    if mp3.tags is None:
        mp3.add_tags()

    others = [f for f in mp3.tags.getall("PRIV") if f.owner != FEATURE_OWNER]
    mp3.tags.delall("PRIV")
    for frame in others:
        mp3.tags.add(frame)

    mp3.tags.add(PRIV(owner=FEATURE_OWNER, data=data))
    mp3.save(v1=0, v2_version=3)


# High enough that the timbre exists. The waveform settles for 8 kHz
# because it only measures how loud each slice is; here the top of a
# cymbal has to be on the other side of Nyquist from the bottom of a
# bass line, which 11 kHz gives and 4 kHz does not.
SAMPLE_RATE = 22050

# A pathological file must not tie up a worker forever. Five minutes is
# a file that will never finish; a real one takes half a second.
EXTRACT_TIMEOUT = 300


def extract_samples(song_path: Path) -> np.ndarray:
    """Decode one file to mono samples at SAMPLE_RATE.

    Args:
        song_path: the audio file to decode.

    Returns:
        float32 in [-1, 1], one channel.

    Raises:
        FeatureError: if ffmpeg is missing, fails, or does not finish.
    """

    try:
        completed = subprocess.run(
            [
                "ffmpeg",
                "-v", "error",
                # Without this, ffmpeg inherits the server's stdin and
                # can block on a prompt nobody will ever answer.
                "-nostdin",
                "-i", str(song_path),
                "-ac", "1",
                "-ar", str(SAMPLE_RATE),
                "-f", "s16le",
                "-",
            ],
            capture_output=True,
            check=True,
            timeout=EXTRACT_TIMEOUT,
        )
    except FileNotFoundError as error:
        raise FeatureError("ffmpeg is not installed") from error
    except subprocess.TimeoutExpired as error:
        raise FeatureError(f"{song_path.name}: decoding timed out") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", "replace").strip()
        raise FeatureError(f"{song_path.name}: {detail}") from error

    raw = np.frombuffer(completed.stdout, dtype="<i2")
    if raw.size == 0:
        raise FeatureError(f"{song_path.name}: decoded to nothing")

    # Copied out of the buffer rather than viewed into it: `frombuffer`
    # gives a read-only array, and every window below is multiplied in
    # place by its own window function.
    return np.array(raw, dtype=np.float32) / 32768.0
