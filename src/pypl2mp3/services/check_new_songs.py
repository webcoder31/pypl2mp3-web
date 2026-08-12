#!/usr/bin/env python3
"""Compare a local playlist against its YouTube source.

This is the one operation whose duration is genuinely unpredictable: it
depends entirely on the link quality at the time of the call. That is why
it never runs on the synchronous path of a page render — it runs as a job,
and its result is cached and timestamped by the caller.
"""

from dataclasses import dataclass
from pathlib import Path

from pytubefix import Playlist

from pypl2mp3.libs.repository import get_repository_playlist
from pypl2mp3.libs.utils import get_song_id_from_filename, get_song_id_from_url
from pypl2mp3.ports.progress import ProgressPort

STAGE = "check_new_songs"


@dataclass(frozen=True)
class NewSongsReport:
    """What the remote playlist has that the local folder does not."""

    playlist_id: str
    total_remote: int
    already_local: int
    missing: list[str]


def check_new_songs(
    repository_path: Path,
    playlist_id: str,
    progress: ProgressPort,
) -> NewSongsReport:
    """List the videos present remotely but missing locally.

    Raises:
        Exception: whatever pytubefix raises if the playlist cannot be
            reached. Never swallowed — reporting "nothing new" after a
            network failure would be a lie.
    """

    progress.stage_started(STAGE, "Checking for new songs:")

    selected = get_repository_playlist(
        Path(repository_path), playlist_id, must_exist=False
    )

    # pytubefix fetches lazily; every attribute read below can raise.
    playlist = Playlist(selected.url)
    remote_ids = [
        song_id
        for song_id in map(get_song_id_from_url, playlist.video_urls)
        if song_id is not None
    ]

    playlist_folder = Path(repository_path) / (
        f"{playlist.owner} - {playlist.title} [{selected.id}]"
    )
    local_ids = {
        song_id
        for song_id in map(
            get_song_id_from_filename,
            playlist_folder.glob("*.mp3"),
        )
        if song_id is not None
    }

    missing = [song_id for song_id in remote_ids if song_id not in local_ids]

    progress.stage_progress(STAGE, 100.0)
    progress.stage_done(STAGE)

    return NewSongsReport(
        playlist_id=selected.id,
        total_remote=len(remote_ids),
        already_local=len(remote_ids) - len(missing),
        missing=missing,
    )
