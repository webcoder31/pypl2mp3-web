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

        assert summary.origin == "from corandcrank · Amor Mio"

    def test_it_is_prefixed_where_the_release_line_is_not(self):
        """The board gives its faces no labels, and both lines are
        middot-joined: "Chill Masters · SYNAPSON - Djon Maya Maï" reads
        exactly like a label and an album. Five characters buy the
        distinction."""

        summary = SongSummary(
            path=Path("x.mp3"), youtube_id="a", artist="A", title="T",
            playlist=PLAYLIST, duration="00:03:00", is_junk=False,
            album="Album", year="1971",
            origin_author="Chill Masters", origin_title="SYNAPSON",
        )

        assert summary.release.startswith("Album")
        assert summary.origin.startswith("from ")

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
    def test_the_board_is_given_a_third_face(self, name):
        markup = self._markup(name)

        assert 'data-origin="{{ song.origin }}"' in markup, name
        # Only when there is one: the board turns to every face it is
        # given, and an empty one is ten seconds of nothing.
        assert "{% if song.origin %} data-origin" in markup, name

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
