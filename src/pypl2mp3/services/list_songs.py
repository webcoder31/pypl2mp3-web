#!/usr/bin/env python3
"""Song inventory, filtered.

Backs both the `songs` and `junks` commands: they are the same query with
`junk_only` flipped, so they are one service rather than two.

Reads the local filesystem only — no network call, ever. Building a
SongModel parses the file's ID3 tags, which is disk work, not a request.
"""

import datetime
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pypl2mp3.libs.repository import get_repository_songs
from pypl2mp3.libs.song import SongModel

DEFAULT_MATCH_THRESHOLD = 45


# The order the sentence names them in, which is the order the panel
# shows them in. Dictionary order would follow whatever was written last.
_BY_HAND_ORDER = (
    "artist", "title", "cover", "album", "year", "genre", "publisher",
)


def release_line(album: str, year: str, genre: str, publisher: str) -> str:
    """The release data as one labelled line, or nothing at all.

    Joined here rather than in a template because the parts are each
    optional: Shazam answers with all four, three, or none, and a
    template assembling separators around holes is where the stray
    middot comes from.

    A function and not only a property, because two places show this now
    — the listing's board and the panel offering Shazam's answer — and a
    second implementation would be a second format.
    """

    line = " · ".join(part for part in (album, year, genre, publisher) if part)

    return f"Album: {line}" if line else ""


def recording_line(isrc: str) -> str:
    """The recording code, opened out into what it says.

    `FRZ031900123` is four things run together and nobody reads it as
    four. Country of the registrant, year of reference, the registrant
    itself, then its own numbering.

    Labelled `Recording`, which is the standard's own word — ISRC is the
    International Standard Recording Code. It identifies a take, not a
    disc and not a song: two recordings of one piece carry two codes,
    which is what settled Chill Rob G against Snap!.

    The year is shown as the registrant wrote it, and that is the point:
    38 codes in this library predate the standard, so the field is
    whatever was put there — usually the recording's own year. A 1973
    code on a 2025 release says the reissue kept the take.

    A string that is not a code is shown whole rather than split into
    four parts it does not have. At least the error is visible.
    """

    code = (isrc or "").replace("-", "").upper()

    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{3}\d{7}", code):
        return f"Recording (ISRC): {isrc}" if isrc else ""

    two = int(code[5:7])
    pivot = datetime.date.today().year % 100
    year = 2000 + two if two <= pivot else 1900 + two

    return (
        f"Recording (ISRC): {code[:2]} · {year} · {code[2:5]} · {code[7:]}"
    )


