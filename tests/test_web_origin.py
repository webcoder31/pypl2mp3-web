"""What the file came from, and whether the video is still there.

Both live in the document and nowhere else. The import takes the video's
channel and title, Shazam overwrites them, and on 652 of 944 songs the
name on screen is not the name the video had — so this is the only place
the original survives. Eleven videos have since gone; the link to them
answered 404 without saying so.

Neither is editable. They are evidence, and the panel shows them the way
it shows a duration: read, never typed.
"""

import re
from pathlib import Path

import httpx
import pytest
from mutagen.id3 import ID3, TPE1, TIT2, TXXX

from pypl2mp3.libs import metadata
from pypl2mp3.services.list_songs import SongSummary, summarize
from pypl2mp3.libs.song import SongModel
from pypl2mp3.web.app import create_app

HX = {"HX-Request": "true"}


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )

_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413
PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"


def _song(repo: Path, vid="aaaaaaaaaaa", origin=None) -> Path:
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"IAMX - Kiss {vid} [{vid}].mp3"
    path.write_bytes(_FRAME * 8)

    tags = ID3()
    tags.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
    tags.add(TPE1(encoding=3, text="IAMX"))
    tags.add(TIT2(encoding=3, text="Kiss"))

    document = metadata.blank(vid)

    if origin is not None:
        document = metadata.set_source(document, "youtube", origin)

    metadata.attach(tags, document)
    tags.save(path, v1=0, v2_version=3)

    return path


class TestTheModelCarriesIt:
    def test_the_origin_is_read_from_the_document(self, tmp_path):
        path = _song(tmp_path, origin={
            "author": "corandcrank",
            "channel": "https://www.youtube.com/@corandcrank",
            "title": "corandcrank - Amor Mio",
        })

        song = SongModel(path)

        assert song.youtube_origin["author"] == "corandcrank"
        assert song.youtube_origin["title"] == "corandcrank - Amor Mio"

    def test_a_file_that_was_never_asked_has_none(self, tmp_path):
        assert SongModel(_song(tmp_path)).youtube_origin == {}

    def test_it_survives_a_save(self, tmp_path):
        """`update_state` re-calls the constructor, which does not read
        the file again — so anything read once has to be carried, not
        rediscovered."""

        path = _song(tmp_path, origin={"author": "c", "title": "t"})

        song = SongModel(path)
        song.update_state(title="Kiss Again", by="user")

        assert song.youtube_origin["author"] == "c"


class TestTheLine:
    def test_it_names_the_channel_before_the_video(self):
        summary = SongSummary(
            path=Path("x.mp3"), youtube_id="a", artist="A", title="T",
            playlist=PLAYLIST, duration="00:03:00", is_junk=False,
            origin_author="corandcrank", origin_title="Amor Mio",
        )

        assert summary.origin == "From: corandcrank · Amor Mio"

    def test_every_face_says_what_it_is(self):
        """They were told apart by their shape while there were two of
        them, and that stopped working at four: a middot-joined line
        could be a release, an origin, or a recording code opened out.
        "Chill Masters · SYNAPSON - Djon Maya Maï" reads exactly like a
        label and an album."""

        summary = SongSummary(
            path=Path("x.mp3"), youtube_id="a", artist="A", title="T",
            playlist=PLAYLIST, duration="00:03:00", is_junk=False,
            album="Album", year="1971", isrc="FRZ031900123",
            origin_author="Chill Masters", origin_title="SYNAPSON",
        )

        assert summary.release.startswith("Album: ")
        assert summary.recording.startswith("Release (ISRC): ")
        assert summary.playlist_face.startswith("Playlist: ")
        assert summary.origin.startswith("From: ")

    def test_nothing_known_is_no_line_at_all(self):
        """An empty face would still take its ten seconds on the board."""

        summary = SongSummary(
            path=Path("x.mp3"), youtube_id="a", artist="A", title="T",
            playlist=PLAYLIST, duration="00:03:00", is_junk=False,
        )

        assert summary.origin == ""

    def test_a_gone_video_has_no_line(self, tmp_path):
        """It has no title and no channel to show — only the record that
        asking cost a 404. The mark on the link is what says so."""

        path = _song(tmp_path, origin={"gone": True, "http": 404})
        summary = summarize(SongModel(path))

        assert summary.origin == ""
        assert summary.video_gone is True


