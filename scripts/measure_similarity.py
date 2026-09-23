"""Does the feature vector know anything about music?

The ruler is the artist. For each song, how many of its five nearest
neighbours are by the same one? Two songs drawn at random are by the
same artist 0.7% of the time on this library — the sum of the squared
proportions — so a vector that knows nothing scores that.

The genre was the first ruler and it was the wrong one. It is still
reported, because it colours the map and a rise would be good news, but
the same vectors score 1.4x on genre and 11.6x on artist, measured on
the same 352 songs. "Alternative" and "Pop" are commercial categories,
not acoustic ones: two Pop songs from 1985 and 2020 share a label and
nothing else.

Read-only. It writes nothing, analyses nothing, and skips any song with
no vector yet — run the bulk analysis first, from the console or with
`curl -X POST http://127.0.0.1:8895/features/analyse`.

This measure checks the weights; it must not be used to choose them.
Optimising agreement with a label turns the thing into a guesser of
labels, and an acoustic cover would stop being the neighbour of the
electronic original it covers — which is the kind of link the map
exists to show.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

import mutagen
import mutagen.mp3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pypl2mp3.libs.features import read_features  # noqa: E402
from pypl2mp3.libs.utils import get_song_id_from_filename  # noqa: E402
from pypl2mp3.services import similarity  # noqa: E402
from pypl2mp3.services.similarity import FACETS, Space  # noqa: E402


def chance_rate(counts) -> float:
    """What two songs drawn at random do.

    The sum of squared proportions — not the weight of the largest
    class, which answers a different question and flatters the result.
    """

    total = sum(counts.values())
    if total == 0:
        return 0.0

    return sum((n / total) ** 2 for n in counts.values())


def collect(repository: Path) -> list:
    """Every song that carries a vector, with its artist and genre.

    Returns:
        (key, youtube_id, vector, artist, genre) for each. The key is
        the path, which is enough to tell two songs apart here — the
        playlist key belongs to the web and this is a script.
    """

    found = []

    for song in sorted(Path(repository).glob("*/*.mp3")):
        video = get_song_id_from_filename(song.name)
        if not video:
            continue

        try:
            mp3 = mutagen.mp3.MP3(song)
        except (mutagen.MutagenError, OSError):
            continue

        vector = read_features(mp3)
        if vector is None:
            continue

        tags = mp3.tags
        genre = str(tags["TCON"]) if tags and "TCON" in tags else ""
        # The filename over the tag: it is what the repository is
        # organised by, and a junk song has no reliable artist tag.
        artist = song.name.split(" - ")[0].strip().casefold()

        found.append((str(song), video, vector, artist, genre))

    return found


def _agreement(space, keys, labels, count) -> float:
    """How often a song's neighbours share its label.

    Songs whose label is empty, and songs that are the only one carrying
    theirs, are not scored: neither can succeed, and counting them as
    failures would say the features are worse than they are.
    """

    counts = Counter(label for label in labels.values() if label)
    hits = shots = 0.0

    for key in keys:
        label = labels.get(key)
        if not label or counts[label] < 2:
            continue

        neighbours = space.neighbours(key, count=count)
        if not neighbours:
            continue

        shots += 1
        hits += sum(
            1 for n in neighbours if labels.get(n.key) == label
        ) / len(neighbours)

    return hits / shots if shots else 0.0


def _with_weights(songs, labels, weights, count) -> float:
    """The same measure under a different weighting."""

    was = dict(similarity.WEIGHTS)
    similarity.WEIGHTS.update(weights)
    try:
        space = Space.build([(k, v, vec) for k, v, vec, _, _ in songs])
        return _agreement(space, [k for k, *_ in songs], labels, count)
    finally:
        similarity.WEIGHTS.clear()
        similarity.WEIGHTS.update(was)


def measure(repository: Path, count: int = 5) -> dict:
    """The agreement rates, and what each facet contributes alone."""

    songs = collect(repository)
    keys = [key for key, *_ in songs]
    artists = {key: artist for key, _, _, artist, _ in songs}
    genres = {key: genre for key, _, _, _, genre in songs}

    space = Space.build([(k, v, vec) for k, v, vec, _, _ in songs])

    by_facet = {
        name: _with_weights(
            songs, artists,
            {f: (1.0 if f == name else 0.0) for f in FACETS}, count,
        )
        for name in FACETS
    }

    return {
        "analysed": len(songs),
        "artist": _agreement(space, keys, artists, count),
        "artist_chance": chance_rate(
            Counter(a for a in artists.values() if a)
        ),
        "genre": _agreement(space, keys, genres, count),
        "genre_chance": chance_rate(
            Counter(g for g in genres.values() if g)
        ),
        "no_genre": sum(1 for g in genres.values() if not g),
        "by_facet": by_facet,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    parser.add_argument("--count", type=int, default=5,
                        help="how many neighbours to score (default 5)")
    args = parser.parse_args()

    report = measure(args.repository, args.count)

    if not report["analysed"]:
        print("no song carries a vector — run the analysis first")
        return 1

    def line(label, rate, chance):
        times = f"{rate / chance:.1f}x" if chance else "—"
        print(f"  {label:8} {rate * 100:5.1f}%   chance {chance * 100:4.1f}%"
              f"   {times}")

    print(f"{report['analysed']} songs carry a vector, "
          f"{report['no_genre']} of them without a genre\n")
    line("artist", report["artist"], report["artist_chance"])
    line("genre", report["genre"], report["genre_chance"])

    print("\neach facet on its own, against the artist:")
    for name, rate in sorted(report["by_facet"].items(),
                             key=lambda item: -item[1]):
        against = report["artist_chance"]
        times = f"{rate / against:.1f}x" if against else "—"
        print(f"  {name:9} {rate * 100:5.1f}%   {times}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
