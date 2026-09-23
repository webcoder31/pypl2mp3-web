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


def _sine(hz: float, seconds: float = 4.0, gain: float = 0.5) -> np.ndarray:
    time = np.arange(int(SAMPLE_RATE * seconds), dtype=np.float32) / SAMPLE_RATE
    return (gain * np.sin(2 * np.pi * hz * time)).astype(np.float32)


def _noise(seconds: float = 4.0, gain: float = 0.5) -> np.ndarray:
    # Seeded: a test that fails one run in twenty teaches nothing.
    rng = np.random.default_rng(20260923)
    count = int(SAMPLE_RATE * seconds)
    return (gain * rng.standard_normal(count)).astype(np.float32)


def test_two_different_sounds_have_different_timbres():
    from pypl2mp3.libs.features import timbre_of

    apart = np.abs(timbre_of(_noise()) - timbre_of(_sine(220))).max()

    # Measured at 79 on this pair. The threshold sits an order of
    # magnitude below it and still an order of magnitude above the 0.014
    # that the volume test calls invariance — a gap that wide is what
    # makes both numbers mean something.
    assert apart > 10.0, "white noise and a low sine read as the same timbre"


def test_the_same_sound_played_louder_keeps_its_timbre():
    """The whole point of dropping the first cepstral coefficient: it is
    energy, and energy is what the dynamics facet is for. A timbre that
    moved with the volume would make every loud song neighbour every
    other loud song."""

    from pypl2mp3.libs.features import timbre_of

    quiet = timbre_of(_sine(440, gain=0.1))
    loud = timbre_of(_sine(440, gain=0.8))

    # Measured at 0.014 for a volume multiplied by eight.
    assert np.abs(quiet - loud).max() < 0.1, "the timbre followed the volume"


def test_the_timbre_is_the_size_the_layout_says():
    from pypl2mp3.libs.features import TIMBRE, timbre_of

    assert len(timbre_of(_sine(440))) == TIMBRE.stop - TIMBRE.start


def test_a_signal_shorter_than_one_window_is_not_a_crash():
    """Every library has a two-second interlude in it somewhere."""

    from pypl2mp3.libs.features import TIMBRE, timbre_of

    out = timbre_of(np.zeros(100, dtype=np.float32))

    assert len(out) == TIMBRE.stop - TIMBRE.start
    assert np.isfinite(out).all()


def test_a_bright_sound_has_a_higher_centroid_than_a_dark_one():
    from pypl2mp3.libs.features import colour_of

    low = colour_of(_sine(200))[0]
    high = colour_of(_sine(5000))[0]

    assert high > low * 3, f"centroids {low:.0f} and {high:.0f} barely differ"


def test_noise_is_flatter_than_a_tone():
    """Flatness is the one number that separates a texture from a note,
    and it is what puts a distorted guitar nearer a cymbal than a clean
    one."""

    from pypl2mp3.libs.features import colour_of

    tone = colour_of(_sine(440))[2]
    noise = colour_of(_noise())[2]

    assert noise > tone * 5, f"flatness {tone:.4f} vs {noise:.4f}"


def test_a_tone_between_two_bins_still_reads_as_a_tone():
    """What the Hann window is for, and the only test that can see it.

    A sine whose frequency falls between two FFT bins cannot be
    represented by either, and without a window the error spills across
    the whole spectrum — a pure tone then measures as flat as noise.
    Every window here is 22050/1024 = 21.53 Hz wide, so half of that is
    the worst case.
    """

    from pypl2mp3.libs.features import FRAME_SIZE, SAMPLE_RATE, colour_of

    spacing = SAMPLE_RATE / FRAME_SIZE
    on_bin = colour_of(_sine(spacing * 20))[2]
    between = colour_of(_sine(spacing * 20.5))[2]

    assert between < on_bin * 50, (
        f"a tone off the bin grid reads as {between:.4f} against "
        f"{on_bin:.4f} on it — the leak is not being windowed"
    )


def test_the_colour_is_the_size_the_layout_says():
    from pypl2mp3.libs.features import COLOUR, colour_of

    assert len(colour_of(_sine(440))) == COLOUR.stop - COLOUR.start
