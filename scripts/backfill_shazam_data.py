"""Fill in what Shazam already answered and older versions did not keep.

Three gaps, all historical, all filled by one recognition per song:

  * The release data — album, publisher, year, genre — was never read out
    of the answer until it was added to the model. Every song identified
    before that has none.
  * The `Shazam artist` / `Shazam title` / `Shazam cover art URL` /
    `Shazam match level` frames, which record *what Shazam proposed* as
    distinct from what the song claims, arrived in the CLI on 2025-05-04.
    Everything imported before then has none of those either, which is
    why their absence is no evidence that a song was never identified.
  * The recording code. Shazam returns an ISRC on every answer and it was
    never read: no file in a 944-song library carried one. It identifies
    the recording rather than the song, which is the one thing that
    separates a remaster, a live take or a remix from the original — the
    ambiguity that left thirteen songs unconfirmable last time.

It writes what the answer holds and what the answer *is*: the release
data into the standard frames, and the identifiers, page and palette into
the document, where nothing else can carry them.

What this does NOT do is call `shazam_song`. That method reapplies the
whole match: on a good score it rewrites the artist, the title and the
cover art, and renames the file. Run over hundreds of songs that may have
been corrected by hand since, it would undo that work silently. This asks
Shazam the same question and writes only what is missing.

A song is only written if Shazam still names it. The check is
`SongModel.match_score`, the same rule `shazam_song` uses — an album
applied from a different match would be a plain untruth in the file, and
nothing in the tags would say which of the two was right.

Resumable: a song that already carries everything this would write is
skipped, so stopping with Ctrl-C and starting again costs one recognition
at most. Nothing is written by halves — each song is one complete tag
write or none.

    uv run python scripts/backfill_shazam_data.py --dry-run
    uv run python scripts/backfill_shazam_data.py [--limit N] [--playlist ID]

Shazam is throttled to one request every 15 seconds by the model itself,
so the wall-clock cost is roughly a quarter-hour per sixty songs.
"""

import argparse
import asyncio
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from mutagen.mp3 import MP3
from shazamio import Shazam

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pypl2mp3.libs.song import SongModel  # noqa: E402


# The same floor `shazam_song` applies. Named here rather than reached for
# because the model keeps it inline; if that ever moves to a constant this
# should point at it instead.
THROTTLE_SECONDS = 15

# And the same back-off. Shazam refuses often enough to matter: a dry run
# over twenty songs came back with two FailedDecodeJson, which over eight
# hundred would be eighty songs needing a second pass. The model answers a
# refusal by waiting longer and asking once more, and so does this.
RETRY_SECONDS = 35

# What the CLI defaults to, and what the console's own Shazam button uses.
# Raisable from the command line, because the cost of being wrong is not
# the same here: a wrong artist or title is visible in the listing and in
# the filename, where somebody notices it. A wrong album is a quiet
# untruth inside the file, and nothing in the tags says which of the two
# answers was right. A run at 68% turned up an Ave Maria filed under "The
# Holy Grail & Knights Templars" — plausibly a compilation, plausibly the
# wrong record.
MATCH_THRESHOLD = 50

# The cover art Shazam serves is on Apple's CDN. A song whose stored cover
# URL points there was matched, whatever its provenance frames say — and
# that is the only reliable sign left for songs older than those frames.
SHAZAM_COVER_HOST = "mzstatic.com"


@dataclass
class Tally:
    """What happened, in the order it is worth reading."""

    filled: list = field(default_factory=list)
    unconfirmed: list = field(default_factory=list)
    unanswered: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    skipped: int = 0


def frames_of(path: Path):
    """The file's tags, or None if it cannot be read at all."""

    try:
        return MP3(path).tags
    except Exception:
        return None


def what_is_missing(tags) -> set:
    """Which of the two gaps this file has.

    Returns the names of the groups worth a request: "release" for the
    four standard frames, "provenance" for the four TXXX ones, "isrc" for
    the recording code. A song missing none of them is not worth fifteen
    seconds.
    """

    missing = set()

    if not any(tags.get(frame) for frame in ("TALB", "TPUB", "TDRC", "TCON")):
        missing.add("release")

    if not tags.get("TXXX:Shazam artist"):
        missing.add("provenance")

    if not tags.get("TSRC"):
        missing.add("isrc")

    return missing


def was_identified(tags) -> bool:
    """Whether Shazam ever named this song, on the only evidence that
    survives in the oldest files."""

    if tags.get("TXXX:Shazam artist"):
        return True

    cover = tags.get("TXXX:Cover art URL")

    return bool(cover) and SHAZAM_COVER_HOST in str(cover.text[0])


def candidates(repository: Path, playlist: str = "") -> list:
    """Songs worth a request, in a stable order so a resumed run walks
    the same list."""

    found = []

    for path in sorted(repository.rglob("*.mp3")):
        if playlist and playlist not in str(path.parent.name):
            continue

        # Junk is the other tool's job: those songs need identifying, not
        # topping up, and `fix_junks` already offers that with a
        # confirmation for each one.
        if "(JUNK)" in path.name:
            continue

        tags = frames_of(path)

        if tags is None or not was_identified(tags):
            continue

        if what_is_missing(tags):
            found.append(path)

    return found


async def _ask(shazam: Shazam, path: Path, last_request: list, gap: int):
    """One request, no sooner than `gap` seconds after the last."""

    waited = time.time() - last_request[0]

    if waited < gap:
        await asyncio.sleep(gap - waited)

    try:
        return await shazam.recognize_song(str(path))
    finally:
        last_request[0] = time.time()


