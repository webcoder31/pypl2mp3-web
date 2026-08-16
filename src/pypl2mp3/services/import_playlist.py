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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pytubefix import Playlist, YouTube

from pypl2mp3.libs.repository import get_repository_playlist
from pypl2mp3.libs.song import SongModel
from pypl2mp3.libs.waveform import peaks_for
from pypl2mp3.libs.utils import get_song_id_from_filename, get_song_id_from_url
from pypl2mp3.ports.progress import ProgressPort
from pypl2mp3.services._song_callbacks import create_from_youtube_callbacks

DEFAULT_SHAZAM_THRESHOLD = 50

# Stage name for the per-song boundary. The sub-stages that follow
# (download, encode, shazam) belong to whichever song was last announced.
SONG_STAGE = "song"

# How many extra passes to make over songs YouTube refused. Refusals have
# been observed to clear on their own — a video that raised BotDetection
# mid-import fetched cleanly moments later. Age restriction and region
# blocking never clear, so they are not retried at all.
DEFAULT_RETRY_PASSES = 1


def root_cause(error: BaseException) -> BaseException:
    """Walk to the deepest cause.

    SongModel wraps everything in a SongModelException, so the surface
    message reads "Failed to fetch information" whether the video is age
    restricted, region blocked, or simply refused. The distinction lives
    at the bottom of the chain.
    """

    seen = {id(error)}
    current = error

    while True:
        deeper = current.__cause__ or current.__context__
        if deeper is None or id(deeper) in seen:
            return current
        seen.add(id(deeper))
        current = deeper


def is_bot_detection(error: BaseException) -> bool:
    """Whether YouTube refused this request, rather than the video being
    off limits.

    The only failure worth retrying: age restriction and region blocking
    are properties of the video and will hold on a second attempt.
    """

    return type(root_cause(error)).__name__ == "BotDetection"


def failure_reason(error: BaseException) -> str:
    """A short, honest label for why a song did not import."""

    name = type(root_cause(error)).__name__

    return {
        "AgeRestrictedError": "age restricted",
        "AgeCheckRequiredError": "age restricted",
        "AgeCheckRequiredAccountError": "age restricted",
        "LoginRequired": "login required",
        "VideoRegionBlocked": "blocked in this country",
        "VideoPrivate": "private",
        "MembersOnly": "members only",
        "VideoUnavailable": "unavailable",
        "VideoRemovedByUploader": "removed by uploader",
        "VideoRemovedByYouTubeForViolatingTOS": "removed by YouTube",
        "VideoBlockedByCopyright": "blocked for copyright",
        "AccountTerminated": "account terminated",
        "BotDetection": "refused by YouTube",
        "SABRError": "stream protection",
        "LiveStreamError": "live stream",
    }.get(name, name)


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
    reason: str = ""
    retryable: bool = False


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
    retry_passes: int = DEFAULT_RETRY_PASSES,
    only: Optional[list[str]] = None,
) -> ImportReport:
    """Download the songs the playlist has and the repository lacks.

    Args:
        repository_path: folder where playlists are stored.
        playlist_id: id, URL or index of the playlist.
        progress: receives stage events; the per-song boundary is reported
            as a `song` stage whose label names the song.
        shazam_threshold: minimum Shazam score to accept an identification.
        retry_passes: extra sweeps over songs YouTube refused. Only those:
            an age-restricted video is just as restricted the second time.
        only: import just these, instead of everything missing. What is
            already on disk is still skipped, and an id the playlist does
            not hold is ignored rather than fetched — a selection narrows
            what was offered, it is never a way to reach outside it.
            `None` means everything missing; an empty list means nothing,
            which is not the same thing.

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

    if only is not None:
        # Intersected with what is genuinely missing rather than trusted:
        # the list was built by a check that may be minutes old, the songs
        # may have been fetched by another run since, and the ids may not
        # be this playlist's at all.
        wanted = set(only)
        missing = [song_id for song_id in missing if song_id in wanted]

    # The whole run, announced before any of it starts. A caller drawing
    # rows otherwise learns of each song only as it is reached, so a
    # selection of twelve shows one row and grows — and any song left out
    # of the selection would go on looking like it was still coming.
    for song_id in missing:
        progress.item_listed(song_id, "")

    imported: list[ImportedSong] = []
    failed: list[FailedImport] = []

    async def sweep(ids: list[str], prefix: str = "") -> list[FailedImport]:
        """Import each id, collecting rather than raising failures."""

        rejected: list[FailedImport] = []

        for index, youtube_id in enumerate(ids, 1):
            position = f"{prefix}{index}/{len(ids)}"

            # Announced before anything is attempted, so a panel can show
            # the row as running rather than leaving it blank for however
            # long YouTube takes to answer.
            progress.item_started(youtube_id, position)

            try:
                song = await _import_one(
                    youtube_id,
                    playlist_path,
                    shazam_threshold,
                    progress,
                    position,
                )
            except Exception as exc:
                # One song failing must not end the run: a dropped
                # connection on song 3 of 34 used to lose the other 31.
                cause = root_cause(exc)
                reason = failure_reason(exc)
                issue = f"{type(cause).__name__}: {cause}"
                # Reported as it happens, not only in the final report:
                # a run of 34 songs takes minutes, and a failure nobody
                # is told about until the end is a failure nobody can act
                # on while there is still time.
                progress.item_failed(youtube_id, reason, issue)
                rejected.append(
                    FailedImport(
                        youtube_id=youtube_id,
                        song_name=f"Video ID: {youtube_id}",
                        issue=issue,
                        reason=reason,
                        retryable=is_bot_detection(exc),
                    )
                )
                continue

            progress.item_done(youtube_id)
            imported.append(song)

        return rejected

    failed = await sweep(missing)

    # Retry only what YouTube refused. Those have been seen to succeed on
    # a later attempt; an age-restricted video never will, and retrying it
    # would just spend time to reach the same answer.
    for attempt in range(retry_passes):
        retryable = [item.youtube_id for item in failed if item.retryable]
        if not retryable:
            break

        permanent = [item for item in failed if not item.retryable]
        failed = permanent + await sweep(retryable, prefix=f"retry {attempt + 1}: ")

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

    await asyncio.to_thread(_store_waveform, song.path)

    return ImportedSong(
        youtube_id=youtube_id,
        filename=song.filename,
        artist=song.artist or "",
        title=song.title or "",
        shazam_match_score=song.shazam_match_score,
        is_junk=bool(song.has_junk_filename),
    )


def _store_waveform(song_path: Path) -> None:
    """Compute and store the song's waveform, here rather than later.

    The file is on disk and freshly encoded, and half a second of ffmpeg
    is nothing beside the download that just finished. Left undone, that
    same half second is paid by whoever first presses play — which is the
    one moment somebody is waiting.

    Best effort in both directions: a waveform that cannot be computed is
    not a failed import, and the player recomputes or falls back to the
    plain bar on its own.
    """

    try:
        peaks_for(song_path)
    except Exception:
        pass
