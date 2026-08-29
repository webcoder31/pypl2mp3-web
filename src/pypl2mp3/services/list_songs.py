#!/usr/bin/env python3
"""Song inventory, filtered.

Backs both the `songs` and `junks` commands: they are the same query with
`junk_only` flipped, so they are one service rather than two.

Reads the local filesystem only — no network call, ever. Building a
SongModel parses the file's ID3 tags, which is disk work, not a request.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pypl2mp3.libs.repository import get_repository_songs
from pypl2mp3.libs.song import SongModel

DEFAULT_MATCH_THRESHOLD = 45


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
        """The release data as one line, or nothing at all.

        Joined here rather than in the template because the parts are
        each optional: Shazam answers with all four, three, or none, and
        a template assembling separators around holes is where the stray
        middot comes from.
        """

        return " · ".join(
            part for part in (self.album, self.year, self.genre,
                              self.publisher) if part
        )

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
    )
