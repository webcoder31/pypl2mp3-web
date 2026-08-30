"""Remove every TXXX frame, once the document carries what they held.

Read-only by default. `--write` removes them; without it nothing is
touched and the run is a report.

The model stopped writing them, so a file loses them the next time it is
saved for any reason. This makes the state uniform instead of leaving the
library half one way and half the other for however long it takes every
song to be touched.

Eleven distinct labels existed here, and four of them the codebase does
not mention anywhere: `Shazam matching artist`, `Shazam matching title`,
`Shazam matching rate`, `Shazam matching cover art URL` — an older
generation of the same four names, which `legacy` can read and the model
no longer could. That is the whole argument against a free-text key: a
frame is found by the label somebody chose, and three generations of
labels lived here at once, each invisible to the reader expecting
another.

Verified before writing a line: of 5 305 frames in this library, 5 304
hold word for word what the document already says. The one exception is
a single `Stored cover art URL` whose value the document never picked up,
and this carries it over rather than dropping it.
"""

import argparse
import collections
import os
import sys
from pathlib import Path

import mutagen.mp3

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pypl2mp3.libs import metadata  # noqa: E402


def carried_over(document: dict, tags) -> dict | None:
    """The document with anything a frame still held that it lacks.

    Only one case exists, and it is worth the code rather than the loss:
    where the picture came from. The digest answers "is this already the
    one being asked for?" but only once the bytes are in hand, which is
    after paying for the download the question exists to avoid.
    """

    frame = tags.get("TXXX:Stored cover art URL")
    value = str(frame.text[0]) if frame and frame.text else ""

    if not value or document["embedded"].get("cover_url"):
        return None

    return metadata.set_embedded_cover(
        document,
        document["embedded"].get("cover_sha256", ""),
        value,
        at=document["embedded"].get("at"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository",
        default=os.environ.get("PYPL2MP3_DEFAULT_REPOSITORY_PATH"),
        help="folder where playlists are stored",
    )
    parser.add_argument(
        "--write", action="store_true",
        help="remove the frames; without it nothing is touched",
    )
    args = parser.parse_args()

    if not args.repository:
        parser.error("no repository given and none in the environment")

    songs = sorted(Path(args.repository).expanduser().rglob("*.mp3"))
    labels = collections.Counter()
    touched = carried = unreadable = 0

    print(f"{len(songs)} song(s)")
    print("dry run: nothing is written\n" if not args.write else "")

    for path in songs:
        try:
            mp3 = mutagen.mp3.MP3(path)
        except Exception as error:
            unreadable += 1
            print(f"  ! {path.name[:60]}  {type(error).__name__}")
            continue

        if mp3.tags is None:
            continue

        found = mp3.tags.getall("TXXX")

        if not found:
            continue

        for frame in found:
            labels[frame.desc] += 1

        touched += 1

        if not args.write:
            continue

        try:
            document = metadata.of(mp3.tags)
        except metadata.MetadataError:
            # A document this build cannot read. Its frames are not this
            # pass's to remove: whatever wrote it may still need them.
            print(f"  ~ {path.name[:60]}  unreadable document, left alone")
            touched -= 1
            continue

        if document is not None:
            rescued = carried_over(document, mp3.tags)

            if rescued is not None:
                metadata.attach(mp3.tags, rescued)
                carried += 1

        mp3.tags.delall("TXXX")
        mp3.save(v1=0, v2_version=3)

    verb = "would remove" if not args.write else "removed"
    print(f"{verb} {sum(labels.values())} frame(s) from {touched} song(s)")

    for label, count in labels.most_common():
        print(f"  {count:5}  {label}")

    if carried:
        print(f"carried into the document first: {carried}")

    if unreadable:
        print(f"unreadable {unreadable}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
