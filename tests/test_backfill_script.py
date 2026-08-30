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
from mutagen.id3 import ID3, TALB, TPE1, TIT2, TSRC, TXXX
from mutagen.mp3 import MP3

from pypl2mp3.libs import metadata

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
          identified=False, provenance=False, isrc=False, handles=False,
          junk=False):
    """A song, and the document that says what is known about it.

    The frames are still written because the file has to be a real one,
    but nothing here reads them any more: the pass asks the document, so
    that is what these knobs fill.
    """

    folder = repo / PLAYLIST
    folder.mkdir(parents=True, exist_ok=True)
    suffix = " (JUNK)" if junk else ""
    path = folder / f"{name} [aaaaaaaaaaa]{suffix}.mp3"
    path.write_bytes(_FRAME * 8)

    tags = ID3()
    tags.add(TPE1(encoding=3, text="IAMX"))
    tags.add(TIT2(encoding=3, text="Kiss"))
    tags.add(TXXX(encoding=3, desc="YouTube ID", text="aaaaaaaaaaa"))

    document = metadata.blank("aaaaaaaaaaa")
    answer = {}

    if cover:
        document = metadata.set_field(document, "cover", cover, "legacy")
    if album:
        tags.add(TALB(encoding=3, text="Kingdom of Welcome Addiction"))
        document = metadata.set_field(
            document, "album", "Kingdom of Welcome Addiction", "shazam"
        )
    if identified or provenance:
        answer["score"] = 100
    if provenance:
        answer["artist"] = "IAMX"
    if isrc:
        tags.add(TSRC(encoding=3, text="GBDHC1907207"))
        answer["isrc"] = "GBDHC1907207"
    if handles:
        answer["key"] = "470682427"

    if answer:
        document = metadata.set_source(document, "shazam", answer)

    metadata.attach(tags, document)
    tags.save(path, v1=0, v2_version=3)

    return path


def _doc(path: Path):
    return metadata.read(path)


def test_the_document_says_outright_whether_shazam_ever_answered(
    script, tmp_path
):
    """This used to be inferred from the host serving the cover art —
    a workaround, and the right one at the time: the provenance frames
    arrived in the CLI on 2025-05-04, everything imported before had
    none, and their absence proved nothing. Reading them anyway is what
    made the first count seven times too small.

    The document records the answer itself, so the workaround is gone.
    A cover from Apple's CDN no longer counts as evidence — it was only
    ever a symptom of one."""

    answered = _song(tmp_path, "IAMX - Kiss", identified=True)
    never = _song(tmp_path, "IAMX - Sorrow", cover=YOUTUBE_COVER)
    apple_cover_only = _song(tmp_path, "IAMX - Nightlife", cover=SHAZAM_COVER)

    assert script.was_identified(_doc(answered))
    assert not script.was_identified(_doc(never))
    assert not script.was_identified(_doc(apple_cover_only))

    # A named artist is an answer too, score or no score.
    named = _song(tmp_path, "IAMX - Volatile", provenance=True)
    assert script.was_identified(_doc(named))


def test_the_gaps_are_reported_apart(script, tmp_path):
    """A song can be missing the release data, the provenance, the
    recording code, or any combination. Reporting them apart is what lets
    the run say which part of the library it is repairing."""

    whole = _song(tmp_path, "A - One", album=True, provenance=True,
                  isrc=True, handles=True)
    release_only = _song(tmp_path, "A - Two", provenance=True, isrc=True,
                         handles=True)
    provenance_only = _song(tmp_path, "A - Three", identified=True,
                            album=True, isrc=True, handles=True)
    isrc_only = _song(tmp_path, "A - Four", album=True, provenance=True,
                      handles=True)
    handles_only = _song(tmp_path, "A - Six", album=True, provenance=True,
                         isrc=True)
    nothing = _song(tmp_path, "A - Five", identified=True)

    assert script.what_is_missing(_doc(whole)) == set()
    assert script.what_is_missing(_doc(release_only)) == {"release"}
    assert script.what_is_missing(_doc(provenance_only)) == {"provenance"}
    assert script.what_is_missing(_doc(isrc_only)) == {"isrc"}
    # The group the document made possible: no frame ever carried the
    # Shazam page, the Apple identifiers or the palette, so no
    # frame-based criterion could have asked for them.
    assert script.what_is_missing(_doc(handles_only)) == {"handles"}
    assert script.what_is_missing(_doc(nothing)) == {
        "release", "provenance", "isrc", "handles",
    }


def test_a_song_complete_but_for_its_recording_code_is_a_candidate(
    script, tmp_path
):
    """Every song in the library is in that state: Shazam returned an
    ISRC on every answer and nothing ever read it. Without this the
    backfill would report nothing to do."""

    _song(tmp_path, "A - Rattrapee", album=True, provenance=True,
          handles=True)

    assert len(script.candidates(tmp_path)) == 1


def test_nothing_missing_is_not_worth_fifteen_seconds(script, tmp_path):
    """Which is also what makes a stopped run resumable: the songs
    already done fall out of the list on the next pass."""

    _song(tmp_path, "A - Done", album=True, provenance=True, isrc=True,
          handles=True)

    assert script.candidates(tmp_path) == []


