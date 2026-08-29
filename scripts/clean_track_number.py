"""Remove the YouTube id from the track-number frame.

Some version of this tool, older than the repository, stored the video id
in `TRCK` — the frame ID3 defines as the track number. 659 songs in one
944-song library carry one, and every value is the eleven-character id
that also appears in the filename. Nothing has ever read it back: `TRCK`
occurs nowhere in either repository, in any commit.

It is not inert, though. `TRCK` is a standard frame, so every player that
shows a track number shows this instead — "track QxdSAAWRs3E", or nothing
at all where the value fails to parse.

The id itself is not at risk. It lives in `TXXX:YouTube ID`, rewritten on
every save and present on all 944 files, and the filename carries it a
second time in brackets, which is what `find_song_file` searches.

Only a TRCK that *is* the song's own id is removed. A file that carries a
real track number keeps it: the point is to undo a misuse, not to strip a
frame.

    uv run python scripts/clean_track_number.py --dry-run
    uv run python scripts/clean_track_number.py
"""

import argparse
import os
import sys
from pathlib import Path

from mutagen.mp3 import MP3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def misused_track_number(tags, youtube_id: str) -> str:
    """The TRCK value if it is the song's id, else "".

    Compared against the id rather than merely shaped like one: an
    eleven-character track number is unlikely, but "unlikely" is not a
    reason to delete somebody's data.
    """

    frame = tags.get("TRCK") if tags else None

    if not frame:
        return ""

    value = str(frame.text[0]).strip()

    return value if value and value == youtube_id else ""


def song_id(path: Path, tags) -> str:
    """The id, from the tag first and the filename second — the same two
    sources the model uses, in the same order."""

    if tags is not None:
        frame = tags.get("TXXX:YouTube ID")
        if frame:
            return str(frame.text[0]).strip()

    name = path.stem
    if name.endswith("]") and "[" in name:
        return name[name.rfind("[") + 1:-1]

    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repository",
        default=os.environ.get("PYPL2MP3_DEFAULT_REPOSITORY_PATH")
        or str(Path.home() / "pypl2mp3"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repository = Path(args.repository).expanduser()
    cleaned = kept = unreadable = 0

    for path in sorted(repository.rglob("*.mp3")):
        try:
            mp3 = MP3(path)
        except Exception:
            unreadable += 1
            continue

        identifier = song_id(path, mp3.tags)
        misused = misused_track_number(mp3.tags, identifier)

        if not misused:
            if mp3.tags is not None and mp3.tags.get("TRCK"):
                kept += 1
                print(f"  kept   {str(mp3.tags['TRCK'].text[0]):<14} "
                      f"{path.name[:56]}")
            continue

        print(f"  remove {misused:<14} {path.name[:56]}")

        if not args.dry_run:
            mp3.tags.delall("TRCK")
            mp3.save(v1=0, v2_version=3)

        cleaned += 1

    verb = "would remove" if args.dry_run else "removed"
    print(f"\n{verb:>14}  {cleaned}")
    print(f"{'kept':>14}  {kept}   (a real track number)")
    print(f"{'unreadable':>14}  {unreadable}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
