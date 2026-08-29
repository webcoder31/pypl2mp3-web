"""The model keeping a document beside the frames it writes.

The frames are still the source of truth: nothing reads the document yet.
What this step buys is that it stops drifting — before, only a script
wrote it, so every save made through the application left it a little
further behind.

Provenance is the part that could not exist in the frames at all. A field
records who decided it, so a later automated pass can tell a value it may
overwrite from one somebody typed. That distinction is what the backfill
had to work around by hand, by refusing to call `shazam_song`.
"""

import asyncio
import json
from pathlib import Path

import pytest
from mutagen.id3 import ID3, PRIV, TPE1, TXXX
from mutagen.mp3 import MP3

from pypl2mp3.libs import metadata
from pypl2mp3.libs.song import SongModel

_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413
PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"


def _song(repo: Path, vid="aaaaaaaaaaa"):
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"IAMX - Kiss [{vid}].mp3"
    path.write_bytes(_FRAME * 8)

    tags = ID3()
    tags.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
    tags.add(TPE1(encoding=3, text="IAMX"))
    tags.save(path, v1=0, v2_version=3)

    return path


class TestItIsWritten:
    def test_a_save_leaves_a_document_beside_the_frames(self, tmp_path):
        path = _song(tmp_path)
        assert metadata.read(path) is None

        SongModel(path).update_state(title="Kiss")

        document = metadata.read(path)

        assert document is not None
        assert metadata.value(document, "title") == "Kiss"
        assert metadata.value(document, "artist") == "IAMX"

    def test_it_goes_in_the_same_write_as_the_frames(self, tmp_path):
        """Two saves would leave a window in which the frames and the
        document disagree on disk, and double the I/O of every edit."""

        path = _song(tmp_path)
        saves = []

        original = MP3.save

        def counting(self, *args, **kwargs):
            saves.append(1)
            return original(self, *args, **kwargs)

        MP3.save = counting
        try:
            SongModel(path).update_state(title="Kiss")
        finally:
            MP3.save = original

        assert len(saves) == 1, f"{len(saves)} saves for one edit"

    def test_the_peaks_survive_it(self, tmp_path):
        """Both live in PRIV frames, and `delall` takes a frame type and
        not an owner."""

        path = _song(tmp_path)
        tags = ID3(path)
        tags.add(PRIV(owner="https://example.invalid/peaks", data=b"peaks"))
        tags.save(path, v1=0, v2_version=3)

        SongModel(path).update_state(title="Kiss")

        owners = {f.owner: f.data for f in MP3(path).tags.getall("PRIV")}

        assert owners["https://example.invalid/peaks"] == b"peaks"
        assert metadata.OWNER in owners


class TestProvenance:
    def test_the_form_speaks_for_the_user(self, tmp_path):
        """What the form writes outranks any later automated pass, and
        this is where that is recorded."""

        from pypl2mp3.services.fix_junks import apply_fix

        _song(tmp_path)
        asyncio.run(apply_fix(tmp_path, "aaaaaaaaaaa", "MINE", "My Title"))

        path = next(tmp_path.rglob("*.mp3"))
        document = metadata.read(path)

        assert document["fields"]["artist"]["by"] == "user"
        assert document["fields"]["title"]["by"] == "user"

    def test_a_caller_that_says_nothing_claims_nothing(self, tmp_path):
        """"legacy" is not a placeholder: it means the authority behind
        this value is unknown, and an automated pass must not treat it as
        its own to overwrite."""

        path = _song(tmp_path)
        SongModel(path).update_state(title="Kiss")

        assert metadata.read(path)["fields"]["title"]["by"] == "legacy"

    def test_an_unchanged_value_keeps_the_entry_it_had(self, tmp_path):
        """Rewriting it would replace a real moment with this one and lose
        the only thing the document holds that the frames never did."""

        from pypl2mp3.services.fix_junks import apply_fix

        _song(tmp_path)
        asyncio.run(apply_fix(tmp_path, "aaaaaaaaaaa", "MINE", "My Title"))
        path = next(tmp_path.rglob("*.mp3"))
        before = metadata.read(path)["fields"]["artist"]

        # A save that does not touch the artist.
        SongModel(path).update_state(album="An Album")

        assert metadata.read(path)["fields"]["artist"] == before


class TestItRefusesToGuess:
    def test_a_document_it_cannot_read_is_left_alone(self, tmp_path):
        """Overwriting it would destroy whatever a newer build knew, and
        refusing to save the frames would break the application over a
        shadow nothing reads yet. Leaving it untouched does neither."""

        path = _song(tmp_path)
        future = dict(metadata.blank("aaaaaaaaaaa"), v=metadata.VERSION + 1,
                      extra="written by a newer build")
        tags = ID3(path)
        tags.add(PRIV(owner=metadata.OWNER,
                      data=json.dumps(future).encode("utf-8")))
        tags.save(path, v1=0, v2_version=3)

        SongModel(path).update_state(title="Saved anyway")

        assert str(MP3(path).tags["TIT2"].text[0]) == "Saved anyway"

        kept = [f for f in MP3(path).tags.getall("PRIV")
                if f.owner == metadata.OWNER]
        stored = json.loads(kept[0].data)

        assert stored["v"] == metadata.VERSION + 1
        assert stored["extra"] == "written by a newer build"

    def test_an_empty_field_is_not_recorded(self, tmp_path):
        """A field with no value has no provenance to record either, and
        an entry holding "" would be a value somebody could adopt."""

        path = _song(tmp_path)
        SongModel(path).update_state(title="Kiss")

        assert "album" not in metadata.read(path)["fields"]


