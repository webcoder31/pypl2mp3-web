"""Read what the old frames say, and build a document out of it.

The frames this reads were written by three generations of the tool. The
names changed twice without a migration, so one library holds all three
at once: `Shazam artist` beside `Shazam matching artist`, `APIC:Cover art`
beside `APIC:Stored cover art`. Every generation is read here, because
the point is to lose nothing.

What cannot be read is provenance. No frame records who set a value or
when, so most of what this produces is marked `legacy` with a null
timestamp. That is deliberate: a pass that believed a recovered value had
come from Shazam would feel free to overwrite an edit made by hand, and
the whole reason for the document is to stop exactly that.

Two things can be established rather than guessed, and they are:

  * a value that matches what Shazam proposed, on a song whose score
    cleared the threshold, was set by Shazam — that is what the threshold
    means;
  * the recording code, which only Shazam ever supplies and which goes
    into TSRC, a standard frame — nothing had to be invented to store it,
    and nothing else in this library ever wrote one;
  * the digest of the picture the file carries, which is not an inference
    at all. It is the one fact the old arrangement never recorded and the
    one that makes "is this already the picture being asked for?"
    answerable.

Nothing here writes. Building a document and storing it are separate
acts, so a comparison pass can hold what the frames say beside what the
document says without touching a file.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import mutagen.mp3

from pypl2mp3.libs import metadata


# The score at or above which the tool replaced the artist and the title
# with Shazam's. Below it, the names are whatever the import left.
MATCH_THRESHOLD = 50

# Shazam's own artwork is served from Apple's CDN. A cover URL pointing
# there means Shazam matched, whatever the provenance frames say — which
# for anything imported before May 2025 is nothing at all.
SHAZAM_COVER_HOST = "mzstatic.com"

# Each field, and the standard frame that held it.
_TEXT_FRAMES = {
    "artist": "TPE1",
    "title": "TIT2",
    "album": "TALB",
    "year": "TDRC",
    "genre": "TCON",
    "publisher": "TPUB",
}

# The Shazam answer, current name first and older names after. Read in
# order, first hit wins.
_SHAZAM_FRAMES = {
    "artist": ("Shazam artist", "Shazam matching artist"),
    "title": ("Shazam title", "Shazam matching title"),
    "cover": ("Shazam cover art URL", "Shazam matching cover art URL"),
    "score": ("Shazam match level", "Shazam matching rate"),
}

# The recording code, which never had a custom frame of its own: it goes
# straight into TSRC, the standard one, so it is read from there.
_ISRC_FRAME = "TSRC"


def _text(tags, frame: str) -> str:
    value = tags.get(frame) if tags else None

    return str(value.text[0]).strip() if value else ""


def _custom(tags, *names: str) -> str:
    """The first of those TXXX descriptions that the file carries."""

    for name in names:
        value = tags.get(f"TXXX:{name}") if tags else None

        if value:
            text = str(value.text[0]).strip()

            if text:
                return text

    return ""


def _front_cover(tags):
    """The embedded picture, found by its type and not by its label.

    The label is free text: this tool writes "Cover art", the version
    before the repository wrote "Stored cover art", other taggers write
    something else. Looking one up by name is what made 105 songs in one
    library look as though they had no picture at all.
    """

    for picture in tags.getall("APIC") if tags else []:
        if picture.type == 3:
            return picture

    return None


def song_id(song_path: Path, tags) -> str:
    """The id, from the tag first and the filename second.

    The same two sources the model uses, in the same order, so a song
    this cannot identify is one the model cannot identify either.
    """

    identifier = _custom(tags, "YouTube ID")

    if identifier:
        return identifier

    match = re.match(r"^.*\[(?P<id>[^\]]+)\]$", song_path.stem)

    return match.group("id") if match else ""


def read_frames(song_path: Path) -> dict:
    """A flat view of everything the old frames hold.

    Separate from building the document so that a comparison pass can
    show what was read beside what was made of it — the step that has to
    be inspectable is the inference, not the reading.
    """

    tags = mutagen.mp3.MP3(song_path).tags
    picture = _front_cover(tags)

    shazam = {
        name: _custom(tags, *names)
        for name, names in _SHAZAM_FRAMES.items()
    }
    # Only Shazam ever supplies one, so a file that carries a recording
    # code carries Shazam's — even though the frame is a standard one and
    # anything could in principle have written it.
    shazam["isrc"] = _text(tags, _ISRC_FRAME)

    return {
        "id": song_id(song_path, tags),
        "values": {
            field: _text(tags, frame) for field, frame in _TEXT_FRAMES.items()
        },
        "cover": {
            "requested": _custom(tags, "Cover art URL"),
            "embedded_from": _custom(tags, "Stored cover art URL"),
            "sha256": (
                hashlib.sha256(picture.data).hexdigest() if picture else ""
            ),
            "label": picture.desc if picture else "",
        },
        "shazam": shazam,
        "junk_filename": "(JUNK)" in song_path.name,
    }


def shazam_answer(frames: dict) -> dict:
    """What Shazam said, as a source entry, or {} if it never answered.

    The score is kept as a number when the frame holds one. A song can
    carry an answer and no score — the older generation of frames wrote
    the rate for only 18 of the 55 songs that have the names.
    """

    raw = frames["shazam"]

    if not any(raw.values()):
        return {}

    answer = {key: raw[key] for key in ("artist", "title") if raw[key]}

    if raw["cover"]:
        answer["cover"] = raw["cover"]

    if raw["isrc"]:
        answer["isrc"] = raw["isrc"]

    if raw["score"]:
        try:
            answer["score"] = int(float(raw["score"]))
        except ValueError:
            pass

    return answer


def matched(frames: dict) -> bool:
    """Whether Shazam's answer was good enough to have been applied.

    Read from the score when there is one. When there is not — the case
    for every song imported before the provenance frames existed — the
    cover URL answers instead: Shazam's artwork comes from Apple's CDN,
    and a YouTube thumbnail means it never matched.
    """

    score = shazam_answer(frames).get("score")

    if score is not None:
        return score >= MATCH_THRESHOLD

    return SHAZAM_COVER_HOST in frames["cover"]["requested"]


def setter_for(field: str, frames: dict) -> str:
    """Who set a field, where that can be established rather than guessed.

    Only one case is certain: the value matches what Shazam proposed and
    the match was good enough to have been applied. Everything else is
    `legacy` — including values that plainly came from YouTube, because
    "plainly" is not a record and a later edit is indistinguishable from
    the original.
    """

    value = frames["values"].get(field, "")

    if not value:
        return "legacy"

    proposed = frames["shazam"].get(field)

    if proposed and value == proposed and matched(frames):
        return "shazam"

    return "legacy"


def document_from_frames(song_path: Path) -> dict:
    """Everything the old frames hold, as a document.

    Writes nothing. Timestamps are null throughout: no frame records when
    anything happened, and the file's own date has been moved by the peak
    store and by two repair passes since.
    """

    frames = read_frames(song_path)
    document = metadata.blank(frames["id"])

    for field, value in frames["values"].items():
        if value:
            document = metadata.set_field(
                document, field, value, setter_for(field, frames), at=None
            )

    if frames["cover"]["requested"]:
        document = metadata.set_field(
            document, "cover", frames["cover"]["requested"], "legacy", at=None
        )

    answer = shazam_answer(frames)

    if answer:
        document = metadata.set_source(document, "shazam", answer, at=None)

    if frames["cover"]["sha256"] or frames["cover"]["embedded_from"]:
        document = metadata.set_embedded_cover(
            document,
            frames["cover"]["sha256"],
            frames["cover"]["embedded_from"],
            at=None,
        )

    return document
