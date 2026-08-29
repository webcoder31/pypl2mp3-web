"""What is recorded about a video, and the three states it can be in.

The fetching is YouTube's and the writing is the document's, both covered
elsewhere. What this decides is how an answer — or a refusal, or a
failure — becomes something the file will still make sense of in a year.
"""

import importlib.util
from pathlib import Path

import pytest
from mutagen.id3 import ID3, TPE1, TXXX

from pypl2mp3.libs import metadata

WHEN = "2026-08-29T12:00:00Z"
_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413
PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"


@pytest.fixture(scope="module")
def script():
    path = Path("scripts/recover_youtube_origin.py")
    spec = importlib.util.spec_from_file_location("recover", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _song(repo: Path, vid="aaaaaaaaaaa", document=None):
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"IAMX - Kiss [{vid}].mp3"
    path.write_bytes(_FRAME * 8)

    tags = ID3()
    tags.add(TXXX(encoding=3, desc="YouTube ID", text=vid))
    tags.add(TPE1(encoding=3, text="IAMX"))
    tags.save(path, v1=0, v2_version=3)

    if document is not None:
        metadata.write(path, document)

    return path


class TestWhatIsRecorded:
    def test_an_answer_keeps_the_channel_and_the_video_title(self, script):
        """Exactly what the import took and threw away: `author_name` is
        `video.author` and `title` is `video.title`."""

        learnt = script.origin(
            {"author_name": "IAMX", "title": "IAMX - Kiss (official)",
             "author_url": "https://www.youtube.com/channel/UC1"},
            200, WHEN,
        )

        assert learnt == {
            "author": "IAMX",
            "title": "IAMX - Kiss (official)",
            "channel": "https://www.youtube.com/channel/UC1",
        }

    def test_the_topic_suffix_is_kept_as_given(self, script):
        """YouTube appends " - Topic" to its auto-generated music
        channels. This block is evidence; trimming it would be a decision
        made in the wrong place, and the decision belongs to whoever
        adopts the value."""

        learnt = script.origin(
            {"author_name": "IAMX - Topic", "title": "Kiss"}, 200, WHEN
        )

        assert learnt["author"] == "IAMX - Topic"

    def test_a_missing_video_is_recorded_as_missing(self, script):
        """The third state, and the reason the block exists. Without it
        every later pass re-asks the same dead videos and fails the same
        way, unable to tell "not done yet" from "cannot be done"."""

        assert script.origin(None, 404, WHEN) == {"gone": True, "http": 404}

    def test_the_status_is_kept_because_they_differ(self, script):
        """A 404 is a deletion, a 401 a video made private, a 403 a
        regional block. The last two can reopen; recording only "gone"
        would lose that."""

        for code in (401, 403, 410):
            assert script.origin(None, code, WHEN)["http"] == code

    def test_a_failed_request_records_nothing(self, script):
        """The network being down is not the video being gone, and
        writing one as the other would mark a recoverable song as lost
        for good."""

        assert script.origin(None, None, WHEN) is None

    def test_an_unexpected_status_records_nothing(self, script):
        """A 500 is YouTube having a bad day. The song stays a
        candidate."""

        assert script.origin(None, 500, WHEN) is None
        assert script.origin(None, 429, WHEN) is None


class TestTheRun:
    def _run(self, script, monkeypatch, tmp_path, answers, extra=()):
        calls = []

        def fake(video_id):
            calls.append(video_id)
            return answers[video_id]

        monkeypatch.setattr(script, "fetch", fake)
        monkeypatch.setattr(script, "PAUSE", 0)
        monkeypatch.setattr(
            "sys.argv",
            ["recover", "--repository", str(tmp_path), *extra],
        )
        script.main()
        return calls

    def test_an_answer_reaches_the_document(
        self, script, monkeypatch, tmp_path
    ):
        path = _song(tmp_path, document=metadata.blank("aaaaaaaaaaa"))

        self._run(script, monkeypatch, tmp_path, {
            "aaaaaaaaaaa": ({"author_name": "IAMX", "title": "Kiss"}, 200),
        })

        stored = metadata.read(path)["sources"]["youtube"]

        assert stored["author"] == "IAMX"
        assert stored["at"] is not None

    def test_a_song_already_asked_about_is_not_asked_again(
        self, script, monkeypatch, tmp_path
    ):
        """Resumable without a state file: what the document holds is the
        record of what has been done."""

        document = metadata.set_source(
            metadata.blank("aaaaaaaaaaa"), "youtube",
            {"author": "IAMX", "title": "Kiss"}, at=WHEN,
        )
        _song(tmp_path, document=document)

        calls = self._run(script, monkeypatch, tmp_path, {})

        assert calls == []

    def test_a_missing_video_is_not_asked_about_again_either(
        self, script, monkeypatch, tmp_path
    ):
        document = metadata.set_source(
            metadata.blank("aaaaaaaaaaa"), "youtube",
            {"gone": True, "http": 404}, at=WHEN,
        )
        _song(tmp_path, document=document)

        assert self._run(script, monkeypatch, tmp_path, {}) == []

    def test_unless_asked_to_retry_them(self, script, monkeypatch, tmp_path):
        """A 401 or a 403 can reopen. A 404 will not, but sorting them out
        is the caller's business, not this script's."""

        document = metadata.set_source(
            metadata.blank("aaaaaaaaaaa"), "youtube",
            {"gone": True, "http": 403}, at=WHEN,
        )
        path = _song(tmp_path, document=document)

        self._run(script, monkeypatch, tmp_path, {
            "aaaaaaaaaaa": ({"author_name": "IAMX", "title": "Kiss"}, 200),
        }, extra=["--retry-gone"])

        assert metadata.read(path)["sources"]["youtube"]["author"] == "IAMX"

    def test_a_dry_run_writes_nothing(self, script, monkeypatch, tmp_path):
        path = _song(tmp_path, document=metadata.blank("aaaaaaaaaaa"))
        before = path.stat().st_mtime_ns

        self._run(script, monkeypatch, tmp_path, {
            "aaaaaaaaaaa": ({"author_name": "IAMX", "title": "Kiss"}, 200),
        }, extra=["--dry-run"])

        assert path.stat().st_mtime_ns == before
        assert metadata.read(path)["sources"]["youtube"] == {}

    def test_a_song_with_no_document_is_left_for_the_builder(
        self, script, monkeypatch, tmp_path
    ):
        """Creating one here would duplicate the build script and put two
        writers on the same shape."""

        path = _song(tmp_path)

        assert self._run(script, monkeypatch, tmp_path, {}) == []
        assert metadata.read(path) is None

    def test_nothing_is_written_when_the_request_fails(
        self, script, monkeypatch, tmp_path
    ):
        path = _song(tmp_path, document=metadata.blank("aaaaaaaaaaa"))

        self._run(script, monkeypatch, tmp_path, {
            "aaaaaaaaaaa": (None, None),
        })

        assert metadata.read(path)["sources"]["youtube"] == {}
