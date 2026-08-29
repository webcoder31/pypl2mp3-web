#!/usr/bin/env python3
"""Repair a junk song's metadata.

Split in two rather than mirroring the CLI's dialogue. The terminal asks
for the artist, then the title, then the cover art, because a terminal can
only ask one thing at a time; a browser shows all three at once,
pre-filled, and takes one answer. So this exposes a proposal and an
application, and the interaction between them belongs to whatever is
driving — a form, or a sequence of prompts.

That is also why `fix` needs no InteractionPort: there is no dialogue to
port.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pypl2mp3.libs.song import SongModel
from pypl2mp3.ports.progress import ProgressPort
from pypl2mp3.services.find_song import SongNotFound, find_song_file

DEFAULT_SHAZAM_THRESHOLD = 50

SHAZAM_STAGE = "shazam"

__all__ = [
    "FixProposal",
    "SongNotFound",
    "apply_fix",
    "propose_fix",
]


@dataclass(frozen=True)
class FixProposal:
    """What Shazam thinks the song is, beside what the file currently says."""

    youtube_id: str
    filename: str
    current_artist: str
    current_title: str
    shazam_artist: str
    shazam_title: str
    shazam_cover_art_url: str
    shazam_match_score: Optional[float]
    has_cover_art: bool

    @property
    def matched(self) -> bool:
        """Whether Shazam returned anything worth pre-filling."""

        return bool(self.shazam_artist or self.shazam_title)


async def propose_fix(
    repository_path: Path,
    youtube_id: str,
    progress: ProgressPort,
    shazam_threshold: float = DEFAULT_SHAZAM_THRESHOLD,
) -> FixProposal:
    """Ask Shazam what this song is, without writing anything.

    Read-only by design: the caller shows the proposal, the user decides.
    Nothing reaches the file until `apply_fix`.

    Raises:
        SongNotFound: if no song carries that id.
        Exception: whatever Shazam raises. Not swallowed — an empty
            proposal would read as "Shazam found nothing", which is a
            different answer from "Shazam could not be reached".
    """

    song_file = find_song_file(repository_path, youtube_id)
    song = SongModel(song_file)

    progress.stage_started(SHAZAM_STAGE, "Shazam-ing audio track")
    await song.shazam_song(shazam_match_threshold=shazam_threshold)
    progress.stage_done(SHAZAM_STAGE)

    if song.shazam_artist or song.shazam_title:
        progress.song_identified(
            song.shazam_artist or "",
            song.shazam_title or "",
            float(song.shazam_match_score or 0),
        )

    return FixProposal(
        youtube_id=youtube_id,
        filename=song.filename,
        current_artist=song.artist or "",
        current_title=song.title or "",
        shazam_artist=song.shazam_artist or "",
        shazam_title=song.shazam_title or "",
        shazam_cover_art_url=song.shazam_cover_art_url or "",
        shazam_match_score=song.shazam_match_score,
        has_cover_art=bool(song.has_cover_art),
    )


async def apply_fix(
    repository_path: Path,
    youtube_id: str,
    artist: str,
    title: str,
    cover_art_url: str = "",
) -> FixProposal:
    """Write the given metadata to the song and rename it accordingly.

    The values are taken as given: the caller has already decided, whether
    by accepting Shazam's proposal or by overriding it.

    An empty artist or title means empty — a song with neither is what
    junk is, and clearing them is a thing somebody may well want. An
    empty cover does not: the field it comes from says "leave empty to
    keep the current one", and it used to be passed as None, which
    `update_state` reads as "clear". The embedded image survived that, so
    nothing looked wrong on screen while the file quietly lost the URL it
    would need to fetch the picture again. `False` is `update_state`'s own
    word for "do not touch".

    The cover is fetched *before* the names are written, and it is
    all-or-nothing: a cover that cannot be downloaded leaves the song
    entirely untouched. It used to write the names and the new URL first,
    so a failed fetch left the file claiming a picture it had never got.

    The order used to matter for a second reason as well — the download
    decision was made by comparing the requested URL against the one in
    the file, which `update_state` had just overwritten with that very
    request. That is fixed where it belongs now: the model keeps a record
    of where the embedded picture actually came from, and compares
    against that.

    The song stops being junk: `fix_filename` keeps the current junk
    state unless told otherwise, so `mark_as_junk=False` is what actually
    drops the suffix. The CLI does the same after a successful fix.

    Raises:
        SongNotFound: if no song carries that id.
        Exception: if the cover art cannot be fetched. Nothing has been
            written at that point, so the caller can report the failure
            and the song is as it was.
    """

    song_file = find_song_file(repository_path, youtube_id)
    song = SongModel(song_file)

    if cover_art_url:
        song.cover_art_url = cover_art_url
        await song.update_cover_art()

    song.update_state(
        artist=artist or None,
        title=title or None,
        cover_art_url=cover_art_url or False,
    )

    song.fix_filename(mark_as_junk=False)

    return FixProposal(
        youtube_id=youtube_id,
        filename=song.filename,
        current_artist=song.artist or "",
        current_title=song.title or "",
        shazam_artist=song.shazam_artist or "",
        shazam_title=song.shazam_title or "",
        shazam_cover_art_url=song.shazam_cover_art_url or "",
        shazam_match_score=song.shazam_match_score,
        has_cover_art=bool(song.has_cover_art),
    )
