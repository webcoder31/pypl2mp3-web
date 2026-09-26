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


def test_a_vector_of_the_wrong_size_is_refused_at_the_door():
    """Refused where it is cheap to see, rather than written and found
    unreadable later."""

    with pytest.raises(ValueError):
        pack_features([1.0] * (FEATURE_COUNT - 1))


def test_something_that_is_not_a_number_is_refused():
    """NaN and infinity survive float32 and poison every distance they
    take part in — silently, because comparisons against NaN are false."""

    with pytest.raises(ValueError):
        pack_features([float("nan")] + [0.0] * (FEATURE_COUNT - 1))


def test_the_bytes_are_the_width_the_reader_checks():
    """The length test above is the only thing standing between a
    truncated write and forty numbers read out of thirty-seven."""

    data = pack_features([0.0] * FEATURE_COUNT)

    assert len(data) == FEATURE_COUNT * 4
    assert unpack_features(data) == [0.0] * FEATURE_COUNT
