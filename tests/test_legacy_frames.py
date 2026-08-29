"""Reading three generations of frames, and admitting what cannot be read.

The names changed twice without a migration, so one library holds all
three at once. Every generation is read here; what is *not* read is
provenance, because no frame ever recorded it — and saying so is the
point rather than a shortcoming.
"""

from pathlib import Path

import pytest
from mutagen.id3 import ID3, APIC, TALB, TCON, TIT2, TPE1, TPUB, TSRC, TXXX
from mutagen.mp3 import MP3

from pypl2mp3.libs import legacy

_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413
_JPEG = bytes.fromhex("ffd8ffe000104a464946000101" + "00" * 40 + "ffd9")
PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"

SHAZAM_COVER = "https://is1-ssl.mzstatic.com/image/thumb/x/400x400cc.jpg"
YOUTUBE_COVER = "https://i.ytimg.com/vi/aaaaaaaaaaa/hq720.jpg"


def _song(repo: Path, *, vid="aaaaaaaaaaa", junk=False, picture=None,
          customs=(), **text):
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    suffix = " (JUNK)" if junk else ""
    path = folder / f"{text.get('TPE1', 'X')} - Y [{vid}]{suffix}.mp3"
    path.write_bytes(_FRAME * 8)

    tags = ID3()
    tags.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
    for frame, value in text.items():
        tags.add({"TPE1": TPE1, "TIT2": TIT2, "TALB": TALB, "TCON": TCON,
                  "TPUB": TPUB, "TSRC": TSRC}[frame](encoding=3, text=value))
    for desc, value in customs:
        tags.add(TXXX(encoding=3, desc=desc, text=value))
    if picture is not None:
        label, kind = picture
        tags.add(APIC(encoding=3, desc=label, mime="image/jpg", type=kind,
                      data=_JPEG))
    tags.save(path, v1=0, v2_version=3)

    return path


class TestReadingEveryGeneration:
    def test_the_current_shazam_frame_names(self, tmp_path):
        path = _song(tmp_path, customs=[
            ("Shazam artist", "IAMX"), ("Shazam title", "Kiss"),
            ("Shazam match level", "91"),
        ])

        answer = legacy.shazam_answer(legacy.read_frames(path))

        assert answer == {"artist": "IAMX", "title": "Kiss", "score": 91}

    def test_the_names_used_before_may_2025(self, tmp_path):
        """55 songs in one library carry these, and nothing has ever read
        them back. Missing them would throw away the only record that
        Shazam was ever asked."""

        path = _song(tmp_path, customs=[
            ("Shazam matching artist", "IAMX"),
            ("Shazam matching title", "Kiss"),
            ("Shazam matching rate", "91"),
        ])

        answer = legacy.shazam_answer(legacy.read_frames(path))

        assert answer == {"artist": "IAMX", "title": "Kiss", "score": 91}

    def test_the_recording_code_comes_from_the_standard_frame(
        self, tmp_path
    ):
        """It never had a custom frame of its own: it goes into TSRC,
        which anything can read. Only Shazam ever supplies one here, so a
        file carrying a code carries Shazam's."""

        path = _song(tmp_path, TSRC="GBDHC1907207", customs=[
            ("Shazam artist", "IAMX"), ("Shazam match level", "91"),
        ])

        answer = legacy.shazam_answer(legacy.read_frames(path))

        assert answer["isrc"] == "GBDHC1907207"

    def test_a_file_with_no_recording_code_says_nothing_about_one(
        self, tmp_path
    ):
        """No file in the 944-song library had one when this was written:
        Shazam returned it on every answer and it was thrown away. The
        key has to be absent rather than empty, or every migrated
        document would claim a code it does not have."""

        path = _song(tmp_path, customs=[("Shazam artist", "IAMX")])

        assert "isrc" not in legacy.shazam_answer(legacy.read_frames(path))

    def test_the_current_name_wins_when_both_are_there(self, tmp_path):
        path = _song(tmp_path, customs=[
            ("Shazam artist", "current"),
            ("Shazam matching artist", "older"),
        ])

        assert legacy.read_frames(path)["shazam"]["artist"] == "current"

    def test_a_picture_is_found_whatever_it_is_called(self, tmp_path):
        """"Cover art" here, "Stored cover art" in 105 songs, the empty
        string in files other taggers touched."""

        for label in ("Cover art", "Stored cover art", "", "front"):
            path = _song(tmp_path, picture=(label, 3))

            assert legacy.read_frames(path)["cover"]["sha256"], (
                f"a picture labelled {label!r} was not found"
            )

    def test_a_picture_that_is_not_a_front_cover_is_not_the_cover(
        self, tmp_path
    ):
        path = _song(tmp_path, picture=("Cover art", 8))

        assert legacy.read_frames(path)["cover"]["sha256"] == ""

    def test_the_id_falls_back_to_the_filename(self, tmp_path):
        """The same two sources the model uses, in the same order — a song
        this cannot identify is one the model cannot identify either."""

        path = _song(tmp_path, vid="r4L-YY5rtq4")
        tags = ID3(path)
        tags.delall("TXXX:YouTube ID")
        tags.save(path, v1=0, v2_version=3)

        assert legacy.song_id(path, MP3(path).tags) == "r4L-YY5rtq4"


