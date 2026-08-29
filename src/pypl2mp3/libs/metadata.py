"""One document per song, holding everything this tool knows about it.

Today that knowledge is spread across eight TXXX frames whose names have
changed twice, plus four standard frames, and the split between them is
historical rather than meaningful. Three defects found in one afternoon
came from that arrangement: a picture identified by the free-text label
somebody gave it, a `delall("TXXX")` that destroyed every frame the
writer did not happen to know about, and a URL that answered two
different questions at once.

The document answers those by separating three things a song carries:

  * `fields` — what the file claims, one entry per displayed value, each
    carrying who decided it and when. Without that an automated pass
    cannot tell a value it may overwrite from one somebody typed.
  * `sources` — what each upstream answered, kept verbatim and never
    overwritten. YouTube's author and title are currently destroyed by
    the first Shazam match that beats the threshold; nothing keeps them.
  * `embedded` — what the file actually contains right now, as opposed to
    what was asked for. The distinction between "the cover I requested"
    and "the cover that is in here" is exactly the one whose absence
    stopped covers from ever being refetched.

It lives in a PRIV frame, which is the one place the existing code cannot
reach: `song.py` deletes TPE1, TIT2, the four release frames, every TXXX
and every APIC, but never a PRIV — and `waveform.store_peaks`, which does
delete PRIV frames, puts back the ones it does not own. Both were checked
against a real file before this module was written.

The version lives *inside* the document, not in the owner string. The
peaks do the opposite — `#peaks-1` — and that is right for them: a cache
whose format changes can simply be discarded and recomputed. A record
cannot. It has to be migrated, which means a reader must be able to find
a document of any version before deciding what to do with it.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import mutagen.mp3
from mutagen.id3 import PRIV


# Stable across versions, on purpose: see the module docstring.
OWNER = "https://github.com/webcoder31/pypl2mp3#meta"

# What this build writes, and the highest it knows how to read.
VERSION = 1

# Every value the panels display. A field that is displayed and has no
# provenance is a field an automated pass cannot safely touch.
FIELDS = ("artist", "title", "album", "year", "genre", "publisher", "cover")

# Who may have set a field. "import" is the tool acting on YouTube's
# answer, which is not the same as the user having chosen it; "legacy"
# means the value was recovered from the old frames and its origin cannot
# be established. Guessing would be worse than saying so: a pass that
# believed a legacy value was "shazam" would feel free to overwrite an
# edit somebody made by hand.
SETTERS = ("user", "shazam", "import", "legacy")

SOURCES = ("youtube", "shazam")

# Tells "no timestamp given, use the clock" apart from "the timestamp is
# not knowable". The second is not a hypothetical: nothing in the old
# frames records when a value was set, and the file's own date has been
# moved by the peak store and by two repair passes. Writing today's date
# there would make every migrated field look freshly decided, which is
# precisely the comparison the document exists to make possible.
UNSET = object()


class MetadataError(Exception):
    """Something is wrong with a song's document."""


class UnknownVersion(MetadataError):
    """The document was written by a newer build than this one.

    Raised rather than ignored. A reader that treated a version it does
    not understand as one it does would write it back in the older shape
    and lose whatever the newer one added — silently, which is how the
    Shazam frame names came to exist in three generations at once.
    """


def now() -> str:
    """The current instant, in the form the document stores.

    A function rather than a call buried in each setter, so a test can
    pass its own timestamp and two fields set by one operation can be
    made to share it.
    """

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def blank(youtube_id: str) -> dict:
    """A document for a song nothing is yet known about.

    Every key that will ever be read is present from the start, empty
    rather than absent. A schema where a key is sometimes there is a
    schema every reader has to guard, and this codebase has already been
    caught twice by exactly that.
    """

    return {
        "v": VERSION,
        "id": youtube_id,
        "fields": {},
        "sources": {name: {} for name in SOURCES},
        "embedded": {},
    }


def read(song_path: Path) -> dict | None:
    """The song's document, or None if it has none yet.

    Raises:
        UnknownVersion: if the document is newer than this build.
        MetadataError: if the frame is there but is not a document.
    """

    try:
        return of(mutagen.mp3.MP3(song_path).tags)
    except MetadataError as error:
        raise type(error)(f"{song_path.name}: {error}") from error