async def recognise(shazam: Shazam, path: Path, last_request: list) -> dict:
    """One throttled recognition, retried once on a refusal.

    Shazam answers a request it does not like with something that is not
    JSON, which surfaces as FailedDecodeJson. It is not about the file:
    the same song asked again a moment later usually answers. The model
    waits thirty-five seconds and asks once more; anything still failing
    after that is left for a later run, which costs nothing because the
    song is simply still a candidate.
    """

    try:
        return await _ask(shazam, path, last_request, THROTTLE_SECONDS)
    except Exception:
        return await _ask(shazam, path, last_request, RETRY_SECONDS)


async def run(args) -> Tally:
    repository = Path(args.repository).expanduser()
    songs = candidates(repository, args.playlist)
    tally = Tally()

    minutes = len(songs) * THROTTLE_SECONDS / 60
    print(f"{len(songs)} song(s) to ask about — about {minutes:.0f} min")
    print(f"writing anything needs a match of {args.min_score}% or better")

    if args.limit:
        songs = songs[: args.limit]
        print(f"limited to {len(songs)}")

    if args.dry_run:
        print("dry run: Shazam is asked, nothing is written\n")

    stopping = []
    signal.signal(signal.SIGINT, lambda *_: stopping.append(True))

    shazam = Shazam()
    last_request = [0.0]

    for index, path in enumerate(songs, start=1):
        if stopping:
            print("\ninterrupted — everything already written is written")
            break

        song = SongModel(path)
        head = f"{index:4}/{len(songs)}  {path.name[:58]:58}"

        try:
            answer = await recognise(shazam, path, last_request)
        except Exception as error:
            tally.failed.append((path.name, f"{type(error).__name__}"))
            print(f"{head}  ! {type(error).__name__}")
            continue

        track = answer.get("track") if isinstance(answer, dict) else None

        if not track:
            tally.unanswered.append(path.name)
            print(f"{head}  – Shazam names nothing")
            continue

        shazam_title = track.get("title") or ""
        shazam_artist = track.get("subtitle") or ""
        # The rule is asked with the tool's own threshold, because the
        # artist test is relative to it, and the answer is then compared
        # against whatever the caller asked for.
        score = SongModel.match_score(
            song.artist, song.title, shazam_artist, shazam_title,
            MATCH_THRESHOLD,
        )

        if score < args.min_score:
            tally.unconfirmed.append(
                (path.name, f"{shazam_artist} - {shazam_title}", score)
            )
            print(f"{head}  – {score}%  {shazam_artist} - {shazam_title}")
            continue

        release = SongModel._release_data(track)
        cover = (track.get("images") or {}).get("coverart") or ""

        written = dict(
            release,
            shazam_artist=shazam_artist,
            shazam_title=shazam_title,
            shazam_match_score=score,
        )

        # Only when Shazam served one: passing an empty string would clear
        # a URL the file already holds.
        if cover:
            written["shazam_cover_art_url"] = cover

        summary = release.get("album") or "no album named"

        if release.get("isrc"):
            summary = f"{summary}  {release['isrc']}"
        print(f"{head}  ✓ {score}%  {summary}")

        if not args.dry_run:
            try:
                # The handles the answer carries — the Shazam page, the
                # Apple identifiers, the cover's palette. No frame can
                # hold them, so they exist only in the document, and only
                # a recognition produces them. `shazam_song` collects
                # them; this script deliberately does not go through it,
                # which is why it has to collect them itself.
                #
                # Set before the save, because that is where `_document`
                # reads them — and their presence is what tells a fresh
                # answer from an ordinary save that must not drop what an
                # earlier answer left.
                song._shazam_extras = SongModel._shazam_identity(track)

                # Shazam decided the album, the year, the genre and the
                # label. Without saying so they were written as `legacy`,
                # the document's word for "nobody knows" — over the four
                # values whose origin is the least uncertain thing in the
                # file.
                song.update_state(by="shazam", **written)
            except Exception as error:
                tally.failed.append((path.name, f"{type(error).__name__}"))
                print(f"       write failed: {error}")
                continue

        tally.filled.append(path.name)

    return tally


def report(tally: Tally, dry_run: bool) -> None:
    verb = "would fill" if dry_run else "filled"
    print()
    print(f"{verb:>12}  {len(tally.filled)}")
    print(f"{'unconfirmed':>12}  {len(tally.unconfirmed)}")
    print(f"{'unanswered':>12}  {len(tally.unanswered)}")
    print(f"{'failed':>12}  {len(tally.failed)}")

    if tally.unconfirmed:
        print("\nShazam names something else for these — left untouched:")
        for name, proposal, score in tally.unconfirmed:
            print(f"  {score:3}%  {name}")
            print(f"        Shazam says: {proposal}")

    if tally.failed:
        print("\nfailed, worth another run:")
        for name, why in tally.failed:
            print(f"  {why:24} {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repository",
        default=os.environ.get("PYPL2MP3_DEFAULT_REPOSITORY_PATH")
        or str(Path.home() / "pypl2mp3"),
    )
    parser.add_argument("--playlist", default="", help="folder name filter")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--min-score",
        type=int,
        default=MATCH_THRESHOLD,
        help=f"minimum match to write anything (default {MATCH_THRESHOLD}, "
             f"what the rest of the tool uses)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tally = asyncio.run(run(args))
    report(tally, args.dry_run)

    return 1 if tally.failed else 0


if __name__ == "__main__":
    sys.exit(main())
