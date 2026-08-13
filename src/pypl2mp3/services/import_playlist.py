#!/usr/bin/env python3
"""Import the songs a YouTube playlist has and the repository does not.

Non-interactive: every new song is imported. The CLI's `-p` prompt mode
needs an InteractionPort implementation the web layer does not have yet,
and skipping songs one by one is a separate concern from getting the
import to run at all.

Every blocking step inside `SongModel.create_from_youtube` now runs off
the event loop, so this coroutine can be awaited directly by a web server
without freezing it.
"""

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pytubefix import Playlist, YouTube

from pypl2mp3.libs.repository import get_repository_playlist
from pypl2mp3.libs.song import SongModel
from pypl2mp3.libs.utils import get_song_id_from_filename, get_song_id_from_url
from pypl2mp3.ports.progress import ProgressPort
from pypl2mp3.services._song_callbacks import create_from_youtube_callbacks

DEFAULT_SHAZAM_THRESHOLD = 50

# Seconds to leave between two songs. A 34-song import with no spacing at
# all had 8 requests refused outright with "This request was detected as a
# bot" and 12 more fail to fetch — 20 of 34 lost. SongModel already paces
# its Shazam calls 15s apart; nothing paced YouTube, and that asymmetry is
# what tripped the detector.
DEFAULT_REQUEST_INTERVAL = 4.0

# Where the pause goes once YouTube has already objected. Backing off from
# 4s doubles to 8, 16, 32, then holds — long enough to matter, bounded so a
# long playlist still finishes.
MAX_REQUEST_INTERVAL = 32.0

# Fragments that mark a refusal rather than a broken video. Matched
# case-insensitively against the exception text.
_RATE_LIMIT_MARKERS = (
    "detected as a bot",
    "too many requests",
    "http error 429",
)

# Stage name for the per-song boundary. The sub-stages that follow
# (download, encode, shazam) belong to whichever song was last announced.
SONG_STAGE = "song"


def looks_rate_limited(error: BaseException) -> bool:
    """Whether YouTube refused us rather than the video being broken.

    Matched on the message: pytubefix raises BotDetection for the explicit
    case, but the same throttling also surfaces as a plain failure to
    fetch video information, and both call for backing off rather than
    charging on.
    """

    text = f"{type(error).__name__}: {error}".lower()

    return any(marker in text for marker in _RATE_LIMIT_MARKERS)


class _Pacer:
    """Keeps a minimum gap between YouTube requests, widening on refusal."""

    def __init__(self, interval: float):
        self._interval = interval
        self._last_request: Optional[float] = None

    @property
    def interval(self) -> float:
        return self._interval

    async def wait(self) -> float:
        """Sleep until the next request is due. Returns what it waited."""

        if self._interval <= 0:
            return 0.0

        now = time.monotonic()
        if self._last_request is not None:
            remaining = self._interval - (now - self._last_request)
            if remaining > 0:
                await asyncio.sleep(remaining)
                self._last_request = time.monotonic()
                return remaining

        self._last_request = time.monotonic()

        return 0.0

    def penalise(self) -> None:
        """Double the gap, up to the cap. Call after a refusal."""

        self._interval = min(max(self._interval, 1.0) * 2, MAX_REQUEST_INTERVAL)


@dataclass(frozen=True)
class ImportedSong:
    """One song that made it to disk."""

    youtube_id: str
    filename: str
    artist: str
    title: str
    shazam_match_score: Optional[float]
    is_junk: bool


@dataclass(frozen=True)
class FailedImport:
    """One song that did not, and why."""

    youtube_id: str
    song_name: str
    issue: str


@dataclass(frozen=True)
class ImportReport:
    """The outcome of one import run."""

    playlist_id: str
    total_remote: int
    already_local: int
    imported: list[ImportedSong] = field(default_factory=list)
    failed: list[FailedImport] = field(default_factory=list)


