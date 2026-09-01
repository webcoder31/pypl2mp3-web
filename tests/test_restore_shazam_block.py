"""Putting back Shazam answers a write truncated, and noticing next time.

770 documents lost every key of `sources.shazam` but the recording code,
and gained a fresh `at` stamping the loss. What wrote them was never
established — the session's scratch files were gone, no commit fell in
the window, and no read path reproduced it on a restored copy.

The repair does not depend on knowing, and neither does the guard: a key
that was in a document and is not any more is a loss whatever wrote it.
"""

import collections
import importlib.util
import io
import tarfile
from pathlib import Path

import pytest
from mutagen.id3 import ID3, TPE1
from mutagen.mp3 import MP3

from pypl2mp3.libs import metadata

_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413
VID = "aaaaaaaaaaa"
WHEN = "2026-08-29T17:15:55Z"

FULL = {
    "artist": "Franco Micalizzi", "title": "Trinity", "score": 81,
    "isrc": "ITB262202020", "key": "44150982",
    "url": "https://www.shazam.com/track/44150982/x",
    "apple_album": "1755567369", "apple_artists": ["33131974"],
    "colors": "b:d34c19p:020202",
}
TRUNCATED = {"isrc": "ITB262202020"}


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location(
        "restore", Path("scripts/restore_shazam_block.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def _song(folder: Path, answer: dict, at=WHEN) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"IAMX - Kiss [{VID}].mp3"
    path.write_bytes(_FRAME * 8)

    tags = ID3()
    tags.add(TPE1(encoding=3, text="IAMX"))
    document = metadata.set_field(metadata.blank(VID), "artist", "IAMX", "user")
    metadata.attach(tags, metadata.set_source(document, "shazam", answer, at=at))
    tags.save(path, v1=0, v2_version=3)

    return path


def _backup(root: Path, into: Path) -> Path:
    into.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(into, "w:gz") as tar:
        for path in sorted(root.rglob("*.mp3")):
            raw = path.read_bytes()
            size = 10 + (
                ((raw[6] & 0x7f) << 21) | ((raw[7] & 0x7f) << 14)
                | ((raw[8] & 0x7f) << 7) | (raw[9] & 0x7f)
            )
            info = tarfile.TarInfo(str(path.relative_to(root)) + ".id3")
            info.size = size
            tar.addfile(info, io.BytesIO(raw[:size]))

    return into


class TestTheMerge:
    def test_what_the_backup_still_has_comes_back(self, script):
        merged = script.restored(dict(TRUNCATED, at="2026-08-30T10:56:18Z"),
                                 dict(FULL, at=WHEN))

        assert set(merged) - {"at"} == set(FULL)
        assert merged["colors"] == FULL["colors"]

    def test_the_moment_comes_from_the_backup(self, script):
        """The one in the file records when the loss happened and nothing
        else. Keeping it would date the recognition to the accident."""

        merged = script.restored(dict(TRUNCATED, at="2026-08-30T10:56:18Z"),
                                 dict(FULL, at=WHEN))

        assert merged["at"] == WHEN

    def test_what_the_file_has_now_wins(self, script):
        """A key written since the backup is not rolled back. The repair
        fills holes; it does not restore a past state."""

        newer = {"isrc": "ITB262202020", "score": 99, "artist": "Corrected"}
        merged = script.restored(dict(newer, at="x"), dict(FULL, at=WHEN))

        assert merged["score"] == 99
        assert merged["artist"] == "Corrected"
        assert merged["key"] == FULL["key"]

    def test_a_file_that_lost_nothing_is_left_alone(self, script):
        """Rewriting it would move its timestamp, which busts the cover's
        address and the repository's parse cache for nothing."""

        assert script.restored(dict(FULL, at=WHEN), dict(FULL, at=WHEN)) is None

    def test_a_backup_with_nothing_to_give_is_not_a_reason_to_write(
        self, script
    ):
        assert script.restored(dict(TRUNCATED, at="x"), {}) is None


class TestTheAudit:
    def test_it_sees_a_key_that_went(self, script, tmp_path, capsys):
        """The negative case, and it needs building on purpose: auditing
        the repaired library against the truncated backup says "nothing
        lost" quite correctly, because a subset cannot show a loss. Only
        a library poorer than its backup can."""

        root = tmp_path / "lib"
        path = _song(root / "Owner - A [PL1]", FULL)
        archive = _backup(root, tmp_path / "full.tar.gz")

        # Now truncate the library, as the incident did.
        tags = ID3(path)
        metadata.attach(tags, metadata.set_source(
            metadata.of(tags), "shazam", TRUNCATED, at="2026-08-30T10:56:18Z"
        ))
        tags.save(path, v1=0, v2_version=3)

        code = script.audit(root, script.blocks(archive, root))
        out = capsys.readouterr().out

        assert code == 1, "a loss reported success"
        assert "8 key(s) lost across 1 song(s)" in out, out
        assert "colors" in out and "apple_artists" in out

    def test_it_says_nothing_when_nothing_went(self, script, tmp_path, capsys):
        root = tmp_path / "lib"
        _song(root / "Owner - A [PL1]", FULL)
        archive = _backup(root, tmp_path / "full.tar.gz")

        code = script.audit(root, script.blocks(archive, root))

        assert code == 0
        assert "nothing lost" in capsys.readouterr().out

    def test_a_document_that_vanished_is_a_loss_too(
        self, script, tmp_path, capsys
    ):
        root = tmp_path / "lib"
        path = _song(root / "Owner - A [PL1]", FULL)
        archive = _backup(root, tmp_path / "full.tar.gz")

        tags = ID3(path)
        tags.delall("PRIV")
        tags.save(path, v1=0, v2_version=3)

        assert script.audit(root, script.blocks(archive, root)) == 1
        assert "no document at all" in capsys.readouterr().out
