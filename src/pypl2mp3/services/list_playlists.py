#!/usr/bin/env python3
"""Inventory of local playlists.

Reads the filesystem exclusively: no network call, ever. The service knows
neither terminal nor browser; it renders data, the facade takes care of
presenting it.
"""

import datetime
import os
import re
from dataclasses import dataclass
from pathlib import Path

from pypl2mp3.libs.utils import get_song_id_from_filename, natural_sort_key

# A playlist folder ends with its identifier in brackets.
_PLAYLIST_PATTERN = re.compile(r"^.*\[(.?[^\]]+)\]$")


@dataclass(frozen=True)
class PlaylistSummary:
    """What we know about a playlist without querying YouTube."""

    path: Path
    playlist_id: str
    name: str
    total_songs: int
    junk_songs: int
    # Epoch seconds, or 0 for a folder holding nothing.
    last_change: float = 0.0

    @property
    def valid_songs(self) -> int:
        """Songs correctly tagged, i.e. not "junk"."""

        return self.total_songs - self.junk_songs

    @property
    def changed_on(self) -> str:
        """The day this playlist last gained or lost a song, or "".

        The newest mp3's own timestamp, and it says *changed* rather than
        *imported* deliberately: saving metadata rewrites the file, so
        this moves for a correction as much as for an arrival. From the
        folder's side those are one thing — something came in, or
        something was put right — and a date quietly meaning only the
        first would be wrong half the time.
        """

        if not self.last_change:
            return ""

        return datetime.date.fromtimestamp(self.last_change).isoformat()

    @property
    def youtube_url(self) -> str:
        """Where this playlist lives, for going and looking at it.

        Built from the id in the folder's own name, which is the only
        thing here that came from YouTube — no request is made, and the
        address is right whether or not the playlist still exists.
        """

        return f"https://www.youtube.com/playlist?list={self.playlist_id}"

    @property
    def owner(self) -> str:
        """Who the playlist belongs to, or "" if the name does not say.

        A folder is named "Owner - Title", so the split is on the first
        separator only: a title may well contain another one, and
        "Best of - Live" belongs to the title, not to a second owner.
        """

        owner, separator, _ = self.name.partition(" - ")

        return owner.strip() if separator else ""

    @property
    def title(self) -> str:
        """The playlist itself, without whose it is.

        The whole name when there is no separator: better a title that
        happens to read like an owner than a playlist with no name.
        """

        _, separator, title = self.name.partition(" - ")

        return (title.strip() if separator else self.name.strip()) or self.name


def list_playlists(repository_path: Path) -> list[PlaylistSummary]:
    """Summarize each playlist in the repository, sorted in natural order.

    Args:
        repository_path: folder containing the playlists.

    Returns:
        A summary per playlist. Empty list if the repository has none.
    """

    paths = [
        Path(path)
        for path in repository_path.glob("*/")
        if _PLAYLIST_PATTERN.match(str(path))
    ]
    paths.sort(key=natural_sort_key)

    return [_summarize(path) for path in paths]


def _summarize(playlist_path: Path) -> PlaylistSummary:
    playlist_id = get_song_id_from_filename(playlist_path.name)

    # One pass rather than three. Two globs counted the songs and the
    # junk among them, and the newest timestamp would have been a third
    # walk of the same folder — scandir carries the name and the stat
    # together, so all of it comes off one listing.
    total = junk = 0
    newest = 0.0

    with os.scandir(playlist_path) as entries:
        for entry in entries:
            if not entry.name.endswith(".mp3"):
                continue

            total += 1
            if entry.name.endswith(" (JUNK).mp3"):
                junk += 1

            newest = max(newest, entry.stat().st_mtime)

    return PlaylistSummary(
        path=playlist_path,
        playlist_id=playlist_id,
        name=playlist_path.name.replace(f"[{playlist_id}]", "").strip(),
        total_songs=total,
        junk_songs=junk,
        last_change=newest,
    )
