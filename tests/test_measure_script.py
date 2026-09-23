"""The instrument that judges the features.

Loaded from its path, as tests/test_backfill_script.py does: it lives in
scripts/, outside the package.
"""

import importlib.util
from pathlib import Path

import pytest
from mutagen.id3 import ID3, TCON, TXXX

from pypl2mp3.libs.features import FEATURE_COUNT, store_features

SCRIPT = Path("scripts/measure_similarity.py")
_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


def _script():
    spec = importlib.util.spec_from_file_location("measure_similarity", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def _song(folder: Path, artist: str, at: int, vector, genre=""):
    vid = f"{at:011d}"
    path = folder / f"{artist} - Song {at} [{vid}].mp3"
    path.write_bytes(_MP3_FRAME * 8)

    frames = ID3()
    frames.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
    if genre:
        frames.add(TCON(encoding=3, text=genre))
    frames.save(path)

    store_features(path, [float(v) for v in vector])

    return path


def _library(tmp_path: Path) -> Path:
    folder = tmp_path / "Owner - Alpha [PL0000000000000000000000000000001]"
    folder.mkdir(parents=True)

    return folder


def test_the_chance_rate_is_the_sum_of_squared_proportions():
    """Not the weight of the largest class, which is the mistake this
    number exists to avoid: with one label at 20% and 48 others, the two
    answers are 20% and 12%, and only one of them is what two songs
    drawn at random actually do."""

    assert _script().chance_rate({"a": 1, "b": 1}) == pytest.approx(0.5)
    assert _script().chance_rate({}) == 0.0


def test_a_library_where_neighbours_share_an_artist_scores_high(tmp_path):
    """Two tight clusters, one artist each. A measure that cannot see
    this cannot see anything."""

    folder = _library(tmp_path)
    for at in range(10):
        near = "ONE" if at < 5 else "TWO"
        _song(folder, near, at, [0.0 if at < 5 else 100.0] * FEATURE_COUNT)

    report = _script().measure(tmp_path, count=3)

    assert report["analysed"] == 10
    assert report["artist"] == pytest.approx(1.0)


def test_a_song_whose_label_is_unique_is_not_scored(tmp_path):
    """It cannot succeed — there is no second song to find — and
    counting it as a failure would say the features are worse than they
    are."""

    folder = _library(tmp_path)
    for at in range(4):
        # Four artists, one song each: nothing is scoreable.
        _song(folder, f"ARTIST{at}", at, [float(at)] * FEATURE_COUNT)

    assert _script().measure(tmp_path, count=1)["artist"] == 0.0


def test_songs_without_a_genre_are_counted_but_not_scored(tmp_path):
    """124 of the 944 have none. Counting them as disagreements would
    make the number say the features are worse than they are."""

    folder = _library(tmp_path)
    for at in range(4):
        _song(folder, "SAME", at, [float(at)] * FEATURE_COUNT,
              genre="Techno" if at < 2 else "")

    report = _script().measure(tmp_path, count=1)

    assert report["analysed"] == 4
    assert report["no_genre"] == 2


def test_a_song_with_no_vector_is_skipped(tmp_path):
    """The script judges the features; a song nobody analysed has none
    to judge, and inventing a zero for it would drag every distance in
    the library towards it."""

    folder = _library(tmp_path)
    _song(folder, "SAME", 0, [1.0] * FEATURE_COUNT)
    _song(folder, "SAME", 1, [1.0] * FEATURE_COUNT)

    bare = folder / "SAME - Song 9 [00000000009].mp3"
    bare.write_bytes(_MP3_FRAME * 8)
    frames = ID3()
    frames.add(TXXX(encoding=3, desc="YouTube ID", text="00000000009"))
    frames.save(bare)

    assert _script().measure(tmp_path)["analysed"] == 2


def test_each_facet_is_reported_on_its_own(tmp_path, monkeypatch):
    """Which axis does the work is the thing that would decide a
    re-weighting, so it has to be visible rather than inferred."""

    from pypl2mp3.services.similarity import FACETS, WEIGHTS

    folder = _library(tmp_path)
    for at in range(6):
        _song(folder, "ONE" if at < 3 else "TWO", at,
              [float(at)] * FEATURE_COUNT)

    # A weighting of our own, put there by monkeypatch so it is undone
    # whatever happens. Reading the current one instead made this test
    # pass for the wrong reason: every run of `measure` ends on the same
    # weighting, so once an earlier test had left the dict in that state
    # a later one compared it against itself. It only caught anything
    # when it happened to run first.
    mine = {"timbre": 0.4, "colour": 0.3, "rhythm": 0.2, "dynamics": 0.1}
    for facet, weight in mine.items():
        monkeypatch.setitem(WEIGHTS, facet, weight)

    report = _script().measure(tmp_path, count=2)

    assert set(report["by_facet"]) == set(FACETS)
    # And the weights are put back: a module-level dict left mutated
    # would make every later measurement answer a question nobody asked.
    assert WEIGHTS == mine
