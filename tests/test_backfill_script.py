"""The backfill's selection rules, which are the part that can be wrong
without anyone noticing.

The recognition itself is Shazam's and the writing is SongModel's, both
already covered. What only this script decides is *which* songs are worth
a request — and getting that wrong either wastes hours or silently skips
half the library.
"""

import importlib.util
from pathlib import Path

import pytest
from mutagen.id3 import ID3, TALB, TPE1, TIT2, TXXX
from mutagen.mp3 import MP3

_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413
PLAYLIST = "Owner - Alpha [PL0000000000000000000000000000001]"
SHAZAM_COVER = "https://is1-ssl.mzstatic.com/image/thumb/x/400x400cc.jpg"
YOUTUBE_COVER = "https://i.ytimg.com/vi/aaaaaaaaaaa/hq720.jpg"


@pytest.fixture(scope="module")
def script():
    """Loaded from its path: it lives in scripts/, outside the package,
    because it is an operation you run once and not a feature."""

    path = Path("scripts/backfill_shazam_data.py")
    spec = importlib.util.spec_from_file_location("backfill", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _song(repo: Path, name: str, *, cover=None, album=False,
          provenance=False, junk=False):
    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    suffix = " (JUNK)" if junk else ""
    path = folder / f"{name} [aaaaaaaaaaa]{suffix}.mp3"
    path.write_bytes(_FRAME * 8)

    tags = ID3()
    tags.add(TPE1(encoding=3, text="IAMX"))
    tags.add(TIT2(encoding=3, text="Kiss"))
    tags.add(TXXX(encoding=3, desc="YouTube ID", text="aaaaaaaaaaa"))

    if cover:
        tags.add(TXXX(encoding=3, desc="Cover art URL", text=cover))
    if album:
        tags.add(TALB(encoding=3, text="Kingdom of Welcome Addiction"))
    if provenance:
        tags.add(TXXX(encoding=3, desc="Shazam artist", text="IAMX"))

    tags.save(path, v1=0, v2_version=3)
    return path


def test_a_shazam_cover_is_what_identifies_the_oldest_songs(script, tmp_path):
    """The provenance frames arrived in the CLI on 2025-05-04. Everything
    imported before has none, so their absence proves nothing — 787 songs
    in one library. What survives is the cover URL: Shazam serves its art
    from Apple's CDN, and a YouTube thumbnail means it never matched.
    """

    shazamed = _song(tmp_path, "IAMX - Kiss", cover=SHAZAM_COVER)
    never = _song(tmp_path, "IAMX - Sorrow", cover=YOUTUBE_COVER)
    bare = _song(tmp_path, "IAMX - Nightlife")

    assert script.was_identified(MP3(shazamed).tags)
    assert not script.was_identified(MP3(never).tags)
    assert not script.was_identified(MP3(bare).tags)

    # And the frames still count when they are there.
    tagged = _song(tmp_path, "IAMX - Volatile", provenance=True)
    assert script.was_identified(MP3(tagged).tags)


def test_the_two_gaps_are_reported_apart(script, tmp_path):
    """A song can be missing the release data, the provenance, or both.
    Reporting them apart is what lets the run say which half of the
    library it is repairing."""

    neither = _song(tmp_path, "A - One", cover=SHAZAM_COVER,
                    album=True, provenance=True)
    release_only = _song(tmp_path, "A - Two", cover=SHAZAM_COVER,
                         provenance=True)
    provenance_only = _song(tmp_path, "A - Three", cover=SHAZAM_COVER,
                            album=True)
    both = _song(tmp_path, "A - Four", cover=SHAZAM_COVER)

    assert script.what_is_missing(MP3(neither).tags) == set()
    assert script.what_is_missing(MP3(release_only).tags) == {"release"}
    assert script.what_is_missing(MP3(provenance_only).tags) == {"provenance"}
    assert script.what_is_missing(MP3(both).tags) == {"release", "provenance"}


def test_nothing_missing_is_not_worth_fifteen_seconds(script, tmp_path):
    """Which is also what makes a stopped run resumable: the songs
    already done fall out of the list on the next pass."""

    _song(tmp_path, "A - Done", cover=SHAZAM_COVER, album=True,
          provenance=True)

    assert script.candidates(tmp_path) == []


def test_junk_is_left_to_the_tool_that_asks_first(script, tmp_path):
    """Junk songs need identifying, not topping up, and `fix_junks`
    already offers that one song at a time with a confirmation. Sweeping
    them here would rename files behind the listener."""

    _song(tmp_path, "A - Junky", cover=SHAZAM_COVER, junk=True)

    assert script.candidates(tmp_path) == []


def test_a_song_never_identified_is_not_a_candidate(script, tmp_path):
    """Backfilling it would mean identifying it, which rewrites the
    artist, the title and the cover — a different operation with a
    different risk, and not what a backfill is."""

    _song(tmp_path, "A - Unknown", cover=YOUTUBE_COVER)

    assert script.candidates(tmp_path) == []


def test_the_order_is_stable_so_a_resumed_run_walks_the_same_list(
    script, tmp_path
):
    _song(tmp_path, "C - Third", cover=SHAZAM_COVER)
    _song(tmp_path, "A - First", cover=SHAZAM_COVER)
    _song(tmp_path, "B - Second", cover=SHAZAM_COVER)

    once = script.candidates(tmp_path)
    twice = script.candidates(tmp_path)

    assert once == twice
    assert [p.name[0] for p in once] == ["A", "B", "C"]


def test_an_unreadable_file_is_passed_over_rather_than_crashing(
    script, tmp_path
):
    """One corrupt file in nine hundred must not end a three-hour run."""

    folder = tmp_path / PLAYLIST
    folder.mkdir(parents=True)
    (folder / "broken [aaaaaaaaaaa].mp3").write_bytes(b"not an mp3 at all")

    assert script.frames_of(folder / "broken [aaaaaaaaaaa].mp3") is None
    assert script.candidates(tmp_path) == []


def test_the_throttle_is_the_one_the_model_applies(script):
    """Fifteen seconds, because Shazam refuses faster and the model waits
    that long itself. A script pacing itself differently would either be
    throttled server-side or take longer than it needs to."""

    assert script.THROTTLE_SECONDS == 15


def test_the_threshold_starts_where_the_rest_of_the_tool_starts(script):
    """Raisable, because a wrong album is a quieter mistake than a wrong
    title — but not silently different from what the console does."""

    assert script.MATCH_THRESHOLD == 50