@dataclass(frozen=True)
class SongSummary:
    """What a listing needs about one song, without reopening the file."""

    path: Path
    youtube_id: str
    artist: str
    title: str
    playlist: str
    duration: str
    is_junk: bool
    # What Shazam knows about the release, when it matched the song.
    # Empty strings rather than None: every consumer is a template, and
    # a template treats both the same while None reads back as "None".
    album: str = ""
    publisher: str = ""
    year: str = ""
    genre: str = ""
    # Where the file came from, when the document knows. The video's own
    # title is the only place the original name survives: the import
    # takes it, Shazam overwrites it, and on 652 songs the two differ.
    origin_author: str = ""
    origin_title: str = ""
    # The recording code, from Shazam's answer and nowhere else. Not a
    # field: it is not something the file asserts about itself, it is
    # what one upstream replied.
    isrc: str = ""
    # The fields somebody typed, as opposed to the ones a pass proposed.
    # A tuple and not a set: the sentence built from it has to come out
    # the same way twice.
    set_by_hand: tuple[str, ...] = ()
    # And whether asking YouTube about it is still worth a click. Eleven
    # videos have gone; the link to them answers 404 without saying so.
    video_gone: bool = False

    @property
    def cover_version(self) -> int:
        """A number that changes whenever the file does.

        The cover lives at /songs/<id>/cover, an address that never
        changes, and the response carries no validator of any kind — so a
        browser that has seen it once keeps showing it. Saving a new cover
        URL replaced the picture on disk and left the old one on screen,
        which read as the save having failed.

        The file's own timestamp is the cheapest thing that moves. It also
        moves when something unrelated is written — a tag edit, the
        waveform peaks — and the cover is then fetched again for nothing.
        That is a few tens of kilobytes over a loopback connection, which
        is a smaller price than a stale picture.

        A property and not a field: the listing builds one summary per
        song and nine hundred stat() calls would be paid by every page,
        while only the two panels that draw a cover ever read this.
        """

        try:
            return int(self.path.stat().st_mtime)
        except OSError:
            # The file went while the page was being built. The panel is
            # about to 404 anyway; it should not do it from here.
            return 0

    @property
    def release(self) -> str:
        """The release line. See `release_line`."""

        return release_line(self.album, self.year, self.genre, self.publisher)

    @property
    def recording(self) -> str:
        """The recording code, opened out. See `recording_line`."""

        return recording_line(self.isrc)

    @property
    def playlist_face(self) -> str:
        """The playlist, labelled like the rest."""

        return f"Playlist: {self.playlist_name}"

    @property
    def by_hand(self) -> str:
        """What was typed rather than found, as a sentence, or nothing.

        The warning that was missing in front of Ask Shazam. A match
        overwrites artist, title and cover without asking, and a value
        somebody typed is the one thing in the file that asking again
        cannot bring back — which is exactly what the backfill had to
        work around by refusing to call `shazam_song` at all.

        A sentence rather than a mark on each field: three marks say the
        same thing three times and read as decoration, and the reader has
        to work out what they mean. One line says it once, in words, at
        the moment it matters.
        """

        if not self.set_by_hand:
            return ""

        names = list(self.set_by_hand)
        listed = (
            names[0] if len(names) == 1
            else ", ".join(names[:-1]) + f" and {names[-1]}"
        )

        return (
            f"{listed} set by hand — Ask Shazam would replace "
            f"{'it' if len(names) == 1 else 'them'}"
        )

    @property
    def by_hand_short(self) -> str:
        """The same warning, short enough for a row that is already full.

        It had a row of its own and that row cost the panel 25px, which
        was the difference between landing on the cover and overrunning
        it. What is left is the half a reader acts on — which fields —
        with the consequence in the tooltip.
        """

        if not self.set_by_hand:
            return ""

        return f"{', '.join(self.set_by_hand)} set by hand"

    @property
    def origin(self) -> str:
        """The video this file was made from, as one line.

        Channel first, then the video's own title — the same order the
        eye reads a listing row in. Empty when the origin was never
        recovered, which is what keeps it off the board: a face with
        nothing to say should not take a turn.

        Prefixed, as they all are now. It was the first face to need it,
        back when it was the only one: both lines were middot-joined and
        "Chill Masters · SYNAPSON - Djon Maya Maï" read exactly like a
        label and an album.
        """

        line = " · ".join(
            part for part in (self.origin_author, self.origin_title) if part
        )

        return f"From: {line}" if line else ""

    @property
    def label(self) -> str:
        """Artist and title as one line, for a single-column display."""

        return f"{self.artist} - {self.title}"

    @property
    def short_duration(self) -> str:
        """`6:17`, not `00:06:17`.

        SongModel pads to a fixed eight characters so terminal columns
        line up. On screen those leading zeros are three characters of
        nothing, repeated down every row of a 900-row listing.
        """

        parts = self.duration.split(":")
        while len(parts) > 2 and parts[0].strip("0") == "":
            parts.pop(0)

        return ":".join([parts[0].lstrip("0") or "0", *parts[1:]])

    @property
    def playlist_name(self) -> str:
        """The playlist without its YouTube id.

        `playlist` is the folder name, which ends in the id — the same
        forty characters repeated on every row of a listing. list_playlists
        strips it the same way for the same reason.
        """

        return re.sub(r"\s*\[[^\[\]]*\]\s*$", "", self.playlist).strip()


def list_songs(
    repository_path: Path,
    junk_only: bool = False,
    keywords: str = "",
    match_threshold: float = DEFAULT_MATCH_THRESHOLD,
    playlist_identifier: Optional[str] = None,
) -> list[SongSummary]:
    """Summarise the songs matching the given criteria.

    Args:
        repository_path: folder where playlists are stored.
        junk_only: restrict to songs Shazam could not match.
        keywords: fuzzy filter; empty means no filtering.
        match_threshold: minimum fuzzy score, 0-100.
        playlist_identifier: id, URL or index; None means every playlist.

    Returns:
        One summary per matching song, in the order the repository
        returned them. Empty when nothing matches — an empty result is a
        legitimate answer, not an error.
    """

    # Asks for the models, not the paths: selecting and sorting has
    # already parsed every candidate, so rebuilding one per path would
    # double the work. Measured at 1.2s over a 915-song repository.
    songs = get_repository_songs(
        Path(repository_path),
        junk_only=junk_only,
        keywords=keywords,
        filter_match_threshold=match_threshold,
        playlist_identifier=playlist_identifier,
    )

    # The repository helper returns None rather than [] when it finds
    # nothing; both mean the same thing here.
    return [summarize(song) for song in (songs or [])]


def summarize(song: SongModel) -> SongSummary:
    """Project a SongModel onto the fields a listing shows.

    Public so callers that already hold a model — after junkizing one, for
    instance — can render it without going back through the repository.
    """

    return SongSummary(
        path=song.path,
        youtube_id=song.youtube_id or "",
        artist=song.artist or "",
        title=song.title or "",
        playlist=song.playlist,
        duration=song.duration,
        is_junk=bool(song.has_junk_filename),
        album=song.album or "",
        publisher=song.publisher or "",
        year=song.year or "",
        genre=song.genre or "",
        set_by_hand=tuple(
            name for name in _BY_HAND_ORDER
            if song.decided_by.get(name) == "user"
        ),
        isrc=song.isrc or "",
        origin_author=song.youtube_origin.get("author") or "",
        origin_title=song.youtube_origin.get("title") or "",
        video_gone=bool(song.youtube_origin.get("gone")),
    )
