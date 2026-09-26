# Similarité musicale — étape 1 : le vecteur, les distances, la règle

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** donner à chaque morceau un vecteur de 40 traits calculés depuis
son audio, rangé dans le MP3, et de quoi mesurer si ce vecteur vaut
quelque chose.

**Architecture:** un seul décodage ffmpeg par morceau, une seule STFT en
numpy, quatre facettes dérivées de ces deux objets ; le vecteur brut va
dans une frame ID3 privée versionnée, exactement comme `libs/waveform.py`
range ses peaks ; la normalisation et les distances se calculent à la
volée sur la sélection, jamais dans le fichier.

**Tech Stack:** Python 3.13, numpy 1.26.4 (déjà installé), ffmpeg 8.0.1
(déjà utilisé), mutagen, FastAPI, pytest.

**Spec:** `docs/superpowers/specs/2026-09-23-similarite-musicale-design.md`

**Cairn:** PYPL2MP3-2, sous PYPL2MP3-1. Bloque PYPL2MP3-3 et PYPL2MP3-4.

## Global Constraints

- **Aucune dépendance nouvelle.** numpy et ffmpeg sont déjà là ; rien
  d'autre ne s'ajoute. Pas de scipy, pas de librosa, pas de sklearn.
- **La frame ne contient que des valeurs brutes.** Aucune normalisation
  n'est stockée. Les statistiques de la collection se recalculent.
- **40 `float32` petit-boutiens** exactement, soit 160 octets. Une
  longueur différente rend la frame absente, pas douteuse.
- **Owner :** `https://github.com/webcoder31/pypl2mp3#features-1`. Le
  numéro est ce qui périme les anciennes frames.
- **Les tests de l'extracteur n'ouvrent aucun MP3 :** ils fabriquent le
  signal. Chaque assertion a sa contre-expérience.
- **Ordre des facettes dans le vecteur, définitif :** timbre `[0:26]`,
  rythme `[26:29]`, couleur `[29:37]`, dynamique `[37:40]`.
- **Poids :** timbre 0,45 · couleur 0,25 · rythme 0,20 · dynamique 0,10.
- Style du dépôt : docstrings Args/Returns/Raises, commentaires qui
  disent *pourquoi*, anglais dans le code.

## Écart assumé par rapport à la spec

La spec fait venir la **couleur** de `aspectralstats` et la **dynamique**
de `ebur128`, au motif que ffmpeg les calcule en C gratuitement. Cet
argument supposait qu'on n'avait pas déjà le spectre sous la main — or
la tâche 3 calcule une STFT pour le timbre, et centroïde, rolloff,
flatness et entropie s'en déduisent en trois lignes de numpy.

Donc : **un seul décodage, une seule STFT, aucun analyse de sortie
texte.** Deux passes ffmpeg supplémentaires et deux analyseurs de
métadonnées disparaissent, et le coût par morceau tombe de ~1,5 s à
~0,9 s. La dynamique se dérive du PCM (niveau RMS, facteur de crête,
dispersion des RMS courts) plutôt que d'une loudness EBU R128 : la
LUFS est une mesure perceptive pour la normalisation de diffusion, et
tout le vecteur est standardisé de toute façon.

Le nombre de dimensions et les quatre facettes ne changent pas.

---

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `src/pypl2mp3/libs/features.py` | décoder, calculer les 40 traits, lire/écrire la frame. Ignore qu'une radio ou une carte existent. |
| `src/pypl2mp3/services/similarity.py` | standardiser une sélection, distances par facette, voisins. Ignore d'où viennent les vecteurs. |
| `scripts/measure_similarity.py` | l'instrument : taux d'accord de genre. |
| `tests/test_features.py` | l'extracteur, sur signaux fabriqués. |
| `tests/test_similarity.py` | les distances, sur vecteurs fabriqués. |
| `tests/test_features_frame.py` | la frame ID3 et son aller-retour. |
| `src/pypl2mp3/services/import_playlist.py` | +1 appel, à côté des peaks. |
| `src/pypl2mp3/web/app.py` | la route du job de rattrapage. |

---

### Task 1: La frame ID3

**Files:**
- Create: `src/pypl2mp3/libs/features.py`
- Test: `tests/test_features_frame.py`

**Interfaces:**
- Produces: `FEATURE_COUNT = 40`, `FEATURE_OWNER`, `FeatureError`,
  `pack_features(values: Sequence[float]) -> bytes`,
  `unpack_features(data: bytes) -> list[float]`,
  `read_features(mp3: mutagen.mp3.MP3) -> list[float] | None`,
  `store_features(song_path: Path, values: Sequence[float]) -> None`

- [ ] **Step 1: Write the failing tests**

```python
"""The frame that carries a song's feature vector.

Tested apart from the extractor because it carries its own decision —
the vector travels inside the MP3, so it survives the renaming this
application does routinely — and because a round trip needs no audio.
"""

from pathlib import Path

import mutagen.mp3
import pytest
from mutagen.id3 import PRIV, TIT2

from pypl2mp3.libs.features import (
    FEATURE_COUNT,
    FEATURE_OWNER,
    pack_features,
    read_features,
    store_features,
    unpack_features,
)

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _song(tmp_path: Path) -> Path:
    path = tmp_path / "ARTIST - Title [aaaaaaaaaaa].mp3"
    path.write_bytes(_MP3_FRAME * 8)
    return path


def test_a_vector_survives_the_round_trip(tmp_path):
    values = [i / 7 for i in range(FEATURE_COUNT)]
    path = _song(tmp_path)

    store_features(path, values)
    back = read_features(mutagen.mp3.MP3(path))

    assert back is not None
    assert len(back) == FEATURE_COUNT
    for wrote, read in zip(values, back):
        assert read == pytest.approx(wrote, rel=1e-6)


def test_the_vector_follows_the_file_when_it_is_renamed(tmp_path):
    """The whole reason it lives in the MP3: saving a song rewrites its
    filename, and a cache keyed on the path would be orphaned by that."""

    path = _song(tmp_path)
    store_features(path, [1.0] * FEATURE_COUNT)

    moved = path.with_name("ARTIST - Better Title [aaaaaaaaaaa].mp3")
    path.rename(moved)

    assert read_features(mutagen.mp3.MP3(moved)) is not None


def test_a_frame_of_the_wrong_length_is_no_frame_at_all(tmp_path):
    """A truncated write or an older layout. Recomputing costs a second;
    reading 37 floats as if they were 40 would mis-shape every distance
    in the library and nothing would say so."""

    path = _song(tmp_path)
    mp3 = mutagen.mp3.MP3(path)
    mp3.add_tags()
    mp3.tags.add(PRIV(owner=FEATURE_OWNER, data=b"\x00" * 100))
    mp3.save()

    assert read_features(mutagen.mp3.MP3(path)) is None


def test_another_owner_is_left_alone(tmp_path):
    """Other applications' private frames — the peaks included — are not
    this module's to delete."""

    path = _song(tmp_path)
    mp3 = mutagen.mp3.MP3(path)
    mp3.add_tags()
    mp3.tags.add(PRIV(owner="someone-else", data=b"keep me"))
    mp3.tags.add(TIT2(encoding=3, text="Title"))
    mp3.save()

    store_features(path, [0.5] * FEATURE_COUNT)

    kept = mutagen.mp3.MP3(path)
    owners = [f.owner for f in kept.tags.getall("PRIV")]
    assert "someone-else" in owners
    assert FEATURE_OWNER in owners
    assert str(kept.tags["TIT2"]) == "Title"


def test_storing_twice_leaves_one_frame(tmp_path):
    path = _song(tmp_path)
    store_features(path, [1.0] * FEATURE_COUNT)
    store_features(path, [2.0] * FEATURE_COUNT)

    mp3 = mutagen.mp3.MP3(path)
    mine = [f for f in mp3.tags.getall("PRIV") if f.owner == FEATURE_OWNER]
    assert len(mine) == 1
    assert read_features(mp3)[0] == pytest.approx(2.0)


def test_a_vector_of_the_wrong_size_is_refused_at_the_door(tmp_path):
    """Refused where it is cheap to see, rather than written and found
    unreadable later."""

    with pytest.raises(ValueError):
        pack_features([1.0] * (FEATURE_COUNT - 1))


def test_something_that_is_not_a_number_is_refused(tmp_path):
    """NaN and infinity survive float32 and poison every distance they
    take part in — silently, because comparisons against NaN are false."""

    with pytest.raises(ValueError):
        pack_features([float("nan")] + [0.0] * (FEATURE_COUNT - 1))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_features_frame.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pypl2mp3.libs.features'`

