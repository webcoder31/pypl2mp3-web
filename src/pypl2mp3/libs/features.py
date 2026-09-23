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


# 46 ms of signal every 12 ms. The window is long enough to resolve a
# bass note and short enough that a drum hit is one frame rather than
# smeared across three — the same compromise serves the timbre and the
# onsets, which is why there is one spectrogram here and not two.
FRAME_SIZE = 1024
HOP = 256
FRAMES_PER_SECOND = SAMPLE_RATE / HOP

# How many frames are held at once. Everything downstream reduces each
# block to a handful of numbers, so this bounds the cost of a long track
# without changing any result: ten minutes at this hop is 51 000 frames
# of 513 bins, which is 105 MB held for nothing.
BLOCK = 4096

MEL_BANDS = 26
MEL_LOW = 40.0
MEL_HIGH = 10000.0

# Thirteen coefficients, and the first is deliberately not among them:
# C0 is the frame's total energy, which is what the dynamics facet
# measures. Keeping it would let the volume vote twice and call it
# timbre.
CEPSTRA = 13


def _to_mel(hz):
    return 2595.0 * np.log10(1.0 + np.asarray(hz) / 700.0)


def _from_mel(mel):
    return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)


def _mel_filters() -> np.ndarray:
    """Triangular filters, evenly spaced on the mel scale.

    Returns:
        (MEL_BANDS, FRAME_SIZE // 2 + 1) of weights.
    """

    bins = FRAME_SIZE // 2 + 1
    edges = _from_mel(
        np.linspace(_to_mel(MEL_LOW), _to_mel(MEL_HIGH), MEL_BANDS + 2)
    )
    points = np.floor((FRAME_SIZE + 1) * edges / SAMPLE_RATE).astype(int)
    points = np.clip(points, 0, bins - 1)

    filters = np.zeros((MEL_BANDS, bins), dtype=np.float32)
    for band in range(MEL_BANDS):
        left, centre, right = points[band:band + 3]
        # Bands crowd together at the bottom of the scale, where two
        # edges can land on the same bin. A filter one bin wide is still
        # a filter; a filter zero bins wide is a division by zero.
        centre = max(centre, left + 1)
        right = max(right, centre + 1)
        if right >= bins:
            continue
        filters[band, left:centre] = np.linspace(0, 1, centre - left,
                                                 endpoint=False)
        filters[band, centre:right] = np.linspace(1, 0, right - centre,
                                                  endpoint=False)

    return filters


def _dct_basis() -> np.ndarray:
    """DCT-II as a matrix, because numpy has no dct and scipy is not a
    dependency of this project."""

    k = np.arange(CEPSTRA + 1)[:, None]
    n = np.arange(MEL_BANDS)[None, :]

    return np.cos(np.pi * k * (2 * n + 1) / (2 * MEL_BANDS)).astype(np.float32)


_MEL = _mel_filters()
_DCT = _dct_basis()
_WINDOW = np.hanning(FRAME_SIZE).astype(np.float32)


def spectrogram(samples: np.ndarray):
    """Magnitude spectra, in blocks.

    Args:
        samples: mono float32.

    Yields:
        Arrays of shape (n, FRAME_SIZE // 2 + 1), n at most BLOCK.
        Nothing at all when the signal is shorter than one window.
    """

    if len(samples) < FRAME_SIZE:
        return

    count = 1 + (len(samples) - FRAME_SIZE) // HOP

    for start in range(0, count, BLOCK):
        stop = min(start + BLOCK, count)
        frames = np.stack([
            samples[at * HOP:at * HOP + FRAME_SIZE]
            for at in range(start, stop)
        ])

        yield np.abs(np.fft.rfft(frames * _WINDOW, axis=1)).astype(np.float32)


def _middle_and_spread(values: np.ndarray) -> np.ndarray:
    """Median and interquartile range, down each column.

    Robust on purpose: a silent intro or a fade-out pulls a mean, and
    every song here has one or the other.
    """

    low, middle, high = np.percentile(values, [25, 50, 75], axis=0)

    return np.concatenate([middle, high - low]).astype(np.float32)


def timbre_of(samples: np.ndarray) -> np.ndarray:
    """13 cepstral coefficients, as a median and a spread each.

    Args:
        samples: mono float32 at SAMPLE_RATE.

    Returns:
        26 values: 13 medians, then 13 interquartile ranges.
    """

    cepstra = []
    for block in spectrogram(samples):
        # Power into the filters, log out of them: hearing is closer to
        # logarithmic than linear, and the log is also what turns a
        # filter's gain into an additive offset the DCT can separate.
        energies = (block ** 2) @ _MEL.T
        cepstra.append(np.log(energies + 1e-10) @ _DCT.T)

    if not cepstra:
        return np.zeros(TIMBRE.stop - TIMBRE.start, dtype=np.float32)

    # [:, 1:] drops C0 — see CEPSTRA.
    return _middle_and_spread(np.concatenate(cepstra)[:, 1:])