def payload(document: dict) -> bytes:
    """The document as it is stored.

    Keys sorted, so the same content always produces the same bytes and
    an unchanged document can be recognised as unchanged.
    """

    return json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def attach(tags, document: dict) -> bool:
    """Put the document into a tag set without saving the file.

    For a caller that is already writing frames and about to save: one
    write instead of two, and no window in which the frames and the
    document disagree on disk.

    Returns:
        bool: whether anything changed. False means the tag set already
            held this exact document, so a caller saving only because of
            this can skip it.

    Other applications' private frames survive: `delall` takes a frame
    type and not an owner, so the survivors are put back by hand — the
    same discipline `waveform.store_peaks` follows.
    """

    wanted = payload(document)
    others = []
    unchanged = False

    for frame in tags.getall("PRIV"):
        if frame.owner == OWNER:
            unchanged = frame.data == wanted
        else:
            others.append(frame)

    if unchanged:
        return False

    tags.delall("PRIV")

    for frame in others:
        tags.add(frame)

    tags.add(PRIV(owner=OWNER, data=wanted))

    return True


def of(tags) -> dict | None:
    """The document held by a tag set, without reopening the file.

    Raises:
        UnknownVersion: if it was written by a newer build.
        MetadataError: if the frame is there but is not a document.
    """

    for frame in tags.getall("PRIV") if tags else []:
        if frame.owner != OWNER:
            continue

        try:
            document = json.loads(frame.data.decode("utf-8"))
        except Exception as error:
            raise MetadataError("unreadable document") from error

        if document.get("v") != VERSION:
            raise UnknownVersion(
                f"version {document.get('v')} document; this build reads "
                f"version {VERSION}"
            )

        return document

    return None


def write(song_path: Path, document: dict) -> bool:
    """Store the document, leaving every other frame alone.

    Returns:
        bool: whether the file was written. An unchanged document is not
            rewritten — the keys are sorted so the bytes are stable, and
            a needless write would move the file's timestamp, which busts
            the cover's address and the repository's parse cache for
            nothing.

    Other applications' private frames survive: `delall` takes a frame
    type and not an owner, so the survivors are put back by hand — the
    same discipline `waveform.store_peaks` follows, and for the same
    reason.
    """

    mp3 = mutagen.mp3.MP3(song_path)

    if mp3.tags is None:
        mp3.add_tags()

    if not attach(mp3.tags, document):
        return False

    mp3.save(v1=0, v2_version=3)

    return True


def field(document: dict, name: str) -> dict | None:
    """One field, or None if nothing has ever set it."""

    _check_field(name)

    return document.get("fields", {}).get(name)


def value(document: dict, name: str, default: str = "") -> str:
    """What a field says, without its provenance."""

    entry = field(document, name)

    return entry["value"] if entry else default


def set_field(
    document: dict,
    name: str,
    value: str,
    by: str,
    at: str | None = UNSET,
) -> dict:
    """A document with that field set, leaving the given one untouched.

    `at=None` means the moment is not knowable, which is different from
    not having been given one. Everything migrated from the old frames is
    in that case.

    Returns a new document rather than mutating: the shadow phase holds
    one document read from the file beside another rebuilt from the old
    frames and compares them, and a setter that mutated in place would
    quietly make the two the same object.
    """

    _check_field(name)

    if by not in SETTERS:
        raise MetadataError(f"unknown setter {by!r}, expected one of {SETTERS}")

    updated = copy.deepcopy(document)
    updated["fields"][name] = {
        "value": value,
        "by": by,
        "at": now() if at is UNSET else at,
    }

    return updated


def set_source(
    document: dict, name: str, answer: dict, at: str | None = UNSET
) -> dict:
    """A document recording what one upstream answered.

    The answer is stored as given. It is evidence, not a decision: what
    the file ends up claiming is a separate question, and conflating the
    two is what let a Shazam match erase YouTube's own title with nothing
    keeping a copy.
    """

    if name not in SOURCES:
        raise MetadataError(f"unknown source {name!r}, expected one of {SOURCES}")

    updated = copy.deepcopy(document)
    updated["sources"][name] = dict(
        answer, at=now() if at is UNSET else at
    )

    return updated


def set_embedded_cover(
    document: dict, digest: str, url: str = "", at: str | None = UNSET
) -> dict:
    """A document recording which picture the file now carries.

    Two records of one picture, because they answer two questions and
    only one of them is cheap.

    The digest is the fact: "is this already the picture being asked
    for?" is answerable from it without trusting anything outside the
    file, and it stays answerable after the URL has rotted. But it is
    only answerable once the bytes are in hand — which is to say, after
    paying for the download the question was meant to avoid.

    The URL is where those bytes came from. It can lie, and one day it
    will point at something else entirely; that is why it is not the
    fact. It is kept because comparing it against the URL being asked
    for is what lets a save skip a download it does not need.
    """

    updated = copy.deepcopy(document)
    updated["embedded"] = {
        "cover_sha256": digest,
        "cover_url": url,
        "at": now() if at is UNSET else at,
    }

    return updated


def _check_field(name: str) -> None:
    if name not in FIELDS:
        raise MetadataError(f"unknown field {name!r}, expected one of {FIELDS}")