- [ ] **Step 3: Write the implementation**

```python
#!/usr/bin/env python3
"""
PYPL2MP3: YouTube playlist MP3 converter and player,
with Shazam song identification and tagging capabilities.

What a song sounds like, in forty numbers.

The vector lives in the MP3 itself, in a private ID3 frame, for the
reason the waveform does: this application renames files routinely —
saving a song rewrites its filename — and a store keyed on the path
would be orphaned by every correction. 160 bytes per song.

Raw values only. Normalising means knowing the spread of the whole
library, which changes at every import; vectors normalised against an
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


# Four facets, and the slice each one occupies. Fixed forever at this
# version number: a reader that disagreed with the writer about where
# the rhythm starts would compare a tempo against a cepstral
# coefficient and report a number for it.
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
        if frame.owner == FEATURE_OWNER and len(frame.data) == FEATURE_COUNT * 4:
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_features_frame.py -q`
Expected: 7 passed

- [ ] **Step 5: Counter-experiment**

Change `len(frame.data) == FEATURE_COUNT * 4` to `len(frame.data) > 0`.
Run the tests: `test_a_frame_of_the_wrong_length_is_no_frame_at_all` must
fail. Put it back.

- [ ] **Step 6: Commit**

```bash
git add src/pypl2mp3/libs/features.py tests/test_features_frame.py
git commit -m "feat: a private frame to carry what a song sounds like"
cairn commit PYPL2MP3-2 "$(git rev-parse --short HEAD)" --repo "$PWD" --branch main
```

---

### Task 2: Le décodage

**Files:**
- Modify: `src/pypl2mp3/libs/features.py`
- Test: `tests/test_features.py`

**Interfaces:**
- Produces: `SAMPLE_RATE = 22050`, `EXTRACT_TIMEOUT = 300`,
  `extract_samples(song_path: Path) -> np.ndarray` — mono float32
  in [-1, 1].

- [ ] **Step 1: Write the failing tests**

```python
"""The extractor, driven on signals we build rather than on MP3s.

What a feature gets right or wrong is arithmetic over samples, and every
wrong version of it is a source file that reads perfectly well. A click
track has a tempo we chose; a sine has a centroid we can compute by
hand. That is what makes these assertions worth making.

ffmpeg reads WAV, so the one test that needs a real decode writes one
with the standard library instead of requiring an MP3 encoder.
"""

from pathlib import Path
import math
import struct
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_features.py -q`
Expected: FAIL — `ImportError: cannot import name 'SAMPLE_RATE'`

- [ ] **Step 3: Write the implementation**

Append to `src/pypl2mp3/libs/features.py`:

```python
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

    return (raw.astype(np.float32) / 32768.0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_features.py -q`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/pypl2mp3/libs/features.py tests/test_features.py
git commit -m "feat: decode a song to the rate the features assume"
```

---

### Task 3: Le spectre, et le timbre

**Files:**
- Modify: `src/pypl2mp3/libs/features.py`
- Test: `tests/test_features.py`

**Interfaces:**
- Produces: `FRAME_SIZE = 1024`, `HOP = 256`, `FRAMES_PER_SECOND`,
  `spectrogram(samples) -> Iterator[np.ndarray]` (blocks of shape
  `(n, 513)`), `timbre_of(samples) -> np.ndarray` (26 values:
  13 medians then 13 interquartile ranges).

**Why a block iterator:** a ten-minute track at this hop is 51 000
frames of 513 bins — 105 MB as float32, held for nothing, since every
consumer only needs per-frame summaries. Blocks of 4 096 frames bound it
to 8 MB and change no result.

- [ ] **Step 1: Write the failing tests**

```python
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

    assert apart > 1.0, "white noise and a low sine read as the same timbre"


def test_the_same_sound_played_louder_keeps_its_timbre():
    """The whole point of dropping the first cepstral coefficient: it is
    energy, and energy is what the dynamics facet is for. A timbre that
    moved with the volume would make every loud song neighbour every
    other loud song."""

    from pypl2mp3.libs.features import timbre_of

    quiet = timbre_of(_sine(440, gain=0.1))
    loud = timbre_of(_sine(440, gain=0.8))

    assert np.abs(quiet - loud).max() < 0.5, "the timbre followed the volume"


def test_the_timbre_is_the_size_the_layout_says():
    from pypl2mp3.libs.features import TIMBRE, timbre_of

    assert len(timbre_of(_sine(440))) == TIMBRE.stop - TIMBRE.start
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_features.py -q`
Expected: FAIL — `cannot import name 'timbre_of'`

- [ ] **Step 3: Write the implementation**

Append to `src/pypl2mp3/libs/features.py`:

```python
# 46 ms of signal every 12 ms. The window is long enough to resolve a
# bass note and short enough that a drum hit is one frame rather than
# smeared across three — the same compromise serves the timbre and the
# onsets, which is why there is one spectrogram and not two.
FRAME_SIZE = 1024
HOP = 256
FRAMES_PER_SECOND = SAMPLE_RATE / HOP

# How many frames are held in memory at once. Everything downstream
# reduces each block to a handful of numbers, so this bounds the cost of
# a long track without changing any result.
BLOCK = 4096

MEL_BANDS = 26
MEL_LOW = 40.0
MEL_HIGH = 10000.0

