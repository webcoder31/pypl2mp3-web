"""The model asking the document first, and the frames only after.

This is the switch. Before it, every attribute came from a frame found by
the free-text label somebody gave it — which is how three generations of
Shazam frame names came to live in one library at once, each invisible to
the reader that expected another.

The frames are still written, and still what every other player reads.
What changed is who this program believes.

The whole library was measured before the switch: on 944 songs the
document and the frames agree on all seven fields, so nothing here should
have changed what a single file displays. These tests exist because
"nothing changed" is only reassuring if you can also show the two sources
are not simply the same source — hence the fixtures below, where the
document and the frames deliberately disagree.
"""

import asyncio
from pathlib import Path

import pytest
from mutagen.id3 import ID3, PRIV, TALB, TCON, TDRC, TPE1, TPUB, TSRC, TIT2, TXXX
from mutagen.mp3 import MP3

from pypl2mp3.libs import metadata
from pypl2mp3.libs.song import SongModel

_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413
PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"
VID = "aaaaaaaaaaa"


def _file(repo: Path, name=f"IAMX - Kiss [{VID}].mp3") -> Path:
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(_FRAME * 8)

    return path


def _old_frames(path: Path, **extra) -> ID3:
    """A file as builds before the document wrote it."""

    tags = ID3()
    tags.add(TXXX(encoding=3, desc="YouTube ID", text=VID))
    tags.add(TPE1(encoding=3, text=extra.get("artist", "Frames Artist")))
    tags.add(TIT2(encoding=3, text=extra.get("title", "Frames Title")))
    tags.save(path, v1=0, v2_version=3)

    return tags


class TestTheDocumentAnswersFirst:
    def test_a_field_is_read_from_the_document_and_not_from_its_frame(
        self, tmp_path
    ):
        """The two are made to disagree on purpose. Nothing in the real
        library disagrees — that was measured — so a fixture that agreed
        would pass whichever source was being read, and prove nothing."""

        path = _file(tmp_path)
        tags = _old_frames(path)

        document = metadata.set_field(
            metadata.blank(VID), "artist", "Document Artist", "user"
        )
        document = metadata.set_field(
            document, "title", "Document Title", "user"
        )
        metadata.attach(tags, document)
        tags.save(path, v1=0, v2_version=3)

        song = SongModel(path)

        assert song.artist == "Document Artist"
        assert song.title == "Document Title"

    def test_the_release_fields_come_from_the_document(self, tmp_path):
        path = _file(tmp_path)
        tags = _old_frames(path)
        tags.add(TALB(encoding=3, text="Frames Album"))
        tags.add(TPUB(encoding=3, text="Frames Label"))
        tags.add(TDRC(encoding=3, text="1999"))
        tags.add(TCON(encoding=3, text="Frames Genre"))

        document = metadata.blank(VID)

        for name, value in (
            ("album", "Document Album"),
            ("publisher", "Document Label"),
            ("year", "2007"),
            ("genre", "Document Genre"),
        ):
            document = metadata.set_field(document, name, value, "shazam")

        metadata.attach(tags, document)
        tags.save(path, v1=0, v2_version=3)

        song = SongModel(path)

        assert song.album == "Document Album"
        assert song.publisher == "Document Label"
        assert song.year == "2007"
        assert song.genre == "Document Genre"

    def test_what_shazam_said_comes_from_its_own_block(self, tmp_path):
        """Including the recording code, which is not a field: only
        Shazam supplies one, so it lives with the rest of the answer and
        not among the values the file asserts."""

        path = _file(tmp_path)
        tags = _old_frames(path)
        tags.add(TXXX(encoding=3, desc="Shazam artist", text="Frames Shazam"))
        tags.add(TXXX(encoding=3, desc="Shazam match level", text="12"))
        tags.add(TSRC(encoding=3, text="FRAME1234567"))

        document = metadata.set_source(
            metadata.blank(VID),
            "shazam",
            {
                "artist": "Document Shazam",
                "title": "Document Shazam Title",
                "cover": "https://img/doc.jpg",
                "score": 97,
                "isrc": "GBDHC1907207",
            },
        )
        metadata.attach(tags, document)
        tags.save(path, v1=0, v2_version=3)

        song = SongModel(path)

        assert song.shazam_artist == "Document Shazam"
        assert song.shazam_title == "Document Shazam Title"
        assert song.shazam_cover_art_url == "https://img/doc.jpg"
        assert song.shazam_match_score == 97
        assert song.isrc == "GBDHC1907207"