class TestTheHandlesShazamCarries:
    """Identifiers and a palette that never became ID3 frames.

    None of them describe the song. `key` and `url` name the answer;
    `apple_album` and `apple_artists` are what the iTunes lookup takes,
    which turns a later question into one HTTP request instead of a
    fifteen-second recognition. That is the whole reason to keep them —
    and the reason the document exists, since inventing five more custom
    frames is what this branch is leaving behind.
    """

    def test_they_are_read_out_of_the_answer(self):
        track = {
            "key": 470682427,
            "url": "https://www.shazam.com/track/470682427/x",
            "albumadamid": 1485457072,
            "artists": [{"id": "42", "adamid": "110799"}],
            "images": {"joecolor": "b:5e5d71p:f7e4df"},
        }

        assert SongModel._shazam_identity(track) == {
            "key": "470682427",
            "url": "https://www.shazam.com/track/470682427/x",
            "apple_album": "1485457072",
            "apple_artists": ["110799"],
            "colors": "b:5e5d71p:f7e4df",
        }

    def test_the_palette_is_stored_exactly_as_given(self):
        """`b:…p:…s:…t:…q:…` — believed to be background, primary,
        secondary and two text tints. Believed, not decided: this block is
        evidence, and parsing it here would bake an interpretation into
        the file that a reader could not undo."""

        raw = "b:5e5d71p:f7e4dfs:f8c2b3t:d8c9c9q:d9aea6"

        assert SongModel._shazam_identity(
            {"images": {"joecolor": raw}}
        )["colors"] == raw

    def test_an_answer_that_carries_none_of_them_says_nothing(self):
        """Absent rather than empty: a key holding "" would be a handle
        somebody could try to follow."""

        assert SongModel._shazam_identity({}) == {}
        assert SongModel._shazam_identity(
            {"key": "", "images": {"joecolor": "  "}}
        ) == {}

    def test_an_ordinary_save_does_not_drop_them(self, tmp_path):
        """They live only in the document. Replacing the block wholesale
        on every save would quietly lose them, and fetching them again
        would cost a five-hour pass."""

        path = _song(tmp_path)

        song = SongModel(path)
        song._shazam_extras = {"key": "470682427", "colors": "b:5e5d71"}
        song.update_state(shazam_artist="IAMX", shazam_match_score=91,
                          by="shazam")

        SongModel(path).update_state(title="Edited by hand")

        answer = metadata.read(path)["sources"]["shazam"]

        assert answer["key"] == "470682427"
        assert answer["colors"] == "b:5e5d71"

    def test_a_new_recognition_supersedes_the_previous_one(self, tmp_path):
        """Whatever the previous answer named is about a track this one
        may not agree with. Merging would leave the album id of a record
        Shazam no longer claims this is."""

        path = _song(tmp_path)

        first = SongModel(path)
        first._shazam_extras = {"key": "111", "apple_album": "222"}
        first.update_state(shazam_artist="IAMX", shazam_match_score=91,
                           by="shazam")

        second = SongModel(path)
        second._shazam_extras = {"key": "333"}
        second.update_state(shazam_artist="Someone Else",
                            shazam_match_score=60, by="shazam")

        answer = metadata.read(path)["sources"]["shazam"]

        assert answer["key"] == "333"
        assert "apple_album" not in answer, (
            "the album id of a record Shazam no longer claims this is"
        )


class TestTheWiring:
    """That `shazam_song` actually reaches for them.

    Every test above sets `_shazam_extras` by hand, so removing the one
    line in `shazam_song` that fills it broke nothing — a counter-
    experiment caught that, and this is the gap it found.
    """

    def test_a_recognition_puts_the_handles_in_the_document(
        self, tmp_path, monkeypatch
    ):
        path = _song(tmp_path)

        answer = {
            "track": {
                "title": "Kiss",
                "subtitle": "IAMX",
                "key": 470682427,
                "url": "https://www.shazam.com/track/470682427/kiss",
                "albumadamid": 1485457072,
                "artists": [{"adamid": "110799"}],
                "images": {"joecolor": "b:5e5d71p:f7e4df"},
                "sections": [{"metadata": [{"title": "Album", "text": "K"}]}],
            }
        }

        class Client:
            async def recognize_song(self, _path):
                return answer

        monkeypatch.setattr(SongModel, "shazam_client", Client())
        monkeypatch.setattr(SongModel, "last_shazam_request_time", 0)
        monkeypatch.setattr(
            "pypl2mp3.libs.song.asyncio.sleep",
            lambda _seconds: asyncio.sleep(0),
        )

        song = SongModel(path)
        asyncio.run(song.shazam_song())

        stored = metadata.read(next(tmp_path.rglob("*.mp3")))["sources"]["shazam"]

        assert stored["key"] == "470682427"
        assert stored["apple_album"] == "1485457072"
        assert stored["apple_artists"] == ["110799"]
        assert stored["colors"] == "b:5e5d71p:f7e4df"
        assert stored["url"].endswith("/kiss")
