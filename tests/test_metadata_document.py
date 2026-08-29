"""The document a song carries, and the promises it has to keep.

Each of these pins something that went wrong in the arrangement it
replaces, so the failure it prevents is named rather than implied.
"""

import json
from pathlib import Path

import pytest
from mutagen.id3 import ID3, PRIV, TXXX
from mutagen.mp3 import MP3

from pypl2mp3.libs import metadata
from pypl2mp3.libs.metadata import MetadataError, UnknownVersion

_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413
PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"
WHEN = "2026-08-29T12:00:00Z"


def _song(repo: Path, vid: str = "aaaaaaaaaaa") -> Path:
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"IAMX - Kiss [{vid}].mp3"
    path.write_bytes(_FRAME * 8)

    tags = ID3()
    tags.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
    tags.save(path, v1=0, v2_version=3)

    return path


class TestShape:
    """A schema where a key is sometimes there is a schema every reader
    has to guard, and this codebase has been caught by that twice."""

    def test_a_blank_document_already_has_every_branch(self):
        document = metadata.blank("aaaaaaaaaaa")

        assert document["v"] == metadata.VERSION
        assert document["id"] == "aaaaaaaaaaa"
        assert document["fields"] == {}
        assert set(document["sources"]) == set(metadata.SOURCES)
        assert document["embedded"] == {}

    def test_a_field_always_carries_who_and_when(self):
        """The whole reason the block exists: an automated pass has to be
        able to tell a value it may overwrite from one somebody typed."""

        document = metadata.set_field(
            metadata.blank("a"), "artist", "IAMX", "shazam", at=WHEN
        )

        assert document["fields"]["artist"] == {
            "value": "IAMX", "by": "shazam", "at": WHEN,
        }

    def test_every_displayed_value_can_be_a_field(self):
        """Anything shown that cannot be a field is a value no pass can
        reason about — which is how the release data ended up with no
        provenance at all."""

        assert set(metadata.FIELDS) == {
            "artist", "title", "album", "year", "genre", "publisher", "cover",
        }

    def test_an_unknown_field_is_refused_rather_than_stored(self):
        """A typo that silently creates a field is a field nothing reads."""

        with pytest.raises(MetadataError):
            metadata.set_field(metadata.blank("a"), "titel", "x", "user")

        with pytest.raises(MetadataError):
            metadata.field(metadata.blank("a"), "titel")

    def test_a_value_of_unknown_origin_says_so(self):
        """The old frames record no provenance. A pass that believed a
        recovered value came from Shazam would feel free to overwrite an
        edit somebody made by hand, so "unknown" has to be sayable."""

        assert "legacy" in metadata.SETTERS

        document = metadata.set_field(
            metadata.blank("a"), "title", "Kiss", "legacy", at=None
        )

        assert document["fields"]["title"] == {
            "value": "Kiss", "by": "legacy", "at": None,
        }

    def test_a_moment_can_be_unknown_without_the_key_going_missing(self):
        """Nothing in the old frames says when a value was set, and the
        file's own date has been moved by the peak store and by two repair
        passes. Writing today's date would make every migrated field look
        freshly decided — which defeats the one comparison the document is
        for, field older than the last answer."""

        given = metadata.set_field(metadata.blank("a"), "title", "K", "user")
        unknown = metadata.set_field(
            metadata.blank("a"), "title", "K", "legacy", at=None
        )

        assert given["fields"]["title"]["at"] is not None
        assert unknown["fields"]["title"]["at"] is None
        assert "at" in unknown["fields"]["title"]

    def test_an_unknown_setter_is_refused(self):
        with pytest.raises(MetadataError):
            metadata.set_field(metadata.blank("a"), "title", "x", "robot")


class TestSeparation:
    """Three questions kept apart: what the file claims, what each
    upstream answered, what the file actually contains."""

    def test_a_source_is_evidence_and_is_not_a_decision(self):
        """A Shazam match currently overwrites YouTube's own title with
        nothing keeping a copy. Recording the answer is not the same act
        as adopting it."""

        document = metadata.set_source(
            metadata.blank("a"), "youtube",
            {"author": "IAMX", "title": "IAMX - Kiss (official)"},
            at=WHEN,
        )

        assert document["sources"]["youtube"]["title"] == "IAMX - Kiss (official)"
        assert document["sources"]["youtube"]["at"] == WHEN
        # And nothing was decided by recording it.
        assert document["fields"] == {}

    def test_adopting_an_answer_leaves_the_answer_intact(self):
        document = metadata.set_source(
            metadata.blank("a"), "youtube", {"title": "IAMX - Kiss (official)"},
            at=WHEN,
        )
        document = metadata.set_field(
            document, "title", "Kiss", "shazam", at=WHEN
        )

        assert metadata.value(document, "title") == "Kiss"
        assert document["sources"]["youtube"]["title"] == "IAMX - Kiss (official)"

    def test_what_is_embedded_is_a_digest_and_not_a_url(self):
        """"Is this already the picture being asked for?" stays
        answerable without trusting anything outside the file, and after
        the URL has rotted. Asking it of a URL is what stopped covers
        from ever being refetched."""

        document = metadata.set_embedded_cover(
            metadata.blank("a"), "3f9a", at=WHEN
        )

        assert document["embedded"] == {"cover_sha256": "3f9a", "at": WHEN}

    def test_an_unknown_source_is_refused(self):
        with pytest.raises(MetadataError):
            metadata.set_source(metadata.blank("a"), "spotify", {})


