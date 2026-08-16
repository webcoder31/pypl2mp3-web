#!/usr/bin/env python3
"""Compare a local playlist against its YouTube source.

This is the one operation whose duration is genuinely unpredictable: it
depends entirely on the link quality at the time of the call. That is why
it never runs on the synchronous path of a page render — it runs as a job,
and its result is cached and timestamped by the caller.
"""

from dataclasses import dataclass
from pathlib import Path

from pytubefix import Playlist, YouTube

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
    with_labels: bool = False,
) -> NewSongsReport:
    """List the videos present remotely but missing locally.

    Args:
        repository_path: folder where playlists are stored.
        playlist_id: id, URL or index of the playlist.
        progress: receives the stage, and each missing song if asked.
        with_labels: also announce every missing song by name, one
            `item_listed` at a time. Off by default, and it has to be:
            a name costs one YouTube request per song, so a check of
            thirty new songs goes from one request to thirty-one. A
            caller that only counts them should not pay that.

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

    if with_labels:
        for done, song_id in enumerate(missing, 1):
            # Announced one at a time rather than in a batch at the end:
            # each name is a network round trip, and a panel that fills
            # in as they arrive beats one that shows nothing for a minute.
            progress.item_listed(song_id, _name_of(song_id))
            progress.stage_progress(STAGE, done * 100.0 / len(missing))

    progress.stage_progress(STAGE, 100.0)
    progress.stage_done(STAGE)

    return NewSongsReport(
        playlist_id=selected.id,
        total_remote=len(remote_ids),
        already_local=len(remote_ids) - len(missing),
        missing=missing,
    )


def _name_of(youtube_id: str) -> str:
    """A video's "author - title", or "" if YouTube will not say.

    Empty rather than the id: the caller shows the id anyway, and a name
    that is secretly an id reads as a song called "dQw4w9WgXcQ" rather
    than as a song nobody could name.

    Empty rather than raising, either. YouTube refuses these often enough
    — bot detection, age restriction, a deleted video — that treating a
    refusal as fatal would make the panel unusable on exactly the
    playlists that need it most. What is missing is the name; the song
    can still be imported.
    """

    try:
        video = YouTube(f"https://youtube.com/watch?v={youtube_id}")

        return f"{video.author} - {video.title}"
    except Exception:
        return ""
