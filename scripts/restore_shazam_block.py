"""Put back the Shazam answers a write on 2026-08-30 12:56 truncated.

Read-only by default. `--write` restores; without it nothing is touched.

770 documents lost every key of `sources.shazam` except the recording
code, and gained a fresh `at` stamping the loss. `fields`, `embedded` and
`sources.youtube` came through untouched on all of them, so this repairs
one block and leaves the rest of the document exactly as it stands.

What wrote them is not established. The session's own scratch files are
gone, no commit falls in that window, and neither the frame removal nor
any read path reproduces it on a restored copy. Saying "probably X" here
would be worse than saying nothing: the guard this suggests — see
`--audit` — does not depend on knowing.

The backup is the source: one ID3 block per song, taken at 08:39 that
morning and verified by restoring one to the byte before it was relied
on. Its Shazam blocks predate the loss.

The merge keeps whatever the file has now and fills the rest from the
backup, so a key written since is not rolled back. The `at` comes from
the backup, because the one in the file records the moment of the loss
and nothing else.
"""

import argparse
import collections
import io
import os
import sys
import tarfile
from pathlib import Path

from mutagen.id3 import ID3

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pypl2mp3.libs import metadata  # noqa: E402


def restored(current: dict, saved: dict) -> dict | None:
    """The Shazam block with what the backup still has, or None.

    None when there is nothing to add — the file already holds every key
    the backup does, so rewriting would only move its timestamp.
    """

    if not saved:
        return None

    merged = dict(saved)
    merged.update({k: v for k, v in current.items() if k != "at" and v})

    if set(merged) - {"at"} <= set(current) - {"at"}:
        return None

    return merged


def blocks(archive: Path, root: Path) -> dict:
    """Every song's Shazam block as the backup holds it."""

    found = {}

    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            path = root / member.name[:-4]
            data = tar.extractfile(member).read()

            if not data:
                continue

            try:
                document = metadata.of(ID3(io.BytesIO(data)))
            except Exception:
                continue

            if document is not None:
                found[path] = document["sources"]["shazam"]

    return found


def audit(root: Path, saved: dict) -> int:
    """What the library no longer holds and the backup still does.

    The guard the incident asks for, and it does not depend on knowing
    what caused it: a key that was in a document and is not any more is
    a loss whatever wrote it. Run against the last backup, it answers in
    a minute — which is how long it took to find 770 truncated documents
    after weeks of not looking.

    Returns 1 when something is missing, so a shell can act on it.
    """

    lost = collections.Counter()
    songs = 0

    for path in sorted(root.rglob("*.mp3")):
        if path not in saved:
            continue

        try:
            document = metadata.read(path)
        except metadata.MetadataError:
            print(f"  ! {path.name[:60]}  unreadable document")
            lost["<unreadable>"] += 1
            continue

        if document is None:
            print(f"  ! {path.name[:60]}  no document at all")
            lost["<no document>"] += 1
            continue

        current = document["sources"]["shazam"]
        gone = [
            key for key, value in saved[path].items()
            if key != "at" and value and not current.get(key)
        ]

        if gone:
            songs += 1
            for key in gone:
                lost[key] += 1

    if not lost:
        print("nothing lost: every key the backup holds is still there")
        return 0

    print(f"{sum(lost.values())} key(s) lost across {songs} song(s)")

    for key, count in lost.most_common():
        print(f"  {count:5}  {key}")

    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        default=os.environ.get("PYPL2MP3_DEFAULT_REPOSITORY_PATH"),
    )
    parser.add_argument("--backup", required=True, help="the .tar.gz of ID3 blocks")
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--audit", action="store_true",
        help="only report what the library lost against the backup",
    )
    args = parser.parse_args()

    if args.audit and args.write:
        parser.error("--audit reports; it does not write")

    root = Path(args.repository).expanduser()
    saved = blocks(Path(args.backup).expanduser(), root)
    print(f"{len(saved)} song(s) in the backup")

    if args.audit:
        return audit(root, saved)

    print("dry run: nothing is written\n" if not args.write else "")

    repaired = written = absent = 0
    keys = 0

    for path in sorted(root.rglob("*.mp3")):
        if path not in saved:
            absent += 1
            continue

        try:
            document = metadata.read(path)
        except metadata.MetadataError:
            continue

        if document is None:
            continue

        current = document["sources"]["shazam"]
        merged = restored(current, saved[path])

        if merged is None:
            continue

        repaired += 1
        keys += len(set(merged) - set(current))

        if args.write:
            document = metadata.set_source(
                document, "shazam", {k: v for k, v in merged.items() if k != "at"},
                at=merged.get("at"),
            )
            if metadata.write(path, document):
                written += 1

    verb = "would restore" if not args.write else "restored"
    print(f"{verb} {keys} key(s) across {repaired} song(s)")

    if args.write:
        print(f"files written {written}")

    if absent:
        print(f"not in the backup, left alone: {absent}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
