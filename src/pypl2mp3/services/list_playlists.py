#!/usr/bin/env python3
"""Inventory of local playlists.

Reads the filesystem exclusively: no network call, ever. The service knows
neither terminal nor browser; it renders data, the facade takes care of
presenting it.
"""

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

    @property
    def valid_songs(self) -> int:
        """Songs correctly tagged, i.e. not "junk"."""

        return self.total_songs - self.junk_songs

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

    return PlaylistSummary(
        path=playlist_path,
        playlist_id=playlist_id,
        name=playlist_path.name.replace(f"[{playlist_id}]", "").strip(),
        total_songs=len(list(playlist_path.glob("*.mp3"))),
        junk_songs=len(list(playlist_path.glob("* (JUNK).mp3"))),
    )