def test_junk_is_left_to_the_tool_that_asks_first(script, tmp_path):
    """Junk songs need identifying, not topping up, and `fix_junks`
    already offers that one song at a time with a confirmation. Sweeping
    them here would rename files behind the listener."""

    _song(tmp_path, "A - Junky", identified=True, junk=True)

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
    _song(tmp_path, "C - Third", identified=True)
    _song(tmp_path, "A - First", identified=True)
    _song(tmp_path, "B - Second", identified=True)

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


def test_a_refusal_is_asked_again_before_being_given_up_on(script):
    """Shazam answers a request it does not like with something that is
    not JSON. A dry run over twenty songs came back with two of those —
    over eight hundred that would be eighty songs needing a second pass
    for no reason but timing.

    The back-off is the model's own: wait longer, ask once more, and
    leave anything still failing for a later run. Nothing is lost either
    way, because a song that failed is simply still a candidate.
    """

    assert script.RETRY_SECONDS == 35
    assert script.RETRY_SECONDS > script.THROTTLE_SECONDS, (
        "asking again as soon as the first attempt was refused"
    )

    import inspect

    source = inspect.getsource(script.recognise)
    assert source.count("_ask(") == 2, (
        f"a refusal is not asked again: {source}"
    )
    assert "THROTTLE_SECONDS" in source and "RETRY_SECONDS" in source, source


# ---------------------------------------------------------------------
# What the pass actually writes.
#
# The tests above ask the helpers which songs are worth a request. These
# drive the loop itself with a stubbed Shazam, because two things the
# pass has to write were found missing by reading it rather than by
# running it, and reading it is how they came to be missing.
# ---------------------------------------------------------------------

_ANSWER = {
    "track": {
        "title": "Kiss",
        "subtitle": "IAMX",
        "key": "470682427",
        "url": "https://www.shazam.com/track/470682427/kiss",
        "albumadamid": "1485457072",
        "artists": [{"adamid": "110799"}],
        "images": {
            "coverart": "https://is1-ssl.mzstatic.com/kiss.jpg",
            "joecolor": "b:5e5d71p:f7e4df",
        },
        "isrc": "GBDHC1907207",
        "genres": {"primary": "Alternative"},
        "sections": [{"metadata": [
            {"title": "Album", "text": "Kingdom of Welcome Addiction"},
            {"title": "Label", "text": "61 Seconds"},
            {"title": "Released", "text": "2009"},
        ]}],
    }
}


class _Args:
    def __init__(self, repository):
        self.repository = str(repository)
        self.playlist = ""
        self.limit = 0
        self.min_score = 50
        self.dry_run = False


async def _pass(script, tmp_path, monkeypatch, answer=_ANSWER):
    """One run of the loop, with the network and the throttle removed."""

    monkeypatch.setattr(
        script, "recognise",
        lambda _shazam, _path, _last: _resolved(answer),
    )
    monkeypatch.setattr(script, "Shazam", lambda: object())

    return await script.run(_Args(tmp_path))


async def _resolved(value):
    return value


async def test_the_pass_records_the_handles_no_frame_can_hold(
    script, tmp_path, monkeypatch
):
    """They exist only in the document and only a recognition produces
    them. The pass reaches for `recognize_song` directly, on purpose — so
    it has to collect them itself, and it did not: five hours of requests
    would have left the Shazam page, the Apple identifiers and the
    palette at zero across the whole library.
    """

    
    path = _song(tmp_path, "IAMX - Kiss", identified=True)

    await _pass(script, tmp_path, monkeypatch)

    stored = metadata.read(next(tmp_path.rglob("*.mp3")))["sources"]["shazam"]

    assert stored["key"] == "470682427"
    assert stored["apple_album"] == "1485457072"
    assert stored["apple_artists"] == ["110799"]
    assert stored["colors"] == "b:5e5d71p:f7e4df"
    assert stored["url"].endswith("/kiss")


async def test_the_pass_says_who_decided_the_release(
    script, tmp_path, monkeypatch
):
    """Shazam decided the album, the year, the genre and the label.
    Written without saying so they were marked `legacy` — the document's
    word for "nobody knows" — over the four values whose origin is the
    least uncertain thing in the file."""

    _song(tmp_path, "IAMX - Kiss", identified=True)

    await _pass(script, tmp_path, monkeypatch)

    from pypl2mp3.libs.song import SongModel

    decided = SongModel(next(tmp_path.rglob("*.mp3"))).decided_by

    for field in ("album", "year", "genre", "publisher"):
        assert decided[field] == "shazam", f"{field} is {decided.get(field)!r}"


async def test_the_pass_leaves_the_name_alone(
    script, tmp_path, monkeypatch
):
    """The whole reason it does not call `shazam_song`. Saying who
    decided the release must not turn into claiming the name too."""

    _song(tmp_path, "IAMX - Kiss", identified=True)

    from pypl2mp3.libs.song import SongModel

    before = SongModel(next(tmp_path.rglob("*.mp3")))
    before.update_state(artist="Typed By Hand", by="user")

    await _pass(script, tmp_path, monkeypatch)

    after = SongModel(next(tmp_path.rglob("*.mp3")))

    assert after.artist == "Typed By Hand"
    assert after.decided_by["artist"] == "user"
