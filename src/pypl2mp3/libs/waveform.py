#!/usr/bin/env python3
"""
PYPL2MP3: YouTube playlist MP3 converter and player,
with Shazam song identification and tagging capabilities.

Waveform peaks for the web player's seek bar.

Peaks live in the MP3 itself, in a private ID3 frame, rather than in a
cache directory beside it. The waveform then follows the file when it is
moved or renamed — which this application does routinely, since saving a
song rewrites its filename — and there is no second store to invalidate,
prune, or keep in step with the repository.

Extraction costs about half a second per song and happens once. The frame
it writes is 400 bytes.

Copyright 2024 © Thierry Thiers <webcoder31@gmail.com>
License: CeCILL-C (http://www.cecill.info)
Repository: https://github.com/webcoder31/pypl2mp3
"""

# Python core modules
import audioop
from pathlib import Path
import subprocess

# Third-party packages
from mutagen.id3 import PRIV
import mutagen
import mutagen.mp3


# One bar per peak. At the width the player bar actually gets — around
# 1000px — this leaves under three pixels per bar, which is the density
# that reads as a waveform rather than as a bar chart.
PEAK_COUNT = 400

# Mono, and far below any musical frequency: we are measuring how loud
# each slice is, not what it contains. It cuts the decode to a fraction
# of what full-rate stereo would cost and changes no visible bar.
SAMPLE_RATE = 8000

# The version is part of the owner, so changing how peaks are computed
# makes every existing frame invisible to `read_peaks` rather than
# subtly wrong. Old frames are then overwritten on first play.
PEAK_OWNER = "https://github.com/webcoder31/pypl2mp3#peaks-1"

# A pathological file must not tie up a worker thread forever. Half a
# second is typical; two minutes is a file that will never finish.
EXTRACT_TIMEOUT = 120


class WaveformError(Exception):
    """Raised when peaks cannot be extracted from a file."""


def extract_pcm(song_path: Path) -> bytes:
    """Decode one MP3 to raw mono samples.

    Args:
        song_path: the MP3 to decode.

    Returns:
        Signed 16-bit little-endian samples, one channel.

    Raises:
        WaveformError: if ffmpeg is missing, fails, or does not finish.
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
        raise WaveformError("ffmpeg is not installed") from error
    except subprocess.TimeoutExpired as error:
        raise WaveformError(f"{song_path.name}: decoding timed out") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", "replace").strip()
        raise WaveformError(f"{song_path.name}: {detail}") from error

    return completed.stdout


def reduce_to_peaks(pcm: bytes, count: int = PEAK_COUNT) -> bytes:
    """Reduce raw samples to one loudness value per bar.

    Each bar holds the loudest sample in its slice, on an absolute scale:
    a quiet recording draws a short waveform. Normalizing each song to
    its own loudest moment would fill every bar to the top and throw away
    the one thing this display is genuinely useful for — a download that
    came out silent or truncated looks exactly like what it is.

    Args:
        pcm: signed 16-bit little-endian mono samples.
        count: how many bars to produce.

    Returns:
        Exactly `count` bytes, each a loudness from 0 to 255.
    """

    peaks = bytearray(count)

    # Two bytes per sample, so an odd width would read each slice half a
    # sample out of step and measure noise.
    step = max(2, len(pcm) // count // 2 * 2)

    for bar in range(count):
        slice_ = pcm[bar * step:bar * step + step]
        if not slice_:
            # Audio shorter than the bar count: the rest stays silent
            # rather than repeating the last value across the bar.
            break
        peaks[bar] = min(255, audioop.max(slice_, 2) * 255 // 32768)

    return bytes(peaks)


def read_peaks(mp3: mutagen.mp3.MP3) -> bytes | None:
    """Return the peaks stored in an open MP3, or None if it has none.

    A frame of the wrong length is treated as absent: it is either a
    truncated write or a format this version does not speak, and either
    way recomputing is cheaper than drawing something wrong.
    """

    for frame in mp3.tags.getall("PRIV") if mp3.tags else []:
        if frame.owner == PEAK_OWNER and len(frame.data) == PEAK_COUNT:
            return bytes(frame.data)

    return None


def store_peaks(song_path: Path, peaks: bytes) -> None:
    """Write peaks into an MP3's tags, replacing any earlier ones.

    Other applications' private frames are preserved: only frames this
    module owns are dropped. `delall` takes a frame type, not an owner,
    so the survivors have to be put back by hand.
    """

    mp3 = mutagen.mp3.MP3(song_path)
    if mp3.tags is None:
        mp3.add_tags()

    others = [f for f in mp3.tags.getall("PRIV") if f.owner != PEAK_OWNER]
    mp3.tags.delall("PRIV")
    for frame in others:
        mp3.tags.add(frame)

    mp3.tags.add(PRIV(owner=PEAK_OWNER, data=peaks))
    mp3.save(v1=0, v2_version=3)


def peaks_for(song_path: Path) -> bytes:
    """The waveform of one song, computed once and kept in the file.

    Args:
        song_path: the MP3 to describe.

    Returns:
        Exactly PEAK_COUNT bytes, each a loudness from 0 to 255.

    Raises:
        WaveformError: if the file carries no peaks and cannot be decoded.
    """

    try:
        stored = read_peaks(mutagen.mp3.MP3(song_path))
    except (mutagen.MutagenError, OSError):
        # A file whose tags cannot be read is not this function's verdict
        # to give. Fall through and let the decoder be the judge: it
        # reports a WaveformError, which the player degrades to the plain
        # seek bar instead of a stack trace.
        stored = None

    if stored is not None:
        return stored

    peaks = reduce_to_peaks(extract_pcm(song_path))

    try:
        store_peaks(song_path, peaks)
    except Exception:
        # A read-only file, a full disk, a file being written by another
        # process: none of that is a reason to refuse the waveform we
        # already hold. It just gets recomputed next time.
        pass

    return peaks
