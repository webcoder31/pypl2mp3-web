"""Recover what YouTube said about each song, before it is gone for good.

The import takes four things from the video — the id, the channel name,
the video title and the thumbnail — and hands three of them straight to
the fields Shazam later overwrites. Nothing keeps a copy. On 944 songs,
715 now carry Shazam's names and the original is simply not in the file
any more.

It is recoverable only while the video is up, and it is not always. A
sample of 60 came back with two 404s: about 3% already gone, and the
share only grows. That is what separates this pass from the Shazam
backfill — an ISRC does not evaporate, a deleted video does.

It is also cheap in a way the Shazam pass is not. YouTube's oEmbed
endpoint answers in about a tenth of a second, with no key, no throttle
and no library: `title` and `author_name` are exactly `video.title` and
`video.author`. The whole library takes about two minutes.

Nothing is written to the ID3 frames. There is no standard frame for any
of this, and inventing more custom ones is the arrangement this branch
exists to leave behind. It goes in the document, under `sources.youtube`,
which is where evidence lives.

Three states, and the third is the point:

    {}                                    never asked
    {"at": …, "author": …, "title": …}    asked, answered
    {"at": …, "gone": true, "http": 404}  asked, the video is not there

Without the third, every later pass re-asks the same dead videos and
fails the same way, with no means of telling "not done yet" from "cannot
be done". The status code is kept because they do not mean the same
thing: a 404 is a deletion, a 401 a video made private, a 403 a regional
block. The last two can reopen.

    uv run python scripts/recover_youtube_origin.py --dry-run
    uv run python scripts/recover_youtube_origin.py [--limit N] [--retry-gone]
"""

import argparse
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pypl2mp3.libs import metadata  # noqa: E402


OEMBED = "https://www.youtube.com/oembed?url=https://youtu.be/{}&format=json"

# Not a throttle — YouTube imposes none here — just enough not to hammer
# a free endpoint nine hundred times in ninety seconds.
PAUSE = 0.08

# A video that answers with one of these is not coming back today. Any
# other failure is the network's fault and the song stays a candidate.
ABSENT = (400, 401, 403, 404, 410)


def fetch(video_id: str) -> tuple:
    """Ask YouTube about one video.

    Returns:
        tuple: (payload, status). The payload is the decoded answer, or
            None. The status is the HTTP code for a refusal, 200 for an
            answer, and None when the request itself failed — which is
            not the same thing and must not be recorded as one.
    """

    try:
        with urllib.request.urlopen(OEMBED.format(video_id), timeout=10) as r:
            return json.load(r), 200
    except urllib.error.HTTPError as error:
        return None, error.code
    except Exception:
        return None, None


def origin(payload, status, at: str) -> dict | None:
    """What to record, or None if nothing was learnt.

    The channel name arrives with " - Topic" appended on YouTube's own
    auto-generated music channels. It is stored as given: this block is
    evidence, and trimming it here would be a decision made in the wrong
    place.
    """

    if status == 200 and payload:
        return {
            "author": (payload.get("author_name") or "").strip(),
            "title": (payload.get("title") or "").strip(),
            "channel": (payload.get("author_url") or "").strip(),
        }

    if status in ABSENT:
        return {"gone": True, "http": status}

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repository",
        default=os.environ.get("PYPL2MP3_DEFAULT_REPOSITORY_PATH")
        or str(Path.home() / "pypl2mp3"),
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--retry-gone", action="store_true",
        help="ask again about videos previously found missing; a 401 or a "
             "403 can reopen, a 404 will not",
    )
    args = parser.parse_args()

    repository = Path(args.repository).expanduser()
    songs = sorted(repository.rglob("*.mp3"))

    if args.limit:
        songs = songs[: args.limit]

    recovered = already = gone = undocumented = unreachable = 0
    stopping = []
    signal.signal(signal.SIGINT, lambda *_: stopping.append(True))

    print(f"{len(songs)} song(s)"
          + ("  —  dry run, nothing written" if args.dry_run else ""))

    for index, path in enumerate(songs, start=1):
        if stopping:
            print("\ninterrupted — everything already written is written")
            break

        try:
            document = metadata.read(path)
        except Exception as error:
            print(f"  ! {type(error).__name__:20} {path.name[:56]}")
            undocumented += 1
            continue

        if document is None:
            undocumented += 1
            continue

        known = document["sources"].get("youtube") or {}

        if known and not (args.retry_gone and known.get("gone")):
            already += 1
            continue

        payload, status = fetch(document["id"])
        learnt = origin(payload, status, metadata.now())

        if learnt is None:
            unreachable += 1
            print(f"  ? {'unreachable':20} {path.name[:56]}")
            time.sleep(PAUSE)
            continue

        if learnt.get("gone"):
            gone += 1
            print(f"  – {status}  {path.name[:60]}")
        else:
            recovered += 1
            print(f"  ✓ {index:4}/{len(songs)}  {learnt['author'][:28]:28} "
                  f"{learnt['title'][:34]}")

        if not args.dry_run:
            metadata.write(
                path, metadata.set_source(document, "youtube", learnt)
            )

        time.sleep(PAUSE)

    print()
    print(f"{'recovered':>16}  {recovered}")
    print(f"{'gone':>16}  {gone}")
    print(f"{'already known':>16}  {already}")
    print(f"{'no document':>16}  {undocumented}")
    print(f"{'unreachable':>16}  {unreachable}   (still candidates)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
