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

    # A different rule reaches the album — it is one of the four only
    # Shazam can write — but not this one, and not on this evidence.
    assert [n for n, _v, _a in script.corrections(document)] == []


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


# ---------------------------------------------------------------------
# Who decided the fields no answer of Shazam's witnesses.
#
# Three rules, each resting on something the code makes true rather than
# on what the values look like.
# ---------------------------------------------------------------------

def _with_origin(document, author="Some Channel", title="Some Video"):
    return metadata.set_source(
        document, "youtube", {"author": author, "title": title}, at=WHEN
    )


def _blank_legacy(name, value, vid="aaaaaaaaaaa"):
    return metadata.set_field(metadata.blank(vid), name, value, "legacy", at=None)


def test_a_release_field_can_only_be_shazams(script):
    """Exactly two places write those four — the accepted-match branch of
    `shazam_song` and the backfill. The import does not touch them, and
    neither the workbench form nor the terminal prompt offers them, so
    there is no door a person could have come through.

    Marking them as somebody's would put the panel's warning on nearly
    every song in the library, which is the same as removing it."""

    for name, value in (("album", "Alive"), ("year", "2018"),
                        ("genre", "Alternative"), ("publisher", "61 Seconds")):
        document = _with_origin(_blank_legacy(name, value))
        got = script.inferences(document, is_junk=False)

        assert got == [(name, value, None, "shazam")], name


def test_a_name_the_video_had_is_the_imports(script):
    """The import writes `video.author` and `video.title` unparsed, and
    oEmbed returns those same two strings — so this is an exact match and
    not a resemblance."""

    document = _with_origin(_blank_legacy("artist", "Some Channel"))

    assert script.inferences(document, is_junk=False) == [
        ("artist", "Some Channel", None, "import")
    ]


def test_a_name_the_video_never_had_is_somebodys(script):
    """`Pixies` against a channel called `Subbacultcha`, `U2` against
    `Joshua Miller`. Nothing else could have put them there: it is not
    the video's, and the repair above already claimed everything that
    matched Shazam's answer."""

    document = _with_origin(_blank_legacy("artist", "Pixies"),
                            author="Subbacultcha")

    assert script.inferences(document, is_junk=False) == [
        ("artist", "Pixies", None, "user")
    ]


def test_a_junk_song_is_never_said_to_be_somebodys(script):
    """Its values were not typed. `reset_state` clears the frames, the
    constructor then derives artist and title from the filename and
    writes them straight back — so a junk song carries names nobody
    chose, and a warning there would be about nothing."""

    document = _with_origin(_blank_legacy("artist", "Pixies"),
                            author="Subbacultcha")

    assert script.inferences(document, is_junk=True) == []


def test_a_junk_song_still_gets_what_is_certain(script):
    """The exclusion is about the inference from absence, not about the
    song. What only Shazam can have written is Shazam's on a junk song
    too."""

    document = _with_origin(_blank_legacy("album", "Alive"))

    assert script.inferences(document, is_junk=True) == [
        ("album", "Alive", None, "shazam")
    ]


def test_this_videos_own_thumbnail_is_the_imports(script):
    """The id is in the path, so this is not "looks like YouTube" but
    "is the thumbnail of this very video"."""

    url = "https://i.ytimg.com/vi/aaaaaaaaaaa/hq720.jpg"
    document = _with_origin(_blank_legacy("cover", url))

    assert script.inferences(document, is_junk=False) == [
        ("cover", url, None, "import")
    ]


def test_another_videos_thumbnail_is_not(script):
    """A thumbnail carrying a different id did not come from importing
    this song, and guessing which door it came through would be
    guessing."""

    url = "https://i.ytimg.com/vi/zzzzzzzzzzz/hq720.jpg"
    document = _with_origin(_blank_legacy("cover", url))

    assert script.inferences(document, is_junk=False) == []


def test_artwork_apple_serves_is_shazams(script):
    """All 169 of the covers left over sit on that host. Nobody pasted a
    hundred and sixty-nine Apple URLs by hand; they are answers whose
    exact URL has since moved — a different crop, or a later reply."""

    url = "https://is1-ssl.mzstatic.com/image/thumb/Music114/v4/x/400x400cc.jpg"
    document = _with_origin(_blank_legacy("cover", url))

    assert script.inferences(document, is_junk=False) == [
        ("cover", url, None, "shazam")
    ]


def test_a_video_whose_name_was_never_recovered_decides_nothing(script):
    """Eleven videos went before the pass that would have recorded what
    they were called. There is nothing to compare against, so the field
    keeps the honest answer."""

    document = metadata.set_source(
        _blank_legacy("artist", "Pixies"), "youtube",
        {"gone": True, "http": 404}, at=WHEN,
    )

    assert script.inferences(document, is_junk=False) == []


def test_what_is_already_attributed_is_left_alone(script):
    """Both halves: a person's decision outranks every inference here,
    and a field already marked is not re-derived."""

    for by in ("user", "shazam", "import"):
        document = _with_origin(
            metadata.set_field(metadata.blank("a"), "album", "Alive", by, at=WHEN)
        )

        assert script.inferences(document, is_junk=False) == [], by