class TestTheTemplates:
    def _markup(self, name):
        return (Path("src/pypl2mp3/web/templates") / name).read_text()

    @pytest.mark.parametrize("name", ["_inspector.html", "_workbench.html"])
    def test_the_board_turns_its_faces_in_the_written_order(self, name):
        """Release, recording code, playlist, origin. The attribute order
        in the markup is the turning order — the page reads them in the
        order they are written — so this holds the markup to it."""

        markup = self._markup(name)
        board = re.search(r'<span class="board"(.*?)>', markup, re.DOTALL).group(1)
        seen = re.findall(r"data-(release|recording|playlist|origin)=", board)

        assert seen == ["release", "recording", "playlist", "origin"], seen
        # Only when there is one: the board turns to every face it is
        # given, and an empty one is ten seconds of nothing. The playlist
        # is the exception, because every song has one.
        for face in ("release", "recording", "origin"):
            assert f"song.{face if face != 'release' else 'release'} %}}" in markup \
                or f"if song.{face}" in markup, f"{face} is unconditional"

    async def test_a_gone_video_is_marked_and_still_linked(self, tmp_path):
        """Asked of the rendered page and not of the template source: a
        first version of this test looked for "song.video_gone" anywhere
        inside the link, which the warning sign at its end satisfies on
        its own. Disabling the class changed nothing and the test held.

        Kept rather than removed, the link: a video pulled for a regional
        block or set to private can come back, and the address is the
        only way to find out. Three of the eleven answered 401 or 403,
        which are exactly those cases."""

        _song(tmp_path, vid="aaaaaaaaaaa",
              origin={"gone": True, "http": 404})
        _song(tmp_path, vid="bbbbbbbbbbb",
              origin={"author": "c", "title": "t"})

        async with _client(create_app(tmp_path)) as client:
            gone = (await client.get(
                "/fragments/inspector/aaaaaaaaaaa", headers=HX)).text
            alive = (await client.get(
                "/fragments/inspector/bbbbbbbbbbb", headers=HX)).text

        for markup, expected in ((gone, True), (alive, False)):
            link = re.search(
                r'<a href="https://youtu\.be/[^"]+"[^>]*>.*?</a>',
                markup, re.DOTALL,
            )

            assert link, "the video link is gone from the inspector"
            assert ('class="gone"' in link.group(0)) is expected, link.group(0)


class TestTheBoardIsBounded:
    def test_a_face_is_cut_to_the_room_the_line_has(self):
        """Nothing bounds a face. A release line reached 144 characters
        and a video title 126, against a panel that holds about sixty:
        rendered whole they ran out under the column beside them and gave
        the page a horizontal scrollbar — 1118 pixels of board inside 469
        pixels of line, measured in a browser.

        Both numbers are read at render time. The board is monospace but
        its size is em-relative, so a character is only as wide as this
        panel makes it."""

        js = Path("src/pypl2mp3/web/static/console.js").read_text()
        show = re.search(
            r"function showFace\(board, text, turning\) \{(.*?)\n  \}",
            js, re.DOTALL,
        ).group(1)

        assert "boardRoom(board)" in show, show[:400]
        assert "Math.min(" in show, show[:400]
        assert "text = fit(text, width);" in show, show[:400]

        room = re.search(
            r"function boardRoom\(board\) \{(.*?)\n  \}", js, re.DOTALL
        ).group(1)

        assert "getBoundingClientRect" in room
        assert "line.getBoundingClientRect().right" in room, (
            "the room is measured from the board's own left edge, so "
            "whatever shares the line before it is accounted for"
        )

    def test_what_was_cut_says_so(self):
        js = Path("src/pypl2mp3/web/static/console.js").read_text()
        cut = re.search(r"function fit\(face, width\) \{(.*?)\n  \}",
                        js, re.DOTALL).group(1)

        assert "…" in cut, cut
        assert "width - 1" in cut, "the ellipsis has to fit inside the room"


