"""Build each song's document from its frames, and show what diverges.

Read-only by default. `--write` stores what it built; without it nothing
is touched and the run is a report.

The report is the point. During the shadow phase the document is not the
source of truth — the running application keeps writing the old frames
and knows nothing about the document, so the two drift apart. Seeing
where, field by field, over the whole library, is what tells you whether
the document can be trusted to replace the frames. That evidence did not
exist for any earlier repair here: the backfill had to infer from a cover
art host which songs had ever been identified.

The merge rule is one line and it is the same principle the document
exists for: a stored field marked `user` is never overwritten. A rebuild
can only ever produce `shazam` or `legacy` — it reads the frames, and the
frames record no hand edits — so anything the new code marked as a
person's decision outranks it.

Where the value has not changed, the stored entry is kept whole rather
than replaced by an identical one. The rebuild's timestamps are all null,
and swapping a real moment for a null one would lose the only thing the
document knows that the frames never did.

    uv run python scripts/build_metadata_documents.py
    uv run python scripts/build_metadata_documents.py --write
"""

import argparse
import copy
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pypl2mp3.libs import legacy, metadata  # noqa: E402


def merge(stored: dict | None, rebuilt: dict) -> dict:
    """What to store, given what is there and what the frames say."""

    if stored is None:
        return rebuilt

    merged = copy.deepcopy(stored)

    for name, entry in rebuilt["fields"].items():
        current = merged["fields"].get(name)

        if current is None:
            merged["fields"][name] = entry
            continue

        if current["value"] == entry["value"]:
            # Same answer: keep the entry that knows when it was decided.
            continue

        if current["by"] == "user":
            # A person decided this. The frames cannot outrank that.
            continue

        merged["fields"][name] = entry

    for name, answer in rebuilt["sources"].items():
        if answer and not merged["sources"].get(name):
            merged["sources"][name] = answer

    if rebuilt["embedded"] and not merged["embedded"]:
        merged["embedded"] = rebuilt["embedded"]

    return merged


def divergence(stored: dict, rebuilt: dict) -> list:
    """Fields whose value differs, as (field, stored, from the frames).

    Values only. The setters and the timestamps are expected to differ —
    a rebuild has no way to know either — and reporting that as drift
    would bury the one difference worth looking at.
    """

    found = []

    for name in metadata.FIELDS:
        here = metadata.value(stored, name)
        there = metadata.value(rebuilt, name)

        if here != there:
            found.append((name, here, there))

    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repository",
        default=os.environ.get("PYPL2MP3_DEFAULT_REPOSITORY_PATH")
        or str(Path.home() / "pypl2mp3"),
    )
    parser.add_argument(
        "--write", action="store_true",
        help="store the documents; without it nothing is touched",
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    repository = Path(args.repository).expanduser()
    songs = sorted(repository.rglob("*.mp3"))

    if args.limit:
        songs = songs[: args.limit]

    print(f"{len(songs)} song(s)"
          + ("" if args.write else "  —  reporting only, nothing written"))

    fresh = matching = drifted = written = failed = 0
    by_field = {}

    for path in songs:
        try:
            rebuilt = legacy.document_from_frames(path)
            stored = metadata.read(path)
        except Exception as error:
            failed += 1
            print(f"  ! {type(error).__name__:22} {path.name[:56]}")
            continue

        if stored is None:
            fresh += 1
        else:
            differences = divergence(stored, rebuilt)

            if differences:
                drifted += 1
                print(f"  ~ {path.name[:70]}")
                for name, here, there in differences:
                    by_field[name] = by_field.get(name, 0) + 1
                    print(f"      {name:10} document {here[:34]!r}")
                    print(f"      {'':10} frames   {there[:34]!r}")
            else:
                matching += 1

        if args.write and metadata.write(path, merge(stored, rebuilt)):
            written += 1

    print()
    print(f"{'no document yet':>22}  {fresh}")
    print(f"{'matches the frames':>22}  {matching}")
    print(f"{'drifted':>22}  {drifted}")
    print(f"{'unreadable':>22}  {failed}")

    if args.write:
        print(f"{'written':>22}  {written}")

    if by_field:
        print("\ndrift by field:")
        for name, count in sorted(by_field.items(), key=lambda kv: -kv[1]):
            print(f"  {name:12} {count}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