class TestWithoutADocument:
    def test_the_old_frames_still_answer(self, tmp_path):
        """A file from elsewhere, or one this program has not saved since
        the document existed. `legacy` turns its frames into the same
        shape, so the constructor asks one reader either way."""

        path = _file(tmp_path)
        tags = _old_frames(path)
        tags.add(TALB(encoding=3, text="Frames Album"))
        tags.add(TXXX(encoding=3, desc="Shazam artist", text="Frames Shazam"))
        tags.add(TXXX(encoding=3, desc="Shazam match level", text="88"))
        tags.save(path, v1=0, v2_version=3)

        assert metadata.read(path) is None

        song = SongModel(path)

        assert song.artist == "Frames Artist"
        assert song.title == "Frames Title"
        assert song.album == "Frames Album"
        assert song.shazam_artist == "Frames Shazam"
        assert song.shazam_match_score == 88

    def test_a_document_this_build_cannot_read_lets_the_frames_answer(
        self, tmp_path
    ):
        """Refusing to *write* an unreadable document protects whatever a
        newer build knew. Refusing to *read* one would break the song for
        no gain: the frames are still there and still true."""

        path = _file(tmp_path)
        tags = _old_frames(path)
        tags.add(PRIV(owner=metadata.OWNER, data=b'{"v": 99, "id": "x"}'))
        tags.save(path, v1=0, v2_version=3)

        song = SongModel(path)

        assert song.artist == "Frames Artist"

        # And it is still there afterwards, untouched.
        song.update_state(title="Kiss")

        stored = MP3(path).tags.getall("PRIV")
        mine = [one for one in stored if one.owner == metadata.OWNER]

        assert len(mine) == 1
        assert b'"v": 99' in mine[0].data


class TestTheEmbeddedPicture:
    def test_where_the_bytes_came_from_is_read_from_the_document(
        self, tmp_path
    ):
        path = _file(tmp_path)
        tags = _old_frames(path)
        tags.add(TXXX(
            encoding=3, desc="Stored cover art URL", text="https://img/old.jpg"
        ))

        document = metadata.set_embedded_cover(
            metadata.blank(VID), "3f9a", "https://img/new.jpg"
        )
        metadata.attach(tags, document)
        tags.save(path, v1=0, v2_version=3)

        assert SongModel(path).stored_cover_art_url == "https://img/new.jpg"

    def test_a_save_records_the_picture_the_file_actually_carries(
        self, tmp_path
    ):
        """The digest is taken from the bytes in the file, not from what
        anyone claimed to have put there."""

        import hashlib
        from mutagen.id3 import APIC

        path = _file(tmp_path)
        tags = _old_frames(path)
        tags.add(APIC(
            encoding=3, desc="Cover art", mime="image/jpg",
            type=3, data=b"picture-bytes",
        ))
        tags.save(path, v1=0, v2_version=3)

        SongModel(path).update_state(title="Kiss")

        embedded = metadata.read(path)["embedded"]

        assert embedded["cover_sha256"] == \
            hashlib.sha256(b"picture-bytes").hexdigest()

    def test_an_unchanged_picture_keeps_the_instant_it_was_recorded(
        self, tmp_path, monkeypatch
    ):
        """Rehashing the same bytes every save and stamping them anew
        would replace a real moment with this one, every time — the same
        reason an unchanged field keeps its entry.

        The clock is replaced because the real one has one-second
        resolution: two saves in the same second produce the same string,
        so this test passed with the rule removed. It proved nothing
        until the clock was made to tick on every call."""

        from mutagen.id3 import APIC

        ticks = iter(f"2026-01-01T00:00:{n:02d}Z" for n in range(60))
        monkeypatch.setattr(metadata, "now", lambda: next(ticks))

        path = _file(tmp_path)
        tags = _old_frames(path)
        tags.add(APIC(
            encoding=3, desc="Cover art", mime="image/jpg",
            type=3, data=b"picture-bytes",
        ))
        tags.save(path, v1=0, v2_version=3)

        SongModel(path).update_state(title="Kiss")
        first = metadata.read(path)["embedded"]["at"]

        SongModel(path).update_state(title="Kiss Again")
        second = metadata.read(path)["embedded"]["at"]

        assert first is not None
        assert second == first