async def import_playlist(
    repository_path: Path,
    playlist_id: str,
    progress: ProgressPort,
    shazam_threshold: float = DEFAULT_SHAZAM_THRESHOLD,
    request_interval: Optional[float] = None,
) -> ImportReport:
    """Download every song the playlist has and the repository lacks.

    Args:
        repository_path: folder where playlists are stored.
        playlist_id: id, URL or index of the playlist.
        progress: receives stage events; the per-song boundary is reported
            as a `song` stage whose label names the song.
        shazam_threshold: minimum Shazam score to accept an identification.
        request_interval: seconds to leave between songs, widened when
            YouTube starts refusing. Zero disables pacing entirely. None
            resolves to DEFAULT_REQUEST_INTERVAL at call time, so a test
            can neutralise the wait by patching that constant.

    Returns:
        What was imported and what failed. A song that fails does not
        abort the run — reporting nothing after a partial import would
        hide work that did reach the disk.

    Raises:
        Exception: whatever pytubefix raises if the playlist itself cannot
            be reached. Never swallowed: an empty report after a network
            failure would read as "nothing new".
    """

    repository_path = Path(repository_path)
    selected = get_repository_playlist(
        repository_path, playlist_id, must_exist=False
    )

    progress.stage_started(SONG_STAGE, "Retrieving playlist")

    # pytubefix fetches lazily; every attribute read below can raise, and
    # a failure here is fatal to the whole run rather than to one song.
    playlist = Playlist(selected.url)
    remote_ids = [
        song_id
        for song_id in map(get_song_id_from_url, playlist.video_urls)
        if song_id is not None
    ]
    playlist_path = repository_path / (
        f"{playlist.owner} - {playlist.title} [{selected.id}]"
    )

    playlist_path.mkdir(parents=True, exist_ok=True)
    local_ids = {
        song_id
        for song_id in map(
            get_song_id_from_filename, playlist_path.glob("*.mp3")
        )
        if song_id is not None
    }

    missing = [song_id for song_id in remote_ids if song_id not in local_ids]

    imported: list[ImportedSong] = []
    failed: list[FailedImport] = []
    pacer = _Pacer(
        DEFAULT_REQUEST_INTERVAL if request_interval is None
        else request_interval
    )

    for index, youtube_id in enumerate(missing, 1):
        position = f"{index}/{len(missing)}"

        # Space the requests out. Announced when the wait is long enough
        # to look like a hang, silent when it is not.
        if pacer.interval > 2:
            progress.stage_started(
                SONG_STAGE,
                f"{position} waiting {pacer.interval:.0f}s for YouTube",
            )
        await pacer.wait()

        try:
            song = await _import_one(
                youtube_id,
                playlist_path,
                shazam_threshold,
                progress,
                position,
            )
        except Exception as exc:
            # One song failing must not end the run: a dropped connection
            # on song 3 of 34 used to lose the other 31.
            if looks_rate_limited(exc):
                # Charging on after a refusal just collects more refusals.
                pacer.penalise()

            failed.append(
                FailedImport(
                    youtube_id=youtube_id,
                    song_name=f"Video ID: {youtube_id}",
                    issue=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        imported.append(song)

    progress.stage_done(SONG_STAGE)

    return ImportReport(
        playlist_id=selected.id,
        total_remote=len(remote_ids),
        already_local=len(remote_ids) - len(missing),
        imported=imported,
        failed=failed,
    )


async def _import_one(
    youtube_id: str,
    playlist_path: Path,
    shazam_threshold: float,
    progress: ProgressPort,
    position: str,
) -> ImportedSong:
    """Import one song, announcing which one is in flight."""

    video = YouTube(f"https://youtube.com/watch?v={youtube_id}")

    # Read the lazy attributes here, inside this function's own failure
    # scope: the constructor performs no I/O, the request fires on first
    # attribute access.
    label = f"{position} {video.author} - {video.title}"
    progress.stage_started(SONG_STAGE, label)

    song: SongModel = await SongModel.create_from_youtube(
        youtube_id,
        playlist_path,
        shazam_threshold,
        **create_from_youtube_callbacks(progress),
    )

    return ImportedSong(
        youtube_id=youtube_id,
        filename=song.filename,
        artist=song.artist or "",
        title=song.title or "",
        shazam_match_score=song.shazam_match_score,
        is_junk=bool(song.has_junk_filename),
    )
