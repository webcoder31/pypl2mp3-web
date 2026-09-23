"""The extractor, driven on signals we build rather than on MP3s.

What a feature gets right or wrong is arithmetic over samples, and every
wrong version of it is a source file that reads perfectly well. A click
track has a tempo we chose; a sine has a centroid we can compute by
hand. That is what makes these assertions worth making.

ffmpeg reads WAV, so the one test that needs a real decode writes one
with the standard library instead of requiring an MP3 encoder.
"""

from pathlib import Path
import wave

import numpy as np
import pytest

from pypl2mp3.libs.features import (
    FeatureError,
    SAMPLE_RATE,
    extract_samples,
)


def _write_wav(path: Path, samples: np.ndarray, rate: int = 44100) -> Path:
    """A real audio file, for the one thing that needs ffmpeg."""

    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767).astype("<i2").tobytes()

    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm)

    return path


def test_the_decoder_resamples_to_the_rate_the_features_assume(tmp_path):
    """Everything downstream converts frames to seconds with this rate.
    A file at 44.1 kHz decoded as if it were 22.05 would report every
    tempo at half its value."""

    seconds = 2.0
    time = np.arange(int(44100 * seconds)) / 44100
    wav = _write_wav(tmp_path / "tone.wav", np.sin(2 * np.pi * 440 * time))

    samples = extract_samples(wav)

    assert samples.dtype == np.float32
    assert len(samples) == pytest.approx(SAMPLE_RATE * seconds, rel=0.02)
    assert abs(samples).max() == pytest.approx(1.0, abs=0.05)


def test_a_file_that_is_not_audio_is_a_feature_error(tmp_path):
    """Named rather than raised through: a failed decode degrades to a
    song without a vector, which the listing already knows how to show."""

    junk = tmp_path / "not-audio.mp3"
    junk.write_bytes(b"this is not an MP3")

    with pytest.raises(FeatureError):
        extract_samples(junk)


def test_a_file_that_is_not_there_is_a_feature_error(tmp_path):
    """The bulk job walks a directory that another process may be
    reorganising; a song can vanish between the glob and the decode."""

    with pytest.raises(FeatureError):
        extract_samples(tmp_path / "gone.mp3")