class TestWhatWasTypedRatherThanFound:
    """The warning that was missing in front of Ask Shazam.

    A match overwrites artist, title and cover without asking, and a
    value somebody typed is the one thing in the file that asking again
    cannot bring back — which is why the backfill had to work around it
    by refusing to call `shazam_song` at all.
    """

    def test_the_model_reads_who_decided_each_value(self, tmp_path):
        path = _song(tmp_path)

        SongModel(path).update_state(
            artist="Typed Artist", title="Typed Title", by="user"
        )

        assert SongModel(path).decided_by["title"] == "user"
        assert SongModel(path).decided_by["artist"] == "user"

    def test_a_save_claims_the_values_it_actually_writes(self, tmp_path):
        """The setter describes the act, and the act is what got written.

        A field nothing had ever claimed becomes the user's: they looked
        at what the panel had guessed from the filename and pressed Save,
        which is an assertion. A field that already carried an entry and
        did not change keeps it — the rule that an unchanged value holds
        on to the moment it was decided outranks this, and it should. It
        is the difference between "I typed this" and "I did not object to
        it", and only the first is worth warning about."""

        path = _song(tmp_path)

        # Nothing has ever claimed either field here.
        SongModel(path).update_state(title="Typed", by="user")

        assert SongModel(path).decided_by["artist"] == "user"

    def test_leaving_a_claimed_value_alone_does_not_claim_it(self, tmp_path):
        """Found on the real library: saving a song without changing
        anything left every setter where it was. Shazam decided those
        values and the user merely did not object — marking them would
        make the warning fire on songs nobody has corrected, which is
        every song there is."""

        path = _song(tmp_path)

        song = SongModel(path)
        song.update_state(artist="Found", title="Found", by="shazam")
        # The form, resubmitted unchanged.
        song.update_state(artist="Found", title="Found", by="user")

        assert SongModel(path).decided_by["artist"] == "shazam"
        assert summarize(SongModel(path)).by_hand == ""

    def test_it_survives_a_save(self, tmp_path):
        """`update_state` re-calls the constructor, which does not read
        the file again. Anything read once has to be carried."""

        path = _song(tmp_path)

        song = SongModel(path)
        song.update_state(artist="Typed", by="user")
        song.update_state(title="Also Typed", by="user")

        assert song.decided_by["artist"] == "user"

    def test_only_what_was_typed_is_named(self, tmp_path):
        """A field Shazam decided is not the user's, and saying it is
        would make the warning meaningless — every song would carry it."""

        path = _song(tmp_path)

        song = SongModel(path)
        song.update_state(album="Found By Shazam", by="shazam")
        song.update_state(title="Typed", artist="Typed", by="user")

        summary = summarize(SongModel(path))

        assert SongModel(path).decided_by["album"] == "shazam"
        assert "album" not in summary.set_by_hand
        assert set(summary.set_by_hand) == {"artist", "title"}

    def test_the_order_is_the_panel_order_not_the_writing_order(
        self, tmp_path
    ):
        """A sentence that reorders itself between two saves reads as a
        different sentence. The document remembers when each field was
        written, and that is not the order the eye reads them in."""

        path = _song(tmp_path)

        song = SongModel(path)
        # Deliberately backwards: cover, then title, then artist.
        song.update_state(cover_art_url="https://img/one.jpg", by="user")
        song.update_state(title="Typed", by="user")
        song.update_state(artist="Typed", by="user")

        summary = summarize(SongModel(path))

        assert summary.set_by_hand == ("artist", "title", "cover")

    def test_one_field_is_named_in_the_singular(self):
        summary = SongSummary(
            path=Path("x.mp3"), youtube_id="a", artist="A", title="T",
            playlist=PLAYLIST, duration="00:03:00", is_junk=False,
            set_by_hand=("title",),
        )

        assert summary.by_hand == (
            "title set by hand — Ask Shazam would replace it"
        )

    def test_several_are_listed_in_the_order_the_panel_shows_them(self):
        """Not in the order they happened to be written: a sentence that
        reorders itself between two saves reads as a different sentence."""

        summary = SongSummary(
            path=Path("x.mp3"), youtube_id="a", artist="A", title="T",
            playlist=PLAYLIST, duration="00:03:00", is_junk=False,
            set_by_hand=("artist", "title", "cover"),
        )

        assert summary.by_hand == (
            "artist, title and cover set by hand — "
            "Ask Shazam would replace them"
        )

    def test_nothing_typed_is_no_line_at_all(self):
        """Which is every song in the library today: on 5 918 fields,
        4 392 are `legacy` and 1 526 `shazam`, and none is `user`. The
        line fills in with use, not before."""

        summary = SongSummary(
            path=Path("x.mp3"), youtube_id="a", artist="A", title="T",
            playlist=PLAYLIST, duration="00:03:00", is_junk=False,
        )

        assert summary.by_hand == ""

    async def test_the_panel_shows_it_only_where_there_is_one(self, tmp_path):
        """Asked of the rendered page: a template test would pass on
        markup the reader never receives."""

        _song(tmp_path, vid="aaaaaaaaaaa")
        _song(tmp_path, vid="bbbbbbbbbbb")

        typed = tmp_path / PLAYLIST / "IAMX - Kiss aaaaaaaaaaa [aaaaaaaaaaa].mp3"
        SongModel(typed).update_state(title="Typed By Hand", by="user")

        async with _client(create_app(tmp_path)) as client:
            marked = (await client.get(
                "/fragments/inspector/aaaaaaaaaaa", headers=HX)).text
            plain = (await client.get(
                "/fragments/inspector/bbbbbbbbbbb", headers=HX)).text

        assert "set by hand" in marked
        assert "Ask Shazam would replace" in marked
        assert "set by hand" not in plain
        # The element itself, not only its words: an empty paragraph
        # rendered unconditionally passes a test that only looks for the
        # sentence, and leaves a blank line of margin above the fields.
        assert 'class="by-hand"' in marked
        assert 'class="by-hand"' not in plain

    async def test_junking_takes_the_line_away_with_the_values(self, tmp_path):
        """`reset_state` clears the document, so a junked song is no
        longer carrying anything anybody typed — and saying it still is
        would be the panel lying about what is at stake."""

        _song(tmp_path, vid="aaaaaaaaaaa")
        path = tmp_path / PLAYLIST / "IAMX - Kiss aaaaaaaaaaa [aaaaaaaaaaa].mp3"

        song = SongModel(path)
        song.update_state(title="Typed By Hand", by="user")
        song.reset_state()

        async with _client(create_app(tmp_path)) as client:
            markup = (await client.get(
                "/fragments/inspector/aaaaaaaaaaa", headers=HX)).text

        assert "set by hand" not in markup


