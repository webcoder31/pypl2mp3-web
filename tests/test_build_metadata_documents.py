"""The merge rule, which is the only place this script makes a decision.

Reading the frames and reading the document are covered elsewhere. What
is decided here is what to keep when the two disagree — and getting that
wrong would overwrite hand edits with values recovered from frames that
never recorded who made them.
"""

import importlib.util
import re
from pathlib import Path

import pytest

from pypl2mp3.libs import metadata

WHEN = "2026-08-29T12:00:00Z"


@pytest.fixture(scope="module")
def script():
    path = Path("scripts/build_metadata_documents.py")
    spec = importlib.util.spec_from_file_location("build_docs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _doc(**fields):
    document = metadata.blank("aaaaaaaaaaa")
    for name, (value, by, at) in fields.items():
        document = metadata.set_field(document, name, value, by, at=at)
    return document


class TestMerge:
    def test_a_song_with_no_document_takes_the_rebuild_whole(self, script):
        rebuilt = _doc(title=("Kiss", "legacy", None))

        assert script.merge(None, rebuilt) == rebuilt

    def test_a_hand_edit_outranks_the_frames(self, script):
        """The whole reason the document exists. A rebuild can only ever
        produce "shazam" or "legacy" — it reads the frames, and the frames
        record no hand edits — so anything marked as a person's decision
        wins."""

        stored = _doc(title=("My Title", "user", WHEN))
        rebuilt = _doc(title=("Shazam Title", "shazam", None))

        merged = script.merge(stored, rebuilt)

        assert merged["fields"]["title"] == {
            "value": "My Title", "by": "user", "at": WHEN,
        }

    def test_anything_else_takes_the_newer_frames(self, script):
        """During the shadow phase the frames are still the source of
        truth: the running application writes them and knows nothing about
        the document."""

        stored = _doc(title=("Old", "legacy", None))
        rebuilt = _doc(title=("New", "legacy", None))

        assert script.merge(stored, rebuilt)["fields"]["title"]["value"] == "New"

    def test_an_unchanged_value_keeps_the_entry_that_knows_its_moment(
        self, script
    ):
        """A rebuild's timestamps are all null. Replacing a real moment
        with a null one would lose the only thing the document knows that
        the frames never did."""

        stored = _doc(title=("Kiss", "shazam", WHEN))
        rebuilt = _doc(title=("Kiss", "legacy", None))

        merged = script.merge(stored, rebuilt)

        assert merged["fields"]["title"] == {
            "value": "Kiss", "by": "shazam", "at": WHEN,
        }

    def test_a_field_the_document_never_had_is_added(self, script):
        stored = _doc(title=("Kiss", "user", WHEN))
        rebuilt = _doc(title=("Kiss", "legacy", None),
                       album=("Album", "legacy", None))

        merged = script.merge(stored, rebuilt)

        assert merged["fields"]["album"]["value"] == "Album"
        assert merged["fields"]["title"]["by"] == "user"

    def test_a_source_already_recorded_is_not_replaced(self, script):
        """What an upstream answered is evidence, and the stored one may
        carry a real timestamp the rebuild cannot know."""

        stored = metadata.set_source(
            metadata.blank("a"), "shazam", {"artist": "IAMX"}, at=WHEN
        )
        rebuilt = metadata.set_source(
            metadata.blank("a"), "shazam", {"artist": "IAMX"}, at=None
        )

        assert script.merge(stored, rebuilt)["sources"]["shazam"]["at"] == WHEN

    def test_a_source_the_document_never_had_is_taken(self, script):
        stored = metadata.blank("a")
        rebuilt = metadata.set_source(
            metadata.blank("a"), "shazam", {"artist": "IAMX"}, at=None
        )

        assert script.merge(stored, rebuilt)["sources"]["shazam"]["artist"] == (
            "IAMX"
        )

    def test_merging_leaves_both_arguments_alone(self, script):
        stored = _doc(title=("Old", "legacy", None))
        rebuilt = _doc(title=("New", "legacy", None))

        script.merge(stored, rebuilt)

        assert stored["fields"]["title"]["value"] == "Old"
        assert rebuilt["fields"]["title"]["value"] == "New"


class TestDivergence:
    def test_only_values_are_compared(self, script):
        """The setters and the timestamps are expected to differ — a
        rebuild has no way to know either — and reporting that as drift
        would bury the one difference worth looking at."""

        stored = _doc(title=("Kiss", "user", WHEN))
        rebuilt = _doc(title=("Kiss", "legacy", None))

        assert script.divergence(stored, rebuilt) == []

    def test_a_changed_value_is_reported_with_both_sides(self, script):
        stored = _doc(title=("Old", "legacy", None))
        rebuilt = _doc(title=("New", "legacy", None))

        assert script.divergence(stored, rebuilt) == [("title", "Old", "New")]

    def test_a_field_gained_or_lost_counts_as_drift(self, script):
        stored = metadata.blank("a")
        rebuilt = _doc(album=("Album", "legacy", None))

        assert script.divergence(stored, rebuilt) == [("album", "", "Album")]


class TestOnRealFiles:
    def test_reporting_writes_nothing(self, script, tmp_path, monkeypatch):
        """Read-only by default: the report has to be safe to run at any
        time, including while the application is in use."""

        from mutagen.id3 import ID3, TPE1, TXXX

        folder = tmp_path / "Owner - Alpha [PL0000000000000000000000000000001]"
        folder.mkdir(parents=True)
        path = folder / "IAMX - Kiss [aaaaaaaaaaa].mp3"
        path.write_bytes((b"\xff\xfb\x90\xc0" + b"\x00" * 413) * 8)

        tags = ID3()
        tags.add(TXXX(encoding=3, desc="YouTube ID", text="aaaaaaaaaaa"))
        tags.add(TPE1(encoding=3, text="IAMX"))
        tags.save(path, v1=0, v2_version=3)

        before = path.stat().st_mtime_ns, path.stat().st_size

        monkeypatch.setattr(
            "sys.argv", ["build", "--repository", str(tmp_path)]
        )
        script.main()

        assert (path.stat().st_mtime_ns, path.stat().st_size) == before
        assert metadata.read(path) is None

    def test_writing_stores_a_document_that_reads_back(
        self, script, tmp_path, monkeypatch
    ):
        from mutagen.id3 import ID3, TPE1, TXXX

        folder = tmp_path / "Owner - Alpha [PL0000000000000000000000000000001]"
        folder.mkdir(parents=True)
        path = folder / "IAMX - Kiss [aaaaaaaaaaa].mp3"
        path.write_bytes((b"\xff\xfb\x90\xc0" + b"\x00" * 413) * 8)

        tags = ID3()
        tags.add(TXXX(encoding=3, desc="YouTube ID", text="aaaaaaaaaaa"))
        tags.add(TPE1(encoding=3, text="IAMX"))
        tags.save(path, v1=0, v2_version=3)

        monkeypatch.setattr(
            "sys.argv", ["build", "--repository", str(tmp_path), "--write"]
        )
        script.main()

        document = metadata.read(path)

        assert document is not None
        assert metadata.value(document, "artist") == "IAMX"

    def test_running_it_twice_writes_nothing_the_second_time(
        self, script, tmp_path, monkeypatch, capsys
    ):
        """Idempotent, so it can be re-run before a switch without
        moving 944 timestamps for nothing."""

        from mutagen.id3 import ID3, TPE1, TXXX

        folder = tmp_path / "Owner - Alpha [PL0000000000000000000000000000001]"
        folder.mkdir(parents=True)
        path = folder / "IAMX - Kiss [aaaaaaaaaaa].mp3"
        path.write_bytes((b"\xff\xfb\x90\xc0" + b"\x00" * 413) * 8)

        tags = ID3()
        tags.add(TXXX(encoding=3, desc="YouTube ID", text="aaaaaaaaaaa"))
        tags.add(TPE1(encoding=3, text="IAMX"))
        tags.save(path, v1=0, v2_version=3)

        monkeypatch.setattr(
            "sys.argv", ["build", "--repository", str(tmp_path), "--write"]
        )
        script.main()
        capsys.readouterr()          # the first run's report, not this test's
        stamp = path.stat().st_mtime_ns

        script.main()
        captured = capsys.readouterr().out

        assert path.stat().st_mtime_ns == stamp, (
            "the second run rewrote a file it had nothing to change"
        )

        written = re.search(r"written\s+(\d+)", captured)
        assert written and written.group(1) == "0", captured
