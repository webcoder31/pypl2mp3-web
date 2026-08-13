#!/usr/bin/env python3
"""Strip a song's metadata and mark it as junk.

Destructive and not undoable: it clears the ID3 tags and cover art, then
renames the file. Only the YouTube id survives, which is what makes the
song findable again afterwards.

The service acts on one song at a time. The CLI applies it in bulk behind
a confirmation prompt; a caller wanting bulk loops, so that each failure
is attributable to one song rather than aborting a whole sweep.
"""

from dataclasses import dataclass
from pathlib import Path

from pypl2mp3.libs.repository import get_repository_song_files
from pypl2mp3.libs.song import SongModel
from pypl2mp3.libs.utils import get_song_id_from_filename


class SongNotFound(Exception):
    """No song in the repository carries that YouTube id."""


@dataclass(frozen=True)
class JunkizeResult:
    """What changed, so a caller can report it without re-reading the disk."""

    youtube_id: str
    previous_filename: str
    filename: str


def junkize_song(repository_path: Path, youtube_id: str) -> JunkizeResult:
    """Clear one song's metadata and rename it as junk.

    Args:
        repository_path: folder where playlists are stored.
        youtube_id: identifies the song; it is the one field junkizing
            preserves.

    Returns:
        The filename before and after.

    Raises:
        SongNotFound: if no song in the repository has that id.
    """

    song_file = _find_by_youtube_id(Path(repository_path), youtube_id)
    song = SongModel(song_file)
    previous_filename = song_file.name

    song.reset_state()
    song.fix_filename()

    return JunkizeResult(
        youtube_id=youtube_id,
        previous_filename=previous_filename,
        filename=song.filename,
    )


def _find_by_youtube_id(repository_path: Path, youtube_id: str) -> Path:
    """Locate a song by id.

    Matching is on the id embedded in the filename rather than on a fuzzy
    keyword search: this operation destroys metadata, so it must act on
    exactly the song the caller named or on none at all.

    The id is read from the filename rather than by building a SongModel
    per candidate. Constructing one rewrites the file's ID3 header (2.4 to
    2.3), so scanning that way would silently modify every song in the
    repository just to find one.
    """

    for song_file in get_repository_song_files(repository_path) or []:
        if get_song_id_from_filename(song_file.name) == youtube_id:
            return song_file

    raise SongNotFound(youtube_id)
