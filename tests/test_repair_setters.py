"""Correcting an attribution the document could not make at the time.

The documents were built from frames, and a frame holds a string with no
account of where it came from — so most of this library says `legacy`,
"nobody knows". The global Shazam pass could not fix that on its own: it
writes `by="shazam"`, but the rule that an unchanged value keeps its
entry protects a stale `by` along with the moment it records, and 780 of
its 811 songs already held the same values.

What the pass did leave is Shazam's own answer, stored beside the value.
Where a field marked `legacy` holds exactly what Shazam answered, Shazam
decided it — the strings cannot be equal otherwise, since a person who
typed the same URL would have been marked `user`.
"""

import importlib.util
from pathlib import Path

import pytest

from pypl2mp3.libs import metadata

WHEN = "2026-08-01T10:00:00Z"


@pytest.fixture(scope="module")
def script():
    path = Path("scripts/repair_setters.py")
    spec = importlib.util.spec_from_file_location("repair", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def _document(by="legacy", value="IAMX", answered="IAMX", at=None):
    document = metadata.set_field(metadata.blank("a"), "artist", value, by, at=at)

    return metadata.set_source(
        document, "shazam", {"artist": answered}, at=WHEN
    )


def test_a_value_that_is_shazams_answer_is_attributed_to_shazam(script):
    fixed = script.repair(_document())

    assert metadata.field(fixed, "artist")["by"] == "shazam"


def test_a_value_that_is_not_is_left_alone(script):
    """Most of the artists still marked `legacy` differ from what Shazam
    answered — they are the rejected matches and the names that came from
    elsewhere. Nothing in the file says who chose them, and `legacy` is
    the true answer, not a placeholder to be filled."""

    fixed = script.repair(_document(value="Someone Else"))

    assert metadata.field(fixed, "artist")["by"] == "legacy"


def test_what_somebody_typed_is_never_reattributed(script):
    """Even when it happens to match. `user` outranks any inference, and
    losing it would take away the warning the panel shows before Ask
    Shazam."""

    fixed = script.repair(_document(by="user"))

    assert metadata.field(fixed, "artist")["by"] == "user"


def test_the_moment_is_left_exactly_as_it_was(script):
    """Including null. This corrects an attribution, not a moment:
    stamping today would replace "we do not know when" with a time
    nothing happened."""

    fixed = script.repair(_document(at=None))
    assert metadata.field(fixed, "artist")["at"] is None

    fixed = script.repair(_document(at=WHEN))
    assert metadata.field(fixed, "artist")["at"] == WHEN


def test_only_the_three_witnessed_fields_are_ever_corrected(script):
    """The album, the year, the genre and the label have standard frames
    of their own, so no twin was ever kept and nothing witnesses who
    chose them.

    The answer here is made to carry an album equal to the field, which
    the real block never does — precisely so that the equality check
    cannot be what passes this test. It is the list that bounds the
    evidence, and a later version that started storing the release inside
    `sources.shazam` would otherwise begin attributing it in silence."""

    document = metadata.set_field(
        metadata.blank("a"), "album", "Kingdom of Welcome Addiction",
        "legacy", at=None,
    )
    document = metadata.set_source(
        document, "shazam",
        {"artist": "IAMX", "album": "Kingdom of Welcome Addiction"},
        at=WHEN,
    )

    assert script.corrections(document) == []
    assert metadata.field(script.repair(document), "album")["by"] == "legacy"


def test_an_empty_field_is_not_a_match_for_an_empty_answer(script):
    """Two absences are not evidence of anything — and they compare
    equal, which is exactly why this needs its own guard rather than
    leaning on the comparison."""

    document = metadata.set_field(
        metadata.blank("a"), "artist", "", "legacy", at=None
    )
    document = metadata.set_source(document, "shazam", {"artist": ""}, at=WHEN)

    assert metadata.field(document, "artist")["value"] == ""
    assert document["sources"]["shazam"]["artist"] == ""
    assert script.corrections(document) == []


def test_a_document_already_right_is_not_rewritten(script, tmp_path):
    """`metadata.write` returns False for an unchanged document, and a
    needless write moves the file's timestamp — which busts the cover's
    address and the repository's parse cache for nothing."""

    from mutagen.id3 import ID3, TXXX

    path = tmp_path / "IAMX - Kiss [aaaaaaaaaaa].mp3"
    path.write_bytes((b"\xff\xfb\x90\xc0" + b"\x00" * 413) * 8)

    tags = ID3()
    tags.add(TXXX(encoding=3, desc="YouTube ID", text="aaaaaaaaaaa"))
    metadata.attach(tags, _document(by="shazam"))
    tags.save(path, v1=0, v2_version=3)

    document = metadata.read(path)

    assert script.corrections(document) == []
    assert metadata.write(path, script.repair(document)) is False
