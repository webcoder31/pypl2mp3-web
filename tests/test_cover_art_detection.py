"""Finding the cover picture in a file somebody else tagged.

An APIC frame carries two things that are easy to confuse. `type` is a
number the ID3 specification defines — 3 is the front cover — and `desc`
is free text invented by whoever wrote the frame. Mutagen indexes frames
by the text, so asking for `tags["APIC:Cover art"]` asks for the picture
*called* that, and raises for a picture called anything else.

This program writes "Cover art". A version of it that predates the
repository wrote "Stored cover art": 105 songs in one 944-song library
carry that label, and every one of them was counted as having no cover.
`list-junks` reports a song with no cover as needing attention, so they
were all flagged while carrying a perfectly good picture.
"""

from pathlib import Path

import pytest
from mutagen.id3 import ID3, APIC, TXXX
from mutagen.mp3 import MP3

from pypl2mp3.libs.song import SongModel

_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413
PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"

# Enough of a JPEG for mutagen to carry; nothing here decodes it.
_JPEG = bytes.fromhex("ffd8ffe000104a464946000101" + "00" * 40 + "ffd9")


def _song_with_picture(repo: Path, *, desc: str, kind: int = 3):
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "IAMX - Kiss [aaaaaaaaaaa].mp3"
    path.write_bytes(_FRAME * 8)

    tags = ID3()
    tags.add(TXXX(encoding=3, desc="YouTube ID", text="aaaaaaaaaaa"))
    tags.add(APIC(encoding=3, desc=desc, mime="image/jpg", type=kind,
                  data=_JPEG))
    tags.save(path, v1=0, v2_version=3)

    return path


@pytest.mark.parametrize(
    "label",
    [
        "Cover art",          # what this program writes
        "Stored cover art",   # what the version before the repository wrote
        "",                   # what several taggers write
        "front",              # and anything else at all
    ],
)
def test_a_front_cover_is_found_whatever_it_is_called(tmp_path, label):
    """The label is a nickname; the type is the fact."""

    path = _song_with_picture(tmp_path, desc=label)

    assert SongModel(path).has_cover_art is True, (
        f"a front cover labelled {label!r} was not found"
    )


def test_a_picture_that_is_not_a_front_cover_does_not_count(tmp_path):
    """Type 3 is the front cover. An artist photo (8) or a back cover (4)
    is a picture, but not the one the panel draws — reading the label
    would have accepted either as long as the text matched."""

    for kind in (4, 8):
        path = _song_with_picture(tmp_path, desc="Cover art", kind=kind)

        assert SongModel(path).has_cover_art is False, (
            f"a picture of type {kind} was taken for a front cover"
        )


def test_a_file_with_no_picture_at_all(tmp_path):
    folder = tmp_path / PLAYLIST
    folder.mkdir(parents=True)
    path = folder / "IAMX - Sorrow [bbbbbbbbbbb].mp3"
    path.write_bytes(_FRAME * 8)
    tags = ID3()
    tags.add(TXXX(encoding=3, desc="YouTube ID", text="bbbbbbbbbbb"))
    tags.save(path, v1=0, v2_version=3)

    assert SongModel(path).has_cover_art is False


def test_the_lookup_no_longer_goes_through_the_label(tmp_path):
    """The old form raised a KeyError for every one of those 105 songs,
    and a bare `except:` turned it into "no cover art" — which is why
    nothing ever reported it."""

    source = Path("src/pypl2mp3/libs/song.py").read_text()
    lookups = [
        line for line in source.splitlines()
        if 'tags["APIC:Cover art"]' in line and not line.strip().startswith("#")
        and "Mutagen indexes" not in line
    ]

    assert lookups == [], f"a picture is still found by its label: {lookups}"


def test_a_file_that_arrives_with_no_tags_at_all(tmp_path):
    """It gets a receptacle on construction, before the picture is ever
    looked for — which is why the lookup needs no guard of its own."""

    folder = tmp_path / PLAYLIST
    folder.mkdir(parents=True)
    path = folder / "UNKNOWN - Nothing [ccccccccccc].mp3"
    path.write_bytes(_FRAME * 8)

    assert MP3(path).tags is None

    song = SongModel(path)

    assert MP3(path).tags is not None
    assert song.has_cover_art is False