class TestWhatCanBeEstablished:
    def test_a_value_matching_an_applied_answer_came_from_shazam(
        self, tmp_path
    ):
        """The one case that is certain rather than guessed: that is what
        the threshold means."""

        path = _song(tmp_path, TPE1="IAMX", customs=[
            ("Shazam artist", "IAMX"), ("Shazam match level", "91"),
        ])
        frames = legacy.read_frames(path)

        assert legacy.setter_for("artist", frames) == "shazam"

    def test_a_value_matching_a_rejected_answer_did_not(self, tmp_path):
        """Below the threshold the names are whatever the import left, and
        the answer beside them was only ever a proposal."""

        path = _song(tmp_path, TPE1="Some Channel", customs=[
            ("Shazam artist", "Some Channel"), ("Shazam match level", "20"),
        ])
        frames = legacy.read_frames(path)

        assert legacy.setter_for("artist", frames) == "legacy"

    def test_a_value_that_differs_from_the_answer_is_not_attributed(
        self, tmp_path
    ):
        """It may be an edit made by hand or the title YouTube gave. The
        frames do not say, and guessing "user" would be as wrong as
        guessing "import"."""

        path = _song(tmp_path, TPE1="Corrected", customs=[
            ("Shazam artist", "Proposed"), ("Shazam match level", "91"),
        ])

        assert legacy.setter_for("artist", legacy.read_frames(path)) == "legacy"

    def test_the_release_data_is_never_attributed(self, tmp_path):
        """It was written by one pass, days ago, and nothing recorded
        that. Marking it "shazam" would let a later pass overwrite the
        four values a user corrected by hand."""

        path = _song(tmp_path, TPE1="IAMX", TALB="Album", TCON="Rock")
        frames = legacy.read_frames(path)

        assert legacy.setter_for("album", frames) == "legacy"
        assert legacy.setter_for("genre", frames) == "legacy"

    def test_the_cover_host_answers_when_no_score_was_kept(self, tmp_path):
        """Everything imported before the provenance frames existed has no
        score. Shazam's artwork comes from Apple's CDN and a YouTube
        thumbnail means it never matched — which is the only evidence left
        for 787 songs."""

        shazamed = _song(tmp_path, vid="aaaaaaaaaaa",
                         customs=[("Cover art URL", SHAZAM_COVER)])
        never = _song(tmp_path, vid="bbbbbbbbbbb",
                      customs=[("Cover art URL", YOUTUBE_COVER)])

        assert legacy.matched(legacy.read_frames(shazamed)) is True
        assert legacy.matched(legacy.read_frames(never)) is False

    def test_the_digest_is_read_and_not_inferred(self, tmp_path):
        """The one fact the old arrangement never recorded, and the one
        that makes "is this already the picture being asked for?"
        answerable without trusting a URL."""

        import hashlib

        path = _song(tmp_path, picture=("Cover art", 3))

        assert legacy.read_frames(path)["cover"]["sha256"] == (
            hashlib.sha256(_JPEG).hexdigest()
        )


class TestTheDocument:
    def test_every_timestamp_is_null(self, tmp_path):
        """No frame records when anything happened, and the file's own
        date has been moved by the peak store and by two repair passes.
        Today's date would make every migrated field look freshly
        decided."""

        path = _song(tmp_path, TPE1="IAMX", TIT2="Kiss", picture=("Cover art", 3),
                     customs=[("Cover art URL", SHAZAM_COVER),
                              ("Shazam artist", "IAMX"),
                              ("Shazam match level", "91")])

        document = legacy.document_from_frames(path)

        assert all(f["at"] is None for f in document["fields"].values())
        assert document["sources"]["shazam"]["at"] is None
        assert document["embedded"]["at"] is None

    def test_an_empty_field_is_absent_rather_than_empty(self, tmp_path):
        """A field with no value has no provenance to record either, and
        an entry saying "" would be a value somebody could adopt."""

        path = _song(tmp_path, TPE1="IAMX")

        document = legacy.document_from_frames(path)

        assert "artist" in document["fields"]
        assert "album" not in document["fields"]

    def test_reading_writes_nothing(self, tmp_path):
        """Building a document and storing it are separate acts, so a
        comparison pass can hold what the frames say beside what the
        document says without touching a file."""

        path = _song(tmp_path, TPE1="IAMX", picture=("Cover art", 3))
        before = path.stat().st_mtime_ns, path.stat().st_size

        legacy.document_from_frames(path)

        assert (path.stat().st_mtime_ns, path.stat().st_size) == before
