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

# The four that only Shazam can have written. Verified in the code rather
# than assumed: exactly two places set them — the accepted-match branch of
# `shazam_song` and the backfill script. The import does not touch them,
# and neither the workbench form nor the terminal prompt offers them, so
# there is no door a person could have come through.
SHAZAM_ONLY = ("album", "year", "genre", "publisher")

# Where a YouTube thumbnail lives. The id is part of the path, so a match
# is not merely "this looks like YouTube" but "this is the thumbnail of
# this very video".
THUMBNAIL = "https://i.ytimg.com/vi/{id}/"

# Where Apple serves the artwork Shazam answers with. Nobody pasted a
# hundred and sixty-nine of these by hand; they are answers whose exact
# URL has since changed — a different crop, or a later reply.
ARTWORK_HOST = "mzstatic.com"


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


def inferences(document: dict, is_junk: bool) -> list:
    """Who decided the fields no answer of Shazam's witnesses.

    Returns (field, value, at, setter). Three rules, each resting on
    something the code makes true rather than on what the values look
    like:

    A release field can only be Shazam's — nothing else writes those four.

    An artist or title equal to what the video was called is the import's,
    which writes `video.author` and `video.title` unparsed; oEmbed returns
    those same two strings, so the comparison is exact. A cover that is
    this video's own thumbnail is the import's for the same reason.

    What is left over is a person's — with two exceptions. A cover served
    by Apple is an answer of Shazam's whose exact URL has moved on. And a
    junk song's values were never typed at all: `reset_state` clears the
    frames, the constructor then derives artist and title from the
    filename, and writes them straight back. Attributing those to somebody
    would put a warning on a song nobody has touched.
    """

    answer_known = bool(
        document["sources"]["youtube"].get("title")
        or document["sources"]["youtube"].get("author")
    )
    origin = document["sources"]["youtube"]
    found = []

    def entry_of(name):
        entry = metadata.field(document, name)

        if not entry or not entry["value"] or entry["by"] != "legacy":
            return None

        return entry

    for name in SHAZAM_ONLY:
        entry = entry_of(name)

        if entry:
            found.append((name, entry["value"], entry["at"], "shazam"))

    for name, key in (("artist", "author"), ("title", "title")):
        entry = entry_of(name)

        if not entry or not answer_known:
            continue

        if entry["value"] == origin.get(key):
            found.append((name, entry["value"], entry["at"], "import"))
        elif not is_junk:
            found.append((name, entry["value"], entry["at"], "user"))

    entry = entry_of("cover")

    if entry:
        value = entry["value"]

        if value.startswith(THUMBNAIL.format(id=document["id"])):
            found.append(("cover", value, entry["at"], "import"))
        elif ARTWORK_HOST in value:
            found.append(("cover", value, entry["at"], "shazam"))

    return found


def repair(document: dict, is_junk: bool = False) -> dict:
    """The document with those attributions corrected."""

    for name, value, at in corrections(document):
        document = metadata.set_field(document, name, value, "shazam", at=at)

    for name, value, at, setter in inferences(document, is_junk):
        document = metadata.set_field(document, name, value, setter, at=at)

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

    tally = {}
    touched = written = unreadable = left = 0

    for path in songs:
        try:
            document = metadata.read(path)
        except metadata.MetadataError as error:
            unreadable += 1
            print(f"  ! {path.name[:60]}  {error}")
            continue

        if document is None:
            continue

        is_junk = "(JUNK)" in path.name
        found = [
            (name, "shazam") for name, _v, _a in corrections(document)
        ] + [
            (name, setter)
            for name, _v, _a, setter in inferences(document, is_junk)
        ]

        # What no rule reaches, counted rather than passed over in
        # silence: a run that reports only what it changed reads as
        # having covered everything.
        for name in WITNESSED + SHAZAM_ONLY:
            entry = metadata.field(document, name)

            if entry and entry["value"] and entry["by"] == "legacy":
                if name not in {n for n, _s in found}:
                    left += 1

        if not found:
            continue

        touched += 1

        for name, setter in found:
            tally[(setter, name)] = tally.get((setter, name), 0) + 1

        if args.write and metadata.write(path, repair(document, is_junk)):
            written += 1

    verb = "would attribute" if not args.write else "attributed"
    print(f"{verb} {sum(tally.values())} field(s) across {touched} song(s)")

    for setter in ("shazam", "import", "user"):
        rows = {n: c for (s_, n), c in tally.items() if s_ == setter}

        if rows:
            detail = ", ".join(f"{n} {c}" for n, c in sorted(rows.items()))
            print(f"  {setter:7} {sum(rows.values()):5}   ({detail})")

    print(f"  left as legacy, no rule reaches them: {left}")

    if args.write:
        print(f"files written {written}")

    if unreadable:
        print(f"unreadable {unreadable}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