# Thirteen coefficients, and the first is deliberately not among them:
# C0 is the frame's total energy, which is what the dynamics facet
# measures. Keeping it would let the volume vote twice and call it
# timbre.
CEPSTRA = 13


def _to_mel(hz: np.ndarray) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def _from_mel(mel: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def _mel_filters() -> np.ndarray:
    """Triangular filters, evenly spaced on the mel scale.

    Returns:
        (MEL_BANDS, FRAME_SIZE // 2 + 1) of weights.
    """

    bins = FRAME_SIZE // 2 + 1
    edges = _from_mel(
        np.linspace(_to_mel(np.array(MEL_LOW)), _to_mel(np.array(MEL_HIGH)),
                    MEL_BANDS + 2)
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
    """DCT-II, as a matrix, because numpy has no dct and scipy is not a
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
        Arrays of shape (n, FRAME_SIZE // 2 + 1), n <= BLOCK.
    """

    count = 1 + max(0, (len(samples) - FRAME_SIZE) // HOP)

    for start in range(0, count, BLOCK):
        stop = min(start + BLOCK, count)
        frames = np.lib.stride_tricks.as_strided(
            samples,
            shape=(stop - start, FRAME_SIZE),
            strides=(samples.strides[0] * HOP, samples.strides[0]),
        )[start:stop] if False else np.stack([
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

    # [1:] drops C0 — see CEPSTRA.
    return _middle_and_spread(np.concatenate(cepstra)[:, 1:])
```

- [ ] **Step 4: Simplify `spectrogram`**

The `as_strided ... if False else` above is a placeholder for a decision
the implementer must make and must not leave dangling: **use the plain
`np.stack` form**, delete the `as_strided` branch entirely. Striding
saves a copy but aliases the input buffer, and the multiplication by the
window would then write into it on some numpy versions. Correctness
first; the copy is 8 MB per block.

Final form:

```python
        frames = np.stack([
            samples[at * HOP:at * HOP + FRAME_SIZE]
            for at in range(start, stop)
        ])
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_features.py -q`
Expected: 5 passed

- [ ] **Step 6: Counter-experiment**

Remove the `[:, 1:]` that drops C0.
`test_the_same_sound_played_louder_keeps_its_timbre` must fail. Put it
back.

- [ ] **Step 7: Commit**

```bash
git add src/pypl2mp3/libs/features.py tests/test_features.py
git commit -m "feat: the timbre facet, as cepstra that ignore the volume"
```

---

### Task 4: La couleur

**Files:**
- Modify: `src/pypl2mp3/libs/features.py`
- Test: `tests/test_features.py`

**Interfaces:**
- Produces: `colour_of(samples) -> np.ndarray` (8 values: medians of
  centroid, rolloff, flatness, entropy, then their spreads).

- [ ] **Step 1: Write the failing tests**

```python
def test_a_bright_sound_has_a_higher_centroid_than_a_dark_one():
    from pypl2mp3.libs.features import colour_of

    low = colour_of(_sine(200))[0]
    high = colour_of(_sine(5000))[0]

    assert high > low * 3, f"centroids {low:.0f} and {high:.0f} barely differ"


def test_noise_is_flatter_than_a_tone():
    """Flatness is the one number that separates a texture from a note,
    and it is what makes a distorted guitar sit near a cymbal rather
    than near a clean one."""

    from pypl2mp3.libs.features import colour_of

    tone = colour_of(_sine(440))[2]
    noise = colour_of(_noise())[2]

    assert noise > tone * 5, f"flatness {tone:.4f} vs {noise:.4f}"


def test_the_colour_is_the_size_the_layout_says():
    from pypl2mp3.libs.features import COLOUR, colour_of

    assert len(colour_of(_sine(440))) == COLOUR.stop - COLOUR.start
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_features.py -q`
Expected: FAIL — `cannot import name 'colour_of'`

- [ ] **Step 3: Write the implementation**

```python
# Where the energy is, how noisy it is, how spread out. Taken from the
# spectrogram the timbre already computes: ffmpeg's aspectralstats would
# give the same four in C, at the cost of a second decode and a text
# format to parse.
ROLLOFF = 0.85


def colour_of(samples: np.ndarray) -> np.ndarray:
    """Four spectral descriptors, as a median and a spread each.

    Returns:
        8 values: medians of centroid (Hz), rolloff (Hz), flatness and
        entropy, then their four interquartile ranges.
    """

    freqs = np.fft.rfftfreq(FRAME_SIZE, 1.0 / SAMPLE_RATE).astype(np.float32)
    rows = []

    for block in spectrogram(samples):
        total = block.sum(axis=1) + 1e-10

        centroid = (block @ freqs) / total

        # The frequency below which ROLLOFF of the energy lies. Found by
        # walking the cumulative sum rather than by sorting: the spectrum
        # is already in frequency order, which is the order that matters.
        running = np.cumsum(block, axis=1)
        reached = running >= (ROLLOFF * total)[:, None]
        rolloff = freqs[np.argmax(reached, axis=1)]

        # Geometric over arithmetic mean: 1 for noise, near 0 for a tone.
        logs = np.log(block + 1e-10).mean(axis=1)
        flatness = np.exp(logs) / (block.mean(axis=1) + 1e-10)

        share = block / total[:, None]
        entropy = -(share * np.log(share + 1e-10)).sum(axis=1)
        entropy /= np.log(block.shape[1])

        rows.append(np.stack([centroid, rolloff, flatness, entropy], axis=1))

    if not rows:
        return np.zeros(COLOUR.stop - COLOUR.start, dtype=np.float32)

    return _middle_and_spread(np.concatenate(rows))
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_features.py -q`
Expected: 8 passed

- [ ] **Step 5: Counter-experiment**

Replace `flatness` with `np.ones_like(centroid)`.
`test_noise_is_flatter_than_a_tone` must fail. Put it back.

- [ ] **Step 6: Commit**

```bash
git add src/pypl2mp3/libs/features.py tests/test_features.py
git commit -m "feat: the colour facet, from the spectrogram already in hand"
```

---

### Task 5: Le rythme

**Files:**
- Modify: `src/pypl2mp3/libs/features.py`
- Test: `tests/test_features.py`

**Interfaces:**
- Produces: `onset_envelope(samples) -> np.ndarray`,
  `rhythm_of(samples) -> np.ndarray` (3 values: tempo in BPM, pulse
  clarity in [0, 1], onsets per second).

- [ ] **Step 1: Write the failing tests**

```python
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


@pytest.mark.parametrize("bpm", [90.0, 120.0, 150.0])
def test_the_tempo_of_a_click_track_is_the_tempo_we_built_it_with(bpm):
    from pypl2mp3.libs.features import rhythm_of

    found = rhythm_of(_clicks(bpm))[0]

    assert found == pytest.approx(bpm, rel=0.06), f"built {bpm}, read {found}"


def test_a_faster_track_reads_as_faster():
    """The ratio matters more than the absolute value: a tempo estimator
    that halves or doubles is a known failure, one that inverts the
    order of two tracks is useless."""

    from pypl2mp3.libs.features import rhythm_of

    slow = rhythm_of(_clicks(70.0))[0]
    fast = rhythm_of(_clicks(140.0))[0]

    assert fast > slow * 1.5, f"{slow:.0f} then {fast:.0f}"


def test_a_steady_pulse_is_clearer_than_noise():
    from pypl2mp3.libs.features import rhythm_of

    assert rhythm_of(_clicks(120.0))[1] > rhythm_of(_noise())[1] * 2


def test_the_rhythm_is_the_size_the_layout_says():
    from pypl2mp3.libs.features import RHYTHM, rhythm_of

    assert len(rhythm_of(_clicks(120.0))) == RHYTHM.stop - RHYTHM.start
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_features.py -q`
Expected: FAIL — `cannot import name 'rhythm_of'`

- [ ] **Step 3: Write the implementation**

```python
# The range a tempo is looked for in. Outside it the autocorrelation
# finds harmonics of the real pulse and reports them with confidence:
# 240 is 120 counted twice, and there is no way to tell them apart from
# the signal alone.
SLOWEST_BPM = 50.0
FASTEST_BPM = 200.0


def onset_envelope(samples: np.ndarray) -> np.ndarray:
    """How much the spectrum changes from frame to frame.

    Only increases count: energy appearing is an attack, energy leaving
    is a note ending, and a rhythm is made of the first kind.
    """

    flux = []
    previous = None

    for block in spectrogram(samples):
        joined = block if previous is None else np.vstack([previous, block])
        rising = np.diff(joined, axis=0).clip(min=0).sum(axis=1)
        flux.append(rising)
        previous = block[-1:]

    if not flux:
        return np.zeros(0, dtype=np.float32)

    envelope = np.concatenate(flux)

    # Against its own local level, so a quiet passage still has onsets
    # and a loud one does not drown the rest of the track.
    window = int(FRAMES_PER_SECOND)
    if window > 1 and len(envelope) > window:
        smooth = np.convolve(envelope, np.ones(window) / window, mode="same")
        envelope = (envelope - smooth).clip(min=0)

    return envelope.astype(np.float32)


def rhythm_of(samples: np.ndarray) -> np.ndarray:
    """Tempo, pulse clarity, and how often something is struck.

    Returns:
        3 values: BPM, a clarity in [0, 1], onsets per second.
    """

    envelope = onset_envelope(samples)
    if envelope.size < 4:
        return np.zeros(RHYTHM.stop - RHYTHM.start, dtype=np.float32)

    centred = envelope - envelope.mean()

    # Autocorrelation through the frequency domain: the direct form is
    # O(n²) and this envelope is twenty thousand points long.
    size = 1 << int(np.ceil(np.log2(len(centred) * 2)))
    spectrum = np.fft.rfft(centred, n=size)
    acf = np.fft.irfft(spectrum * np.conj(spectrum), n=size)[:len(centred)]

    if acf[0] <= 0:
        return np.zeros(RHYTHM.stop - RHYTHM.start, dtype=np.float32)

    shortest = max(1, int(FRAMES_PER_SECOND * 60.0 / FASTEST_BPM))
    longest = min(len(acf) - 1, int(FRAMES_PER_SECOND * 60.0 / SLOWEST_BPM))
    if longest <= shortest:
        return np.zeros(RHYTHM.stop - RHYTHM.start, dtype=np.float32)

    window = acf[shortest:longest + 1]
    lag = shortest + int(np.argmax(window))

    tempo = 60.0 * FRAMES_PER_SECOND / lag
    clarity = float(np.clip(acf[lag] / acf[0], 0.0, 1.0))

    # An onset is a local maximum standing above the track's own typical
    # rise; counting every non-zero frame would count the shoulders of
    # each attack as well as its peak.
    threshold = envelope.mean() + envelope.std()
    peaks = (envelope[1:-1] > threshold) & \
            (envelope[1:-1] >= envelope[:-2]) & \
            (envelope[1:-1] > envelope[2:])
    rate = float(peaks.sum()) / (len(envelope) / FRAMES_PER_SECOND)

    return np.array([tempo, clarity, rate], dtype=np.float32)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_features.py -q`
Expected: 14 passed

If a click-track tempo lands on half or double the built value, the fault
is the lag window, not the test: widen `SLOWEST_BPM`/`FASTEST_BPM` only
after checking `lag` by hand for one case.

- [ ] **Step 5: Counter-experiment**

Replace `lag = shortest + int(np.argmax(window))` with
`lag = shortest`. Every parametrised tempo test must fail. Put it back.

- [ ] **Step 6: Commit**

```bash
git add src/pypl2mp3/libs/features.py tests/test_features.py
git commit -m "feat: the rhythm facet, from an onset envelope"
```

---

### Task 6: La dynamique, et le vecteur entier

**Files:**
- Modify: `src/pypl2mp3/libs/features.py`
- Test: `tests/test_features.py`

**Interfaces:**
- Produces: `dynamics_of(samples) -> np.ndarray` (3 values),
  `features_of(samples) -> list[float]` (FEATURE_COUNT values),
  `features_for(song_path: Path) -> list[float]`

- [ ] **Step 1: Write the failing tests**

```python
def test_a_compressed_signal_has_a_lower_crest_than_a_peaky_one():
    """Crest factor is production, not composition — and production is
    exactly what makes two tracks of the same genre sound like they
    belong together."""

    from pypl2mp3.libs.features import dynamics_of

    steady = dynamics_of(_sine(440, gain=0.5))[1]

    peaky = np.zeros(int(SAMPLE_RATE * 4), dtype=np.float32)
    peaky[::5000] = 0.9

    assert dynamics_of(peaky)[1] > steady + 6.0


def test_a_louder_signal_reads_as_louder():
    from pypl2mp3.libs.features import dynamics_of

    assert dynamics_of(_sine(440, gain=0.8))[0] > \
           dynamics_of(_sine(440, gain=0.1))[0]


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


def test_a_song_is_analysed_once_and_read_back_after(tmp_path, monkeypatch):
    """The second call must not decode. That is the difference between
    opening the inspector and waiting a second for it."""

    from pypl2mp3.libs import features as mod

    path = tmp_path / "ARTIST - Title [aaaaaaaaaaa].mp3"
    path.write_bytes(b"\xff\xfb\x90\xc0" + b"\x00" * 413)

    decodes = []
    monkeypatch.setattr(mod, "extract_samples",
                        lambda p: decodes.append(p) or _clicks(120.0))

    first = mod.features_for(path)
    second = mod.features_for(path)

    assert len(decodes) == 1, f"decoded {len(decodes)} times"
    assert second == pytest.approx(first, rel=1e-5)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_features.py -q`
Expected: FAIL — `cannot import name 'dynamics_of'`

- [ ] **Step 3: Write the implementation**

```python
# How long a "short-term" loudness lasts. 400 ms is the window EBU R128
# uses for the same purpose, and it is roughly the length of a syllable.
SHORT_TERM = 0.4


def dynamics_of(samples: np.ndarray) -> np.ndarray:
    """Level, crest factor, and how much the level moves.

    All three in decibels, so a doubling is the same distance wherever
    it happens — which is what makes them comparable once standardised.

    Returns:
        3 values: RMS level (dBFS), crest factor (dB), spread of the
        short-term levels (dB).
    """

    if samples.size == 0:
        return np.zeros(DYNAMICS.stop - DYNAMICS.start, dtype=np.float32)

    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    peak = float(np.abs(samples).max())

    level = 20.0 * math.log10(rms + 1e-10)
    crest = 20.0 * math.log10((peak + 1e-10) / (rms + 1e-10))

    step = int(SAMPLE_RATE * SHORT_TERM)
    usable = len(samples) // step * step
    if usable >= step * 4:
        blocks = samples[:usable].astype(np.float64).reshape(-1, step)
        short = 10.0 * np.log10((blocks ** 2).mean(axis=1) + 1e-10)
        low, high = np.percentile(short, [10, 95])
        spread = float(high - low)
    else:
        # Too short to have a range. Zero says "no variation observed",
        # which is true, rather than a number invented from four blocks.
        spread = 0.0

    return np.array([level, crest, spread], dtype=np.float32)


def features_of(samples: np.ndarray) -> list[float]:
    """The whole vector for one decoded signal.

    Returns:
        FEATURE_COUNT finite numbers, laid out as TIMBRE, RHYTHM,
        COLOUR, DYNAMICS.
    """

    whole = np.zeros(FEATURE_COUNT, dtype=np.float32)
    whole[TIMBRE] = timbre_of(samples)
    whole[RHYTHM] = rhythm_of(samples)
    whole[COLOUR] = colour_of(samples)
    whole[DYNAMICS] = dynamics_of(samples)

    # A silent or pathological file can produce a log of zero somewhere
    # upstream. One NaN poisons every distance this song takes part in,
    # and poisons them silently, because comparisons against NaN are
    # false rather than wrong.
    return [float(v) if math.isfinite(float(v)) else 0.0 for v in whole]


def features_for(song_path: Path) -> list[float]:
    """The vector of one song, computed once and kept in the file.

    Args:
        song_path: the MP3 to describe.

    Returns:
        FEATURE_COUNT numbers.

    Raises:
        FeatureError: if the file carries no vector and cannot be
            decoded.
    """

    try:
        stored = read_features(mutagen.mp3.MP3(song_path))
    except (mutagen.MutagenError, OSError):
        # A file whose tags cannot be read is not this function's
        # verdict to give. Let the decoder be the judge.
        stored = None

    if stored is not None:
        return stored

    values = features_of(extract_samples(song_path))

    try:
        store_features(song_path, values)
    except Exception:
        # A read-only file, a full disk, a file being written by another
        # process: none of that is a reason to refuse the vector we
        # already hold. It gets recomputed next time.
        pass

    return values
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_features.py -q`
Expected: 19 passed

- [ ] **Step 5: Counter-experiment**

Swap `whole[COLOUR]` and `whole[DYNAMICS]`.
`test_every_facet_lands_in_its_own_slice` must fail. Put it back.

- [ ] **Step 6: Measure the real cost, once**

```bash
.venv/bin/python -c "
import time, glob
from pypl2mp3.libs.features import extract_samples, features_of
path = sorted(glob.glob('/Users/thierry/Desktop/playlists/*/*.mp3'))[0]
start = time.time(); samples = extract_samples(path); mid = time.time()
features_of(samples); end = time.time()
print(f'decode {mid-start:.2f}s  features {end-mid:.2f}s  total {end-start:.2f}s')
"
```

Record it: `cairn note PYPL2MP3-2 "one song costs …" --kind finding`.
If the total exceeds 3 s, stop and say so before the bulk pass — 944
songs at 3 s is 47 minutes, which is a different conversation from 7.

- [ ] **Step 7: Commit**

```bash
git add src/pypl2mp3/libs/features.py tests/test_features.py
git commit -m "feat: the dynamics facet, and the whole forty-number vector"
```

---

### Task 7: Les distances

**Files:**
- Create: `src/pypl2mp3/services/similarity.py`
- Test: `tests/test_similarity.py`

**Interfaces:**
- Consumes: `FEATURE_COUNT`, `TIMBRE`, `RHYTHM`, `COLOUR`, `DYNAMICS`
  from `libs.features`.
- Produces:
  - `WEIGHTS: dict[str, float]`
  - `Neighbour` dataclass: `key: str`, `distance: float`,
    `percentile: float`, `facet: str`
  - `standardise(vectors: np.ndarray) -> np.ndarray`
  - `facet_distances(vectors: np.ndarray) -> dict[str, np.ndarray]`
  - `Space.build(entries: list[tuple[str, str, list[float]]]) -> Space`
    where each entry is `(key, youtube_id, vector)`
  - `Space.neighbours(key: str, count: int = 5, among: set[str] | None = None) -> list[Neighbour]`

- [ ] **Step 1: Write the failing tests**

```python
"""Distances between songs, driven on vectors we write by hand.

No audio here at all. What this module gets right or wrong is the
arithmetic of comparing forty numbers, and the extractor's tests already
say the forty numbers mean something.
"""

import numpy as np
import pytest

from pypl2mp3.libs.features import COLOUR, DYNAMICS, FEATURE_COUNT, RHYTHM, TIMBRE
from pypl2mp3.services.similarity import Space, WEIGHTS, standardise


def _vector(**facets) -> list[float]:
    """A vector that is zero everywhere except where you say."""

    out = np.zeros(FEATURE_COUNT, dtype=np.float32)
    for name, value in facets.items():
        out[{"timbre": TIMBRE, "rhythm": RHYTHM,
             "colour": COLOUR, "dynamics": DYNAMICS}[name]] = value
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

    # Same per-facet gap, so the ratio must be the ratio of the weights
    # and nothing else.
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
        ("a", "v1", _vector(timbre=0.0)),
        ("far", "v2", _vector(timbre=9.0)),
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
    in the selection does, and it is the same number whatever the units
    of the features happen to be."""

    entries = [(f"s{i}", f"v{i}", _vector(timbre=float(i))) for i in range(10)]
    space = Space.build(entries)

    nearest = space.neighbours("s0", count=1)[0]

    assert 0.0 <= nearest.percentile <= 100.0
    assert nearest.percentile > 80.0


def test_a_space_with_one_song_has_no_neighbours():
    space = Space.build([("alone", "v1", _vector(timbre=1.0))])

    assert space.neighbours("alone") == []


def test_a_key_nobody_knows_has_no_neighbours():
    space = Space.build([("a", "v1", _vector(timbre=1.0))])

    assert space.neighbours("ghost") == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_similarity.py -q`
Expected: FAIL — `No module named 'pypl2mp3.services.similarity'`

- [ ] **Step 3: Write the implementation**

```python
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

Nothing here is stored. The standardisation belongs to a selection, and
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

# The timbre leads because "it sounds the same" means the timbre first.
# These are a starting point to be checked against the genre agreement
# `scripts/measure_similarity.py` reports — not tuned to maximise it,
# which would turn this into a guesser of Shazam's labels and would put
# an acoustic cover far from the electronic original it covers.
WEIGHTS = {
    "timbre": 0.45,
    "colour": 0.25,
    "rhythm": 0.20,
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
        The same shape, standardised down each column.
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
        vectors: (songs, FEATURE_COUNT), already standardised.

    Returns:
        A (songs, songs) matrix for each facet name.
    """

    out = {}
    for name, block in FACETS.items():
        part = vectors[:, block]
        # The expansion of (a - b)² so the whole matrix is three matrix
        # operations rather than a Python loop over 890 000 pairs.
        square = (part ** 2).sum(axis=1)
        gram = part @ part.T
        spread = square[:, None] + square[None, :] - 2 * gram
        # Divided by the facet's width so the four numbers are
        # comparable: this is a distance per dimension, not a total.
        out[name] = np.sqrt(np.clip(spread, 0, None) / part.shape[1])

    return out


class Space:
    """A selection of songs, and the distances between them."""

    def __init__(self, keys, videos, totals, facets, pairs):
        self._keys = keys
        self._videos = videos
        self._at = {key: at for at, key in enumerate(keys)}
        self._totals = totals
        self._facets = facets
        self._pairs = pairs

    @classmethod
    def build(cls, entries) -> "Space":
        """Compute every distance in a selection.

        Args:
            entries: (key, youtube_id, vector) for each song that has
                one. Songs without a vector are simply absent, which is
                what gives them no neighbours and sends them to the end
                of a course.

        Returns:
            A Space. 944 songs cost about ten milliseconds.
        """

        keys = [key for key, _, _ in entries]
        videos = [video for _, video, _ in entries]

        if not keys:
            return cls([], [], np.zeros((0, 0)), {}, np.zeros(0))

        raw = np.array([vector for _, _, vector in entries], dtype=np.float64)
        if raw.shape[1] != FEATURE_COUNT:
            raise ValueError(f"a vector is {FEATURE_COUNT} numbers")

        facets = facet_distances(standardise(raw))
        totals = sum(WEIGHTS[name] * matrix for name, matrix in facets.items())

        # Every distance in the selection, once, so a percentile is a
        # rank in this library rather than a number out of the air.
        above = np.triu_indices(len(keys), k=1)
        pairs = np.sort(totals[above]) if len(keys) > 1 else np.zeros(0)

        return cls(keys, videos, totals, facets, pairs)

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

        order = np.argsort(row, kind="stable")
        found = []

        for there in order:
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
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_similarity.py -q`
Expected: 11 passed

- [ ] **Step 5: Counter-experiments, three of them**

1. Remove the `self._videos[there] == mine` guard →
   `test_the_same_recording_in_two_playlists_is_never_a_neighbour` fails.
2. Drop `/ part.shape[1]` in `facet_distances` →
   `test_the_facet_with_more_dimensions_does_not_win_by_counting` fails.
3. Replace `spread[spread < 1e-9] = 1.0` with nothing →
   `test_a_column_that_never_moves_does_not_divide_by_zero` fails.

Put all three back.

- [ ] **Step 6: Commit**

```bash
git add src/pypl2mp3/services/similarity.py tests/test_similarity.py
git commit -m "feat: distances computed facet by facet, then weighted"
```

---

### Task 8: Le calcul à l'import, et le job de rattrapage

**Files:**
- Modify: `src/pypl2mp3/services/import_playlist.py:380-388`
- Modify: `src/pypl2mp3/web/app.py` (a route beside the check job)
- Test: `tests/test_features_job.py`

**Interfaces:**
- Consumes: `features_for` from `libs.features`.
- Produces: `POST /features/analyse` → a job named `features`, whose
  result is `{"analysed": int, "failed": int, "total": int}`.

- [ ] **Step 1: Write the failing tests**

```python
"""Filling the library with vectors: at import, and in bulk."""

from pathlib import Path

import httpx
import pytest
from mutagen.id3 import ID3, TXXX

from pypl2mp3.libs.features import FEATURE_COUNT, read_features
from pypl2mp3.web.app import create_app

PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"
_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _song(repo: Path, vid: str) -> Path:
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"ARTIST - Title [{vid}].mp3"
    path.write_bytes(_MP3_FRAME * 8)
    frames = ID3()
    frames.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
    frames.save(path)
    return path


async def test_the_bulk_job_writes_a_vector_into_every_song(tmp_path, monkeypatch):
    from pypl2mp3.web import app as web

    for vid in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
        _song(tmp_path, vid)

    # The extractor has its own tests; this one is about the job.
    monkeypatch.setattr(
        web, "features_for",
        lambda path: [1.0] * FEATURE_COUNT,
    )

    application = create_app(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        started = await client.post("/features/analyse")
        assert started.status_code in (200, 202)

        for _ in range(100):
            state = (await client.get("/jobs/features")).json()
            if state["state"] in ("succeeded", "failed"):
                break
            await asyncio.sleep(0.05)

    assert state["state"] == "succeeded", state
    assert state["result"]["analysed"] == 2


async def test_a_song_that_cannot_be_analysed_does_not_fail_the_run(tmp_path, monkeypatch):
    """One unreadable file out of 944 must not cost the other 943."""

    from pypl2mp3.libs.features import FeatureError
    from pypl2mp3.web import app as web

    _song(tmp_path, "aaaaaaaaaaa")
    _song(tmp_path, "bbbbbbbbbbb")

    def refuse(path):
        if "bbbbbbbbbbb" in path.name:
            raise FeatureError("nope")
        return [1.0] * FEATURE_COUNT

    monkeypatch.setattr(web, "features_for", refuse)

    application = create_app(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        await client.post("/features/analyse")
        for _ in range(100):
            state = (await client.get("/jobs/features")).json()
            if state["state"] in ("succeeded", "failed"):
                break
            await asyncio.sleep(0.05)

    assert state["state"] == "succeeded", state
    assert state["result"] == {"analysed": 1, "failed": 1, "total": 2}


def test_the_import_asks_for_a_vector_without_depending_on_one():
    """Best effort, exactly like the waveform beside it: a vector that
    cannot be computed is not a failed import."""

    source = Path("src/pypl2mp3/services/import_playlist.py").read_text()

    assert "features_for" in source, "the import never analyses anything"

    block = source[source.index("def _store_waveform"):]
    assert "except Exception" in block
```

Adjust the last test to whatever the helper beside `peaks_for` is
actually called — read `import_playlist.py:375-390` first and name it
exactly.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_features_job.py -q`
Expected: FAIL — 404 on `/features/analyse`

- [ ] **Step 3: The import hook**

In `src/pypl2mp3/services/import_playlist.py`, beside the existing
waveform helper:

```python
from pypl2mp3.libs.features import features_for
```

```python
def _store_features(song_path: Path) -> None:
    """Describe the song while it is fresh on disk.

    Best effort, like the waveform above: a vector that cannot be
    computed is not a failed import, and the bulk job picks it up later.
    """

    try:
        features_for(song_path)
    except Exception:
        pass
```

Call it immediately after the existing waveform call, on the same path.

- [ ] **Step 4: The bulk job**

In `src/pypl2mp3/web/app.py`, import `features_for` at module level (the
tests monkeypatch it there, which is why it is imported into the module
rather than called through its package), and add beside `start_check`:

```python
    @app.post("/features/analyse")
    async def start_analysis(request: Request):
        """Give every song in the repository a vector.

        One job for the whole library rather than one per playlist: the
        map and the neighbours span everything, and a half-analysed
        library is exactly what produces a map with holes in it.
        """

        loop = asyncio.get_running_loop()
        repository_path = app.state.repository_path

        async def work(job) -> dict:
            progress = WebProgress(app.state.jobs, job.job_id, loop)
            songs = sorted(Path(repository_path).glob("*/*.mp3"))

            def analyse() -> dict:
                analysed = failed = 0
                for at, song in enumerate(songs, 1):
                    try:
                        features_for(song)
                        analysed += 1
                    except Exception:
                        # One unreadable file must not cost the other
                        # nine hundred and forty-three.
                        failed += 1
                    progress.item_done(song.name, f"{at}/{len(songs)}")
                return {"analysed": analysed, "failed": failed,
                        "total": len(songs)}

            # In a worker thread: ffmpeg and numpy both block, and the
            # event loop has a player to keep answering.
            return await asyncio.to_thread(analyse)

        try:
            job = app.state.jobs.start("features", work)
        except JobAlreadyRunning:
            job = app.state.jobs.get("features")

        return {"job": job.job_id}
```

Read `start_check` first and copy its exact shape: the progress port's
method names, the `JobAlreadyRunning` handling, and whether it answers
with JSON or a fragment. **Do not invent a progress method** — use the
ones `WebProgress` already exposes.

- [ ] **Step 5: Run to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_features_job.py -q`
Expected: 3 passed

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: everything that passed before still passes.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: analyse songs at import, and a job to catch up the library"
```

---

### Task 9: L'instrument de mesure

**Files:**
- Create: `scripts/measure_similarity.py`
- Test: `tests/test_measure_script.py`

**Interfaces:**
- Consumes: `Space`, `WEIGHTS` from `services.similarity`;
  `read_features` from `libs.features`.
- Produces: a command printing the genre agreement rate.

- [ ] **Step 1: Write the failing test**

```python
"""The instrument that judges the features.

Loaded from its path, as tests/test_backfill_script.py does: it lives in
scripts/, outside the package.
"""

import importlib.util
from pathlib import Path

import pytest
from mutagen.id3 import ID3, TCON, TXXX

SCRIPT = Path("scripts/measure_similarity.py")
_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _script():
    spec = importlib.util.spec_from_file_location("measure_similarity", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_chance_rate_is_the_sum_of_squared_proportions():
    """Not the weight of the largest class, which is the mistake this
    number exists to avoid: with Electronic at 20% and 48 other genres,
    the two answers are 20% and 12%, and only one of them is what two
    songs drawn at random actually do."""

    chance = _script().chance_rate({"a": 1, "b": 1})

    assert chance == pytest.approx(0.5)


def test_a_library_where_neighbours_share_a_genre_scores_high(tmp_path):
    """Two tight clusters, each one genre. A measure that cannot see
    this cannot see anything."""

    module = _script()
    folder = tmp_path / "Owner - Alpha [PL0000000000000000000000000000001]"
    folder.mkdir(parents=True)

    from pypl2mp3.libs.features import FEATURE_COUNT, store_features

    for at in range(10):
        vid = f"{at:011d}"
        path = folder / f"ARTIST - Song {at} [{vid}].mp3"
        path.write_bytes(_MP3_FRAME * 8)
        frames = ID3()
        frames.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
        frames.add(TCON(encoding=3, text="Techno" if at < 5 else "Folk"))
        frames.save(path)
        # Two clusters far apart on every dimension.
        store_features(path, [0.0 if at < 5 else 100.0] * FEATURE_COUNT)

    report = module.measure(tmp_path, count=3)

    assert report["scored"] == 10
    assert report["agreement"] == pytest.approx(1.0)


def test_songs_without_a_genre_are_not_scored(tmp_path):
    """124 of the 944 have none. Counting them as disagreements would
    make the number say the features are 13% worse than they are."""

    module = _script()
    folder = tmp_path / "Owner - Alpha [PL0000000000000000000000000000001]"
    folder.mkdir(parents=True)

    from pypl2mp3.libs.features import FEATURE_COUNT, store_features

    for at in range(4):
        vid = f"{at:011d}"
        path = folder / f"ARTIST - Song {at} [{vid}].mp3"
        path.write_bytes(_MP3_FRAME * 8)
        frames = ID3()
        frames.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
        if at < 2:
            frames.add(TCON(encoding=3, text="Techno"))
        frames.save(path)
        store_features(path, [float(at)] * FEATURE_COUNT)

    assert module.measure(tmp_path, count=1)["scored"] == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_measure_script.py -q`
Expected: FAIL — the script does not exist

- [ ] **Step 3: Write the script**

```python
"""Does the feature vector know anything about music?

The ruler is the artist. For each song, how many of its five nearest
neighbours are by the same one? Two songs drawn at random are by the
same artist 0.7% of the time — the sum of the squared proportions — so
a vector that knows nothing scores that, and the shipped one scores
11.6 times it.

The genre was the first ruler and it was the wrong one. It is still
reported, because it colours the map and a rise would be good news, but
the same vectors score 1.4x on genre and 11.6x on artist, measured on
the same 352 songs. "Alternative" and "Pop" are commercial categories,
not acoustic ones: two Pop songs from 1985 and 2020 share a label and
nothing else.

Read-only. It writes nothing, analyses nothing, and skips any song that
has no vector yet: run the bulk analysis first.

This measure checks the weights; it must not be used to choose them.
Optimising agreement with a label turns the thing into a guesser of
labels, and an acoustic cover would stop being the neighbour of the
electronic original it covers — which is the kind of link the map exists
to show.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

import mutagen
import mutagen.mp3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pypl2mp3.libs.features import read_features  # noqa: E402
from pypl2mp3.libs.utils import get_song_id_from_filename  # noqa: E402
from pypl2mp3.services.similarity import FACETS, Space, WEIGHTS  # noqa: E402


def chance_rate(counts: dict) -> float:
    """What two songs drawn at random do.

    The sum of squared proportions — not the weight of the largest
    class, which answers a different question and flatters the result.
    """

    total = sum(counts.values())
    if total == 0:
        return 0.0

    return sum((n / total) ** 2 for n in counts.values())


def collect(repository: Path) -> list:
    """Every song that has both a vector and a genre."""

    found = []
    for song in sorted(Path(repository).glob("*/*.mp3")):
        video = get_song_id_from_filename(song.name)
        if not video:
            continue
        try:
            mp3 = mutagen.mp3.MP3(song)
        except (mutagen.MutagenError, OSError):
            continue

        vector = read_features(mp3)
        if vector is None:
            continue

        genre = str(mp3.tags["TCON"]) if mp3.tags and "TCON" in mp3.tags else ""
        found.append((str(song), video, vector, genre))

    return found


def measure(repository: Path, count: int = 5) -> dict:
    """The agreement rate, overall and per facet.

    Returns:
        scored, agreement, chance, by_facet, analysed, no_genre.
    """

    songs = collect(repository)
    space = Space.build([(key, video, vector)
                         for key, video, vector, _ in songs])
    genres = {key: genre for key, _, _, genre in songs}

    counts = Counter(g for g in genres.values() if g)

    hits = shots = 0
    for key, genre in genres.items():
        if not genre:
            continue
        neighbours = space.neighbours(key, count=count)
        if not neighbours:
            continue
        shots += 1
        hits += sum(1 for n in neighbours if genres.get(n.key) == genre) \
            / len(neighbours)

    # Which facet does the work: the same question asked with one weight
    # set to one and the rest to zero.
    by_facet = {}
    for name in FACETS:
        alone = {f: (1.0 if f == name else 0.0) for f in FACETS}
        by_facet[name] = _agreement_with(songs, genres, alone, count)

    return {
        "analysed": len(songs),
        "no_genre": sum(1 for g in genres.values() if not g),
        "scored": shots,
        "agreement": hits / shots if shots else 0.0,
        "chance": chance_rate(counts),
        "by_facet": by_facet,
    }


def _agreement_with(songs, genres, weights, count) -> float:
    """The same measure under a different weighting."""

    from pypl2mp3.services import similarity

    was = dict(similarity.WEIGHTS)
    similarity.WEIGHTS.update(weights)
    try:
        space = Space.build([(k, v, vec) for k, v, vec, _ in songs])
        hits = shots = 0
        for key, genre in genres.items():
            if not genre:
                continue
            found = space.neighbours(key, count=count)
            if not found:
                continue
            shots += 1
            hits += sum(1 for n in found if genres.get(n.key) == genre) \
                / len(found)
        return hits / shots if shots else 0.0
    finally:
        similarity.WEIGHTS.clear()
        similarity.WEIGHTS.update(was)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    parser.add_argument("--count", type=int, default=5,
                        help="how many neighbours to score (default 5)")
    args = parser.parse_args()

    report = measure(args.repository, args.count)

    print(f"analysed      {report['analysed']}")
    print(f"without genre {report['no_genre']}")
    print(f"scored        {report['scored']}")
    print()
    print(f"chance        {report['chance'] * 100:5.1f}%")
    print(f"agreement     {report['agreement'] * 100:5.1f}%"
          f"   ({report['agreement'] / report['chance']:.1f}x)"
          if report["chance"] else "")
    print()
    print("each facet on its own:")
    for name, rate in sorted(report["by_facet"].items(),
                             key=lambda item: -item[1]):
        print(f"  {name:9} {rate * 100:5.1f}%")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_measure_script.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/measure_similarity.py tests/test_measure_script.py
git commit -m "feat: a script that asks whether the features know any music"
```

---

### Task 10: La passe réelle, et le verdict

**Files:** none. This task produces a number and a decision.

- [ ] **Step 1: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: all green. Record it:
`cairn run PYPL2MP3-2 ".venv/bin/python -m pytest -q" --status passed --exit-code 0`

- [ ] **Step 2: Analyse the library**

Restart the server, open the console, and post the job:

```bash
curl -s -X POST http://127.0.0.1:8895/features/analyse
```

Expect roughly seven minutes. While it runs, check that the player still
answers — the job must be in a worker thread, and a console that freezes
means it is not.

- [ ] **Step 3: Verify the library actually carries vectors**

```bash
.venv/bin/python -c "
from pathlib import Path
import mutagen.mp3
from pypl2mp3.libs.features import read_features
songs = list(Path('/Users/thierry/Desktop/playlists').glob('*/*.mp3'))
have = sum(1 for s in songs if read_features(mutagen.mp3.MP3(s)) is not None)
print(f'{have} / {len(songs)}')
"
```

- [ ] **Step 4: Measure**

```bash
.venv/bin/python scripts/measure_similarity.py ~/Desktop/playlists
```

- [ ] **Step 5: Record the verdict and stop**

```bash
cairn note PYPL2MP3-2 "artist agreement X% against a chance of 0.7% (Nx); genre Y%. Per facet: …" --kind finding
cairn checkpoint PYPL2MP3-2 --summary "…"
```

**This gate was already walked, at the task-3 checkpoint and again
after task 6, on a 352-song sample.** What it found:

- artist agreement **11.6x** chance — the features find acoustic likeness
- genre agreement **1.4x** chance — and no weighting moves it; a control
  of random vectors scores exactly chance, so the measurement is sound
- therefore the genre label, not the vector, was the weak thing

So the stage continues rather than reaching for ONNX. What remains here
is to confirm the same numbers on all 944 rather than on a sample:

- **≥ 5x on artist** — as expected. PYPL2MP3-3 and PYPL2MP3-4 proceed.
- **below 5x** — something differs between the sample and the whole
  library. Find out what before building on it.

- [ ] **Step 6: Close the stage**

```bash
cairn done PYPL2MP3-2 --resolution "…the number, and what it decided…" --kind fixed
```

---

## Self-review

**Spec coverage.** Every section 1 and 2 requirement maps to a task:
the four facets (3, 4, 5, 6), the raw-only frame (1), the versioned
owner (1), computing at import and in bulk (8), per-facet distances and
weights (7), the duplicate rule and the selection confinement (7), the
measurement script and its 12,1 % / 36 % (9, 10). Sections 3 and 4 are
PYPL2MP3-3 and PYPL2MP3-4 and are deliberately absent.

**One documented deviation:** colour and dynamics are computed from the
decode this plan already performs rather than from `aspectralstats` and
`ebur128`. Reason and consequence are at the top of this document; the
spec must be amended to match before the stage is closed.

**Types.** `features_for` returns `list[float]`; `Space.build` takes
`(key, youtube_id, vector)` triples and nothing else; `Neighbour` carries
`key`, `distance`, `percentile`, `facet` and is used with those four
names in tasks 7 and 9 alike. `standardise` and `facet_distances` take
and return `np.ndarray`.

**Two things the implementer must read before writing**, flagged in
place rather than guessed here: the exact name of the waveform helper in
`import_playlist.py` (task 8, step 1) and the exact shape of
`start_check` and of `WebProgress` (task 8, step 4).