class TestTheCoverSaveCarriesTheDocument:
    """Cover art is written by a save of its own, not by
    `update_id3_tags`. A save that left the document behind would leave
    the file claiming a picture it no longer carries — and that record is
    exactly what the next open trusts to decide whether to download."""

    def _catch(self, monkeypatch):
        import urllib.request

        jpeg = bytes.fromhex(
            "ffd8ffe000104a46494600010100000100010000ffdb004300"
            + "ff" * 64
            + "ffd9"
        )
        calls = []

        def fetch(url, filename, hook=None):
            calls.append(url)
            Path(filename).write_bytes(jpeg)
            return filename, None

        monkeypatch.setattr(urllib.request, "urlretrieve", fetch)

        return calls

    def test_a_downloaded_picture_is_recorded_in_the_same_write(
        self, tmp_path, monkeypatch
    ):
        calls = self._catch(monkeypatch)
        path = _file(tmp_path)
        _old_frames(path)

        song = SongModel(path)
        song.cover_art_url = "https://img/first.jpg"
        asyncio.run(song.update_cover_art())

        embedded = metadata.read(path)["embedded"]

        assert calls == ["https://img/first.jpg"]
        assert embedded["cover_url"] == "https://img/first.jpg"
        assert embedded["cover_sha256"]

    def test_the_record_is_what_stops_the_second_download(
        self, tmp_path, monkeypatch
    ):
        """Reopened from disk between the two, so the only thing carrying
        the answer across is the document the first save wrote."""

        calls = self._catch(monkeypatch)
        path = _file(tmp_path)
        _old_frames(path)

        first = SongModel(path)
        first.cover_art_url = "https://img/first.jpg"
        asyncio.run(first.update_cover_art())

        again = SongModel(path)

        assert again.stored_cover_art_url == "https://img/first.jpg"

        again.cover_art_url = "https://img/first.jpg"
        asyncio.run(again.update_cover_art())

        assert calls == ["https://img/first.jpg"]

    def test_removing_the_picture_is_recorded_too(
        self, tmp_path, monkeypatch
    ):
        self._catch(monkeypatch)
        path = _file(tmp_path)
        _old_frames(path)

        song = SongModel(path)
        song.cover_art_url = "https://img/first.jpg"
        asyncio.run(song.update_cover_art())

        song.cover_art_url = None
        asyncio.run(song.update_cover_art())

        embedded = metadata.read(path)["embedded"]

        assert embedded["cover_url"] == ""
        assert embedded["cover_sha256"] == ""


class TestTheTaggedProbe:
    def test_a_file_that_carries_nothing_is_tagged_on_first_open(
        self, tmp_path
    ):
        """The id lives only in the filename. This is a fresh download,
        and opening it is what tags it — a behaviour the switch must not
        lose, and would have, had the probe been asked of `_told`:
        `legacy` falls back to the filename too, so it would have
        answered "already tagged" for a file with no tags at all."""

        path = _file(tmp_path)

        song = SongModel(path)

        # A document, and no custom frame at all: the id used to be
        # written to `TXXX:YouTube ID` beside it, and that frame is what
        # this step removed. The id is at the root of the document, and
        # the filename carries it too.
        assert metadata.read(path) is not None
        assert metadata.read(path)["id"] == VID
        assert MP3(path).tags.getall("TXXX") == []
        assert song.artist == "IAMX"

    def test_a_document_this_build_cannot_read_still_counts_as_written(
        self, tmp_path
    ):
        """Otherwise every open rewrites the file, for ever: `_document`
        declines to overwrite what it cannot read, so nothing would ever
        make the probe say yes, and merely listing the library would
        rewrite it on every pass."""

        path = _file(tmp_path)

        # No id frame: this is the state after the cleanup, which is the
        # only state where this clause is the one answering. A first
        # version of this test kept the frame, and the legacy clause
        # rescued the probe — so it passed with the guard removed and
        # proved nothing.
        tags = ID3()
        tags.add(TPE1(encoding=3, text="Frames Artist"))
        tags.add(PRIV(owner=metadata.OWNER, data=b'{"v": 99, "id": "x"}'))
        tags.save(path, v1=0, v2_version=3)

        assert ID3(path).getall("TXXX") == []

        before = path.stat().st_mtime_ns

        SongModel(path)

        assert path.stat().st_mtime_ns == before, "reading rewrote the file"

    def test_saving_clears_the_custom_frames_it_no_longer_writes(
        self, tmp_path
    ):
        """The seven the model used to write, and the four older names
        it never wrote but the library still carried. `update_id3_tags`
        wipes every TXXX and puts none back, so a save is what cleans a
        file — and a pass over the library is what cleans the rest."""

        path = _file(tmp_path)
        tags = _old_frames(path)

        for desc in ("Cover art URL", "Stored cover art URL",
                     "Shazam artist", "Shazam matching artist",
                     "Shazam matching rate", "Foreign"):
            tags.add(TXXX(encoding=3, desc=desc, text="x"))

        tags.save(path, v1=0, v2_version=3)
        assert len(ID3(path).getall("TXXX")) == 7

        SongModel(path).update_state(title="Kiss")

        assert ID3(path).getall("TXXX") == []
        # And what mattered is still there, in the one frame that holds it.
        assert metadata.read(path)["id"] == VID

    def test_a_file_that_carries_a_document_is_not_retagged(self, tmp_path):
        """`update_id3_tags` clears every TXXX before rewriting the ones
        it knows, so a foreign one is the witness: if it survives, the
        constructor did not rewrite the file."""

        path = _file(tmp_path)
        tags = ID3()
        tags.add(TPE1(encoding=3, text="Frames Artist"))
        tags.add(TXXX(encoding=3, desc="Foreign", text="witness"))
        metadata.attach(tags, metadata.blank(VID))
        tags.save(path, v1=0, v2_version=3)

        SongModel(path)

        assert MP3(path).tags["TXXX:Foreign"].text[0] == "witness"


