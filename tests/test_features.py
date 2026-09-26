"""The extractor, driven on signals we build rather than on MP3s.

What a feature gets right or wrong is arithmetic over samples, and every
wrong version of it is a source file that reads perfectly well. A click
track has a tempo we chose; a sine has a centroid we can compute by
hand. That is what makes these assertions worth making.

ffmpeg reads WAV, so the one test that needs a real decode writes one
with the standard library instead of requiring an MP3 encoder.
"""

import math
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


def _clicks(bpm: float, seconds: float = 8.0) -> np.ndarray:
    """A click track: the one signal whose tempo we know exactly."""

    out = np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)
    step = SAMPLE_RATE * 60.0 / bpm

    # 5 ms of decaying noise per click — an impulse one sample wide is
    # not something a 46 ms window can see.
    rng = np.random.default_rng(1)
    length = int(SAMPLE_RATE * 0.005)
    click = (rng.standard_normal(length)
             * np.exp(-np.arange(length) / (length / 4))).astype(np.float32)

    at = 0.0
    while int(at) + length < len(out):
        out[int(at):int(at) + length] += click
        at += step

    return out


@pytest.mark.parametrize("bpm", [55.0, 90.0, 120.0, 150.0, 170.0, 190.0])
def test_the_tempo_of_a_click_track_is_the_tempo_we_built_it_with(bpm):
    """Measured at 0.3% across this range, so 2% is a real bound rather
    than a formality — and loose enough that one frame of lag either way
    does not fail it."""

    from pypl2mp3.libs.features import rhythm_of

    found = rhythm_of(_clicks(bpm))[0]

    assert found == pytest.approx(bpm, rel=0.02), f"built {bpm}, read {found}"


def test_a_tempo_is_not_reported_at_half_its_value():
    """The one wrong answer that looks entirely plausible.

    A pulse at twice the period is just as periodic, so the
    autocorrelation peaks there too — and when the true period falls
    between two frames, which 150 BPM does at 34.45, the doubled peak is
    the sharper of the two and wins. This read 74.9 before the fix.
    """

    from pypl2mp3.libs.features import rhythm_of

    found = rhythm_of(_clicks(150.0))[0]

    assert found > 120.0, f"read {found:.1f}, which is about half of 150"


def test_a_faster_track_reads_as_faster():
    """The ratio matters more than the absolute value: an estimator that
    halves or doubles is a known failure mode, one that inverts the
    order of two tracks is useless."""

    from pypl2mp3.libs.features import rhythm_of

    slow = rhythm_of(_clicks(70.0))[0]
    fast = rhythm_of(_clicks(140.0))[0]

    assert fast > slow * 1.5, f"{slow:.0f} then {fast:.0f}"


def test_a_steady_pulse_is_clearer_than_noise():
    from pypl2mp3.libs.features import rhythm_of

    assert rhythm_of(_clicks(120.0))[1] > rhythm_of(_noise())[1] * 2


def test_a_denser_track_strikes_more_often():
    """Onset rate is not tempo: a track can be slow and busy."""

    from pypl2mp3.libs.features import rhythm_of

    assert rhythm_of(_clicks(160.0))[2] > rhythm_of(_clicks(60.0))[2]


def test_the_rhythm_is_the_size_the_layout_says():
    from pypl2mp3.libs.features import RHYTHM, rhythm_of

    assert len(rhythm_of(_clicks(120.0))) == RHYTHM.stop - RHYTHM.start


def test_silence_has_a_rhythm_of_nothing_rather_than_a_crash():
    from pypl2mp3.libs.features import RHYTHM, rhythm_of

    out = rhythm_of(np.zeros(SAMPLE_RATE * 2, dtype=np.float32))

    assert len(out) == RHYTHM.stop - RHYTHM.start
    assert np.isfinite(out).all()


def test_a_compressed_signal_has_a_lower_crest_than_a_peaky_one():
    """Crest factor is production, not composition — and production is
    much of what makes two tracks sound like they belong together."""

    from pypl2mp3.libs.features import dynamics_of

    steady = dynamics_of(_sine(440, gain=0.5))[1]

    peaky = np.zeros(int(SAMPLE_RATE * 4), dtype=np.float32)
    peaky[::5000] = 0.9

    assert dynamics_of(peaky)[1] > steady + 6.0


def test_a_louder_signal_reads_as_louder():
    from pypl2mp3.libs.features import dynamics_of

    assert dynamics_of(_sine(440, gain=0.8))[0] > \
           dynamics_of(_sine(440, gain=0.1))[0]


def test_a_track_that_swells_has_a_wider_range_than_a_steady_one():
    """What separates a symphony from a pop master: not how loud, but
    how much the loudness moves."""

    from pypl2mp3.libs.features import dynamics_of

    steady = _sine(440, seconds=8.0, gain=0.5)
    swelling = steady * np.linspace(0.02, 1.0, len(steady)).astype(np.float32)

    assert dynamics_of(swelling)[2] > dynamics_of(steady)[2] + 10.0


def test_the_whole_vector_is_the_length_the_frame_expects():
    from pypl2mp3.libs.features import FEATURE_COUNT, features_of

    values = features_of(_clicks(120.0))

    assert len(values) == FEATURE_COUNT
    assert all(math.isfinite(v) for v in values), values


def test_every_facet_lands_in_its_own_slice():
    """The layout is a contract between the writer and every later
    reader. A rhythm written where the colour is read would still be
    forty finite numbers, and nothing downstream could tell."""

    from pypl2mp3.libs.features import (
        COLOUR, DYNAMICS, RHYTHM, TIMBRE,
        colour_of, dynamics_of, features_of, rhythm_of, timbre_of,
    )

    samples = _clicks(120.0)
    whole = np.array(features_of(samples))

    assert whole[TIMBRE] == pytest.approx(timbre_of(samples), rel=1e-5)
    assert whole[RHYTHM] == pytest.approx(rhythm_of(samples), rel=1e-5)
    assert whole[COLOUR] == pytest.approx(colour_of(samples), rel=1e-5)
    assert whole[DYNAMICS] == pytest.approx(dynamics_of(samples), rel=1e-5)


def test_silence_produces_a_vector_rather_than_a_nan(tmp_path):
    """A log of zero somewhere upstream poisons every distance this song
    takes part in, and poisons them silently: comparisons against NaN
    are false rather than wrong."""

    from pypl2mp3.libs.features import FEATURE_COUNT, features_of

    values = features_of(np.zeros(SAMPLE_RATE * 3, dtype=np.float32))

    assert len(values) == FEATURE_COUNT
    assert all(math.isfinite(v) for v in values)


def test_a_song_is_analysed_once_and_read_back_after(tmp_path, monkeypatch):
    """The second call must not decode. That is the difference between
    opening the inspector and waiting a second for it."""

    from pypl2mp3.libs import features as mod

    # Eight frames and not one: mutagen cannot sync to a single MPEG
    # frame, store_features swallows the error as it is meant to, and
    # the test then measures the fallback instead of the cache.
    path = tmp_path / "ARTIST - Title [aaaaaaaaaaa].mp3"
    path.write_bytes((b"\xff\xfb\x90\xc0" + b"\x00" * 413) * 8)

    decodes = []
    monkeypatch.setattr(
        mod, "extract_samples",
        lambda p: (decodes.append(p), _clicks(120.0))[1],
    )

    first = mod.features_for(path)
    second = mod.features_for(path)

    assert len(decodes) == 1, f"decoded {len(decodes)} times"
    assert second == pytest.approx(first, rel=1e-5)
