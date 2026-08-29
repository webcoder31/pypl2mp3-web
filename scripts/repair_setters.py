"""Say Shazam decided a value where Shazam demonstrably did.

Read-only by default. `--write` stores the corrections; without it
nothing is touched and the run is a report.

The document records who decided each value. For most of this library it
says `legacy` — its word for "nobody knows" — because the documents were
built from frames, and a frame holds a string and no account of where it
came from. That is honest but imprecise, and the imprecision survived the
global Shazam pass: the pass writes `by="shazam"`, but the rule that an
unchanged value keeps its entry protects a stale `by` along with the
moment it was decided. 780 of its 811 songs already held the same values,
so their attribution never moved.

What makes the repair possible without asking anything is that the pass
also stored Shazam's own answer beside the value. Where a field marked
`legacy` holds exactly what Shazam answered, Shazam decided it — there is
no other way for the two strings to be equal, since a person who typed
the same URL would have been marked `user`.

Three fields carry that evidence: artist, title and cover. The album, the
year, the genre and the label do not — `sources.shazam` never kept a copy
of them, because they have standard frames of their own and no twin was
ever needed. They stay `legacy`, correctly: nothing in the file says who
chose them.

`at` is left exactly as it was, including null. This corrects an
attribution, not a moment: writing today's date would replace "we do not
know when" with a time nothing happened.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pypl2mp3.libs import metadata  # noqa: E402


# The fields whose decision can be established rather than guessed: the
# ones Shazam's answer is kept beside.
WITNESSED = ("artist", "title", "cover")


def corrections(document: dict) -> list:
    """Which fields this document attributes to nobody and should not.

    Returns (field, value, at) for each. A field already marked `user` or
    `shazam` is left alone — the first outranks any inference, and the
    second is already what this would write.
    """

    answer = document["sources"]["shazam"]
    found = []

    for name in WITNESSED:
        entry = metadata.field(document, name)

        if not entry or not entry["value"]:
            continue

        if entry["by"] != "legacy":
            continue

        if answer.get(name) != entry["value"]:
            continue

        found.append((name, entry["value"], entry["at"]))

    return found


def repair(document: dict) -> dict:
    """The document with those attributions corrected."""

    for name, value, at in corrections(document):
        document = metadata.set_field(document, name, value, "shazam", at=at)

    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        default=os.environ.get("PYPL2MP3_DEFAULT_REPOSITORY_PATH"),
        help="folder where playlists are stored",
    )
    parser.add_argument(
        "--write", action="store_true",
        help="store the corrections; without it nothing is touched",
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    if not args.repository:
        parser.error("no repository given and none in the environment")

    songs = sorted(Path(args.repository).expanduser().rglob("*.mp3"))

    if args.limit:
        songs = songs[: args.limit]

    print(f"{len(songs)} song(s)")
    print("dry run: nothing is written\n" if not args.write else "")

    per_field = {}
    touched = written = unreadable = 0

    for path in songs:
        try:
            document = metadata.read(path)
        except metadata.MetadataError as error:
            unreadable += 1
            print(f"  ! {path.name[:60]}  {error}")
            continue

        if document is None:
            continue

        found = corrections(document)

        if not found:
            continue

        touched += 1

        for name, _value, _at in found:
            per_field[name] = per_field.get(name, 0) + 1

        if args.write and metadata.write(path, repair(document)):
            written += 1

    verb = "would correct" if not args.write else "corrected"
    total = sum(per_field.values())
    print(f"{verb} {total} field(s) across {touched} song(s)")

    for name in WITNESSED:
        if per_field.get(name):
            print(f"  {name:8} {per_field[name]}")

    if args.write:
        print(f"files written {written}")

    if unreadable:
        print(f"unreadable {unreadable}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