class TestJunking:
    """Junking clears the frames. Before the switch that was the end of
    it, because nothing read anything else. Now the document has to
    follow, or the next open reads the old name straight back out of it
    and the song is not junk at all."""

    def _sung(self, tmp_path):
        path = _file(tmp_path)
        _old_frames(path)

        song = SongModel(path)
        song.update_state(artist="IAMX", title="Kiss", by="shazam")
        song.shazam_artist = "IAMX"
        song.shazam_match_score = 97
        song.update_id3_tags()

        return path, song

    def test_the_document_is_cleared_with_the_frames(self, tmp_path):
        path, song = self._sung(tmp_path)

        assert metadata.value(metadata.read(path), "artist") == "IAMX"

        song.reset_state()

        document = metadata.read(path)

        assert document["fields"] == {}
        assert document["sources"]["shazam"] == {}
        assert SongModel(path).artist == "IAMX"  # from the filename, as before
        assert SongModel(path).shazam_artist is None

    def test_where_the_file_came_from_survives_it(self, tmp_path):
        """The one thing junking never claimed to undo. `sources.youtube`
        is the video's own title and channel — irreplaceable once the
        video is gone, and not a conclusion anybody drew about the song.
        A pass was run to recover it before the videos disappeared; it
        would be poor form to throw it away here."""

        path, song = self._sung(tmp_path)

        tags = ID3(path)
        document = metadata.set_source(
            metadata.of(tags),
            "youtube",
            {"author": "corandcrank", "title": "corandcrank - Amor Mio"},
        )
        metadata.attach(tags, document)
        tags.save(path, v1=0, v2_version=3)

        SongModel(path).reset_state()

        origin = metadata.read(path)["sources"]["youtube"]

        assert origin["author"] == "corandcrank"
        assert origin["title"] == "corandcrank - Amor Mio"


    def test_the_signal_is_spent_once(self, tmp_path, monkeypatch):
        """A latch left raised makes every later save on the same object
        erase the document again. The damage is not visible in the values
        — they are rewritten from the attributes straight after — but in
        everything the erasure takes with it: when each value was decided,
        by whom, and the Shazam identifiers, which live in the stored
        block and nowhere else.

        The provenance stamp is the witness. Re-created, it moves."""

        path, song = self._sung(tmp_path)
        song.reset_state()

        ticks = iter(f"2026-01-01T00:00:{n:02d}Z" for n in range(60))
        monkeypatch.setattr(metadata, "now", lambda: next(ticks))

        song.update_state(artist="Corrected", by="user")
        first = metadata.field(metadata.read(path), "artist")["at"]

        song.update_state(title="By Hand", by="user")
        second = metadata.field(metadata.read(path), "artist")["at"]

        assert first is not None
        assert second == first


class TestReinitialization:
    def test_the_new_state_is_not_overwritten_by_what_the_file_says(
        self, tmp_path
    ):
        """`update_state` deliberately re-calls the constructor, carrying
        the new state on the object. Reading the file again there would
        put the old values straight back over it."""

        path = _file(tmp_path)
        tags = _old_frames(path)
        document = metadata.set_field(
            metadata.blank(VID), "artist", "Document Artist", "user"
        )
        metadata.attach(tags, document)
        tags.save(path, v1=0, v2_version=3)

        song = SongModel(path)
        song.update_state(artist="Typed By Hand", by="user")

        assert song.artist == "Typed By Hand"
        assert metadata.value(metadata.read(path), "artist") == "Typed By Hand"