class TestSettersDoNotMutate:
    def test_the_given_document_is_left_alone(self):
        """The shadow phase holds one document read from the file beside
        another rebuilt from the old frames and compares them. A setter
        that mutated in place would quietly make the two the same
        object."""

        before = metadata.blank("a")
        after = metadata.set_field(before, "title", "Kiss", "user", at=WHEN)

        assert before["fields"] == {}
        assert after["fields"]["title"]["value"] == "Kiss"
        assert before is not after


class TestStorage:
    def test_a_document_survives_a_round_trip(self, tmp_path):
        path = _song(tmp_path)
        document = metadata.set_field(
            metadata.blank("aaaaaaaaaaa"), "title", "Kiss", "user", at=WHEN
        )

        assert metadata.write(path, document) is True
        assert metadata.read(path) == document

    def test_a_song_with_no_document_reads_as_none(self, tmp_path):
        assert metadata.read(_song(tmp_path)) is None

    def test_writing_an_unchanged_document_does_not_touch_the_file(
        self, tmp_path
    ):
        """The keys are sorted so the bytes are stable. A needless write
        moves the file's timestamp, which busts the cover's address and
        the repository's parse cache for nothing."""

        path = _song(tmp_path)
        document = metadata.set_field(
            metadata.blank("aaaaaaaaaaa"), "title", "Kiss", "user", at=WHEN
        )
        metadata.write(path, document)

        before = path.stat().st_mtime_ns

        assert metadata.write(path, document) is False
        assert path.stat().st_mtime_ns == before

    def test_the_same_content_built_in_another_order_is_not_a_change(
        self, tmp_path
    ):
        """What sorting the keys is actually for. A document read back
        from the file and one rebuilt by the setters hold the same thing
        in a different insertion order; unsorted, they would serialise
        differently and every pass would rewrite every file it looked at,
        moving 944 timestamps for nothing."""

        path = _song(tmp_path)

        one = metadata.blank("aaaaaaaaaaa")
        one = metadata.set_field(one, "artist", "IAMX", "shazam", at=WHEN)
        one = metadata.set_field(one, "title", "Kiss", "user", at=WHEN)
        metadata.write(path, one)

        other = metadata.blank("aaaaaaaaaaa")
        other = metadata.set_field(other, "title", "Kiss", "user", at=WHEN)
        other = metadata.set_field(other, "artist", "IAMX", "shazam", at=WHEN)

        assert list(one["fields"]) != list(other["fields"]), (
            "the two were built in the same order, so this proves nothing"
        )
        assert metadata.write(path, other) is False, (
            "the same content in another order counted as a change"
        )

    def test_another_application_keeps_its_private_frames(self, tmp_path):
        """`delall` takes a frame type and not an owner. The waveform's
        peaks live in a PRIV frame of their own and must survive every
        write here — as must anything a third party left."""

        path = _song(tmp_path)
        tags = ID3(path)
        tags.add(PRIV(owner="https://example.invalid/other", data=b"theirs"))
        tags.save(path, v1=0, v2_version=3)

        metadata.write(path, metadata.blank("aaaaaaaaaaa"))

        owners = {f.owner: f.data for f in MP3(path).tags.getall("PRIV")}
        assert owners["https://example.invalid/other"] == b"theirs"
        assert metadata.OWNER in owners

    def test_a_newer_document_is_refused_rather_than_misread(self, tmp_path):
        """Treating a version it does not understand as one it does, then
        writing it back in the older shape, is how the Shazam frame names
        came to exist in three generations at once."""

        path = _song(tmp_path)
        future = dict(metadata.blank("aaaaaaaaaaa"), v=metadata.VERSION + 1)
        tags = ID3(path)
        tags.add(PRIV(owner=metadata.OWNER,
                      data=json.dumps(future).encode("utf-8")))
        tags.save(path, v1=0, v2_version=3)

        with pytest.raises(UnknownVersion):
            metadata.read(path)

    def test_a_frame_that_is_not_a_document_is_reported(self, tmp_path):
        path = _song(tmp_path)
        tags = ID3(path)
        tags.add(PRIV(owner=metadata.OWNER, data=b"not json at all"))
        tags.save(path, v1=0, v2_version=3)

        with pytest.raises(MetadataError):
            metadata.read(path)

    def test_the_version_is_inside_the_document_not_in_the_owner(self):
        """The peaks do the opposite, and that is right for them: a cache
        whose format changes can be discarded and recomputed. A record has
        to be migrated, which means a reader must be able to find it
        whatever version it is."""

        assert not metadata.OWNER.endswith("-1")
        assert metadata.blank("a")["v"] == metadata.VERSION