class TestTheTurningOrder:
    async def test_the_page_turns_them_in_the_same_order_as_the_markup(
        self, tmp_path
    ):
        """The markup's attribute order is what a reader sees written
        down; `boardFaces` is what actually decides. A first version of
        this only held the template, so swapping the array in the script
        changed the order on screen and nothing failed."""

        async with _client(create_app(tmp_path)) as client:
            js = (await client.get("/static/console.js")).text

        faces = re.search(
            r"function boardFaces\(board\) \{(.*?)\n  \}", js, re.DOTALL
        ).group(1)
        read = re.findall(r"board\.dataset\.(\w+)", faces)

        assert read == ["release", "recording", "playlist", "origin"], read

    async def test_an_empty_face_is_dropped_rather_than_shown(self, tmp_path):
        """Ten seconds of a blank line is worse than three faces."""

        async with _client(create_app(tmp_path)) as client:
            js = (await client.get("/static/console.js")).text

        faces = re.search(
            r"function boardFaces\(board\) \{(.*?)\n  \}", js, re.DOTALL
        ).group(1)

        assert ".filter(" in faces and 'face !== ""' in faces, faces


class TestTheRecordingFace:
    """`FRZ031900123` is four things run together and nobody reads it as
    four. Opened out, it becomes something the eye can use."""

    def _summary(self, isrc):
        return SongSummary(
            path=Path("x.mp3"), youtube_id="a", artist="A", title="T",
            playlist=PLAYLIST, duration="00:03:00", is_junk=False, isrc=isrc,
        )

    def test_it_reads_country_year_registrant_number(self):
        assert self._summary("FRZ031900123").recording == (
            "Release (ISRC): FR · 2019 · Z03 · 00123"
        )

    def test_the_separators_a_code_may_carry_are_not_part_of_it(self):
        """The standard writes it with hyphens and files store it
        without. Both are the same code."""

        assert self._summary("FR-Z03-19-00123").recording == (
            self._summary("FRZ031900123").recording
        )

    def test_a_year_the_standard_predates_is_shown_as_written(self):
        """38 codes here carry a year earlier than 1986, when the
        standard did not exist: the field is whatever the registrant put
        there, usually the recording's own year. A 1973 code on a 2025
        release is the point, not a bug — the reissue kept the take."""

        assert "1973" in self._summary("FR77F7300790").recording

    def test_nothing_to_say_takes_no_turn(self):
        assert self._summary("").recording == ""

    def test_a_code_that_is_not_one_is_shown_rather_than_parsed(self):
        """Splitting it would invent four parts out of something that has
        none. Shown whole, it is at least visibly wrong."""

        assert self._summary("NOT A CODE").recording == (
            "Release (ISRC): NOT A CODE"
        )
