"""Removing every TXXX, once the document carries what they held.

The model stopped writing them, so a file loses them the next time it is
saved for any reason. This pass makes the state uniform rather than
leaving the library half one way and half the other for as long as it
takes every song to be touched.

Eleven labels existed in this library and four are named nowhere in the
codebase — an older generation of the same four Shazam names, which
`legacy` can read and the model no longer could. That is the argument
against a free-text key in one sentence.
"""

import importlib.util
from pathlib import Path

import pytest
from mutagen.id3 import ID3, PRIV, TPE1, TXXX
from mutagen.mp3 import MP3

from pypl2mp3.libs import metadata

_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413
VID = "aaaaaaaaaaa"


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location(
        "drop", Path("scripts/drop_custom_frames.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def _song(repo: Path, *, document=True, stored="", labels=()):
    repo.mkdir(parents=True, exist_ok=True)
    path = repo / f"IAMX - Kiss [{VID}].mp3"
    path.write_bytes(_FRAME * 8)

    tags = ID3()
    tags.add(TPE1(encoding=3, text="IAMX"))

    for desc in labels:
        tags.add(TXXX(encoding=3, desc=desc, text="x"))

    if stored:
        tags.add(TXXX(encoding=3, desc="Stored cover art URL", text=stored))

    if document:
        metadata.attach(tags, metadata.blank(VID))

    tags.save(path, v1=0, v2_version=3)

    return path


class TestWhatItRemoves:
    def test_every_label_goes_including_those_no_code_names(
        self, script, tmp_path, monkeypatch
    ):
        """`Shazam matching rate` and its three siblings are read by
        `legacy` and by nothing else. A pass that removed only what the
        model writes would have left them, and they are exactly the
        frames whose existence made the case for the document."""

        path = _song(tmp_path, labels=(
            "YouTube ID", "Cover art URL", "Shazam artist",
            "Shazam matching rate", "Shazam matching cover art URL",
            "Something Nobody Here Ever Wrote",
        ))

        monkeypatch.setattr(
            "sys.argv", ["drop", "--repository", str(tmp_path), "--write"]
        )
        script.main()

        assert MP3(path).tags.getall("TXXX") == []

    def test_the_document_is_left_standing(self, script, tmp_path, monkeypatch):
        """It is the whole point: the frames go because the document
        holds what they said."""

        path = _song(tmp_path, labels=("YouTube ID",))

        monkeypatch.setattr(
            "sys.argv", ["drop", "--repository", str(tmp_path), "--write"]
        )
        script.main()

        assert metadata.read(path)["id"] == VID


class TestWhatItCarriesOver:
    def test_where_the_picture_came_from_is_rescued_first(self, script):
        """The one frame in this library whose value the document never
        picked up. Dropping it would cost that song one redundant
        download — small, and avoidable in four lines."""

        tags = ID3()
        tags.add(TXXX(
            encoding=3, desc="Stored cover art URL", text="https://img/one.jpg"
        ))
        document = metadata.set_embedded_cover(
            metadata.blank(VID), "3f9a", "", at=None
        )

        rescued = script.carried_over(document, tags)

        assert rescued["embedded"]["cover_url"] == "https://img/one.jpg"
        # The digest and the moment are untouched: this carries a value
        # across, it does not claim the picture changed.
        assert rescued["embedded"]["cover_sha256"] == "3f9a"
        assert rescued["embedded"]["at"] is None

    def test_the_pass_actually_carries_it(self, script, tmp_path, monkeypatch):
        """The three tests around this one exercise `carried_over` on its
        own; removing the call from the pass broke none of them. A suite
        can cover all of a rule and nothing of its wiring."""

        path = _song(tmp_path, stored="https://img/one.jpg",
                     labels=("YouTube ID",))

        monkeypatch.setattr(
            "sys.argv", ["drop", "--repository", str(tmp_path), "--write"]
        )
        script.main()

        assert MP3(path).tags.getall("TXXX") == []
        assert metadata.read(path)["embedded"]["cover_url"] == (
            "https://img/one.jpg"
        )

    def test_a_document_that_already_knows_is_not_rewritten(self, script):
        tags = ID3()
        tags.add(TXXX(
            encoding=3, desc="Stored cover art URL", text="https://img/old.jpg"
        ))
        document = metadata.set_embedded_cover(
            metadata.blank(VID), "3f9a", "https://img/new.jpg", at=None
        )

        assert script.carried_over(document, tags) is None

    def test_no_frame_is_nothing_to_carry(self, script):
        assert script.carried_over(metadata.blank(VID), ID3()) is None


class TestWhatItRefusesToTouch:
    def test_a_document_it_cannot_read_keeps_its_frames(
        self, script, tmp_path, monkeypatch, capsys
    ):
        """Whatever wrote it may still need them, and this build cannot
        know what it holds. Removing them would be destroying the older
        half of a file it does not understand — the exact mistake that
        left three generations of frame names coexisting."""

        path = _song(tmp_path, document=False, labels=("YouTube ID",))
        tags = ID3(path)
        tags.add(PRIV(owner=metadata.OWNER, data=b'{"v": 99, "id": "x"}'))
        tags.save(path, v1=0, v2_version=3)

        monkeypatch.setattr(
            "sys.argv", ["drop", "--repository", str(tmp_path), "--write"]
        )
        script.main()

        assert MP3(path).tags.getall("TXXX"), "frames removed blindly"
        assert "unreadable document" in capsys.readouterr().out

    def test_a_dry_run_writes_nothing(self, script, tmp_path, monkeypatch):
        path = _song(tmp_path, labels=("YouTube ID", "Shazam artist"))
        before = path.read_bytes()

        monkeypatch.setattr(
            "sys.argv", ["drop", "--repository", str(tmp_path)]
        )
        script.main()

        assert path.read_bytes() == before
