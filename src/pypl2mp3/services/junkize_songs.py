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

from pypl2mp3.libs.song import SongModel
from pypl2mp3.services.find_song import SongNotFound, find_song_file

__all__ = ["JunkizeResult", "SongNotFound", "junkize_song"]


@dataclass(frozen=True)
class JunkizeResult:
    """What changed, so a caller can report it without re-reading the disk."""

    youtube_id: str
    previous_filename: str
    filename: str
    path: Path


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

    song_file = find_song_file(repository_path, youtube_id)
    song = SongModel(song_file)
    previous_filename = song_file.name

    song.reset_state()
    song.fix_filename()

    return JunkizeResult(
        youtube_id=youtube_id,
        previous_filename=previous_filename,
        filename=song.filename,
        path=song_file.parent / song.filename,
    )
