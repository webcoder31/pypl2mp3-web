#!/usr/bin/env python3
"""Locate one song in the repository by its YouTube id.

Shared by every operation that acts on a single named song rather than on
a selection: junkizing, streaming, and anything that follows.

Matching is exact, on the id embedded in the filename. Not a fuzzy
keyword search — callers use this when they mean one specific song, and
some of them destroy data.
"""

from pathlib import Path

from pypl2mp3.libs.repository import get_repository_song_files
from pypl2mp3.libs.utils import get_song_id_from_filename


class SongNotFound(Exception):
    """No song in the repository carries that YouTube id."""


def find_song_file(repository_path: Path, youtube_id: str) -> Path:
    """Return the path of the song with this id.

    The id is read from each filename rather than by building a SongModel
    per candidate: that constructor rewrites the ID3 header of any file
    lacking a YouTube id tag, so scanning that way would modify files just
    to look at them.

    Raises:
        SongNotFound: if no song in the repository has that id.
    """

    repository_path = Path(repository_path)

    for song_file in get_repository_song_files(repository_path) or []:
        if get_song_id_from_filename(song_file.name) == youtube_id:
            return _ensure_inside(repository_path, song_file)

    raise SongNotFound(youtube_id)


def _ensure_inside(repository_path: Path, song_file: Path) -> Path:
    """Refuse a path that escapes the repository.

    The id comes from a URL, so this is the boundary where a crafted value
    could otherwise reach an arbitrary file. The candidates come from a
    repository scan and cannot currently escape, but callers stream these
    paths straight to a browser — the check belongs here, once, rather
    than being remembered at each call site.
    """

    resolved = song_file.resolve()
    root = repository_path.resolve()

    if not resolved.is_relative_to(root):
        raise SongNotFound(song_file.name)

    return resolved
