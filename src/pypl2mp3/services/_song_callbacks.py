#!/usr/bin/env python3
"""Projection of a ProgressPort onto SongModel's callbacks.

Three `SongModel` APIs accept hooks, and each accepts only its own: passing
`update_cover_art` the dictionary cut for `create_from_youtube` raises a
`TypeError`. Hence one builder per API, rather than a single dictionary that
would only ever fit the first.

Two traps in `libs/song.py` are neutralized here, once and for all:

- `create_from_youtube` overwrites its fifteen callbacks with its own
  printing closures as long as `use_default_verbosity` is `True` (and
  cancels all of them if `verbose` is not `True`). Both flags are therefore
  part of the returned dictionary: a caller can no longer forget them.
- the `pre_`/`post_` hooks are awaited (`await`), whereas the progress
  callback of a `ProgressBarInterface` is called synchronously in the
  middle of the download loop. Hence the `async def` / `def` asymmetry
  below: getting it backwards only raises `TypeError` at runtime.

`libs/song.py` is left unmodified — that is deliberate. This module is 1777
lines long and carries the download and tagging logic; touching it would
risk the core value for a cosmetic gain.
"""

from dataclasses import dataclass

from pypl2mp3.libs.song import ProgressBarInterface
from pypl2mp3.ports.progress import ProgressPort


@dataclass(frozen=True)
class _Stage:
    """A measured stage: its identity for the port, its hooks for song.py.

    Attributes:
        stage: stable identifier passed on to the port.
        label: human-readable label, also used by song.py's progress bars.
        pre: name of the parameter called on entering the stage.
        on: name of the parameter receiving the `ProgressBarInterface`.
        post: name of the parameter called on leaving the stage.
    """

    stage: str
    label: str
    pre: str
    on: str
    post: str


# The three stages exposing a measured progress.
# Each carries its own identifier: that is what lets a UI tell the download
# apart from the encoding.
_DOWNLOAD_AUDIO = _Stage(
    stage="download_audio",
    label="Streaming audio:",
    pre="pre_download_audio",
    on="on_download_audio",
    post="post_download_audio",
)

_MP3_ENCODE = _Stage(
    stage="mp3_encode",
    label="Encoding audio stream to MP3:",
    pre="pre_mp3_encode",
    on="on_mp3_encode",
    post="post_mp3_encode",
)

_DOWNLOAD_COVER_ART = _Stage(
    stage="download_cover_art",
    label="Downloading cover art:",
    pre="pre_download_cover_art",
    on="on_download_cover_art",
    post="post_download_cover_art",
)

# Shazam recognition exposes no percentage: start and end, nothing in
# between, plus the identification result.
_SHAZAM_STAGE = "shazam"
_SHAZAM_LABEL = "Shazam-ing audio track:"


def create_from_youtube_callbacks(progress: ProgressPort) -> dict[str, object]:
    """Build the kwargs for `SongModel.create_from_youtube`.

    The returned dictionary also contains `verbose` and
    `use_default_verbosity`: without them, song.py would overwrite all the
    callbacks and print its own progress bars to stdout — a dealbreaker for
    a web server.

    Args:
        progress: the port that will receive the events.

    Returns:
        A dictionary to pass as `**kwargs`. Its keys are a subset of
        `SongModel.create_from_youtube`'s parameters.
    """

    kwargs: dict[str, object] = {
        "verbose": True,
        "use_default_verbosity": False,
    }

    for stage in (_DOWNLOAD_AUDIO, _MP3_ENCODE, _DOWNLOAD_COVER_ART):
        kwargs.update(_stage_hooks(progress, stage))

    kwargs.update(_shazam_hooks(progress))

    return kwargs


def update_cover_art_callbacks(progress: ProgressPort) -> dict[str, object]:
    """Build the kwargs for `SongModel.update_cover_art`.

    Args:
        progress: the port that will receive the events.

    Returns:
        A dictionary to pass as `**kwargs`. Its keys are a subset of
        `SongModel.update_cover_art`'s parameters.
    """

    return _stage_hooks(progress, _DOWNLOAD_COVER_ART)


def shazam_song_callbacks(progress: ProgressPort) -> dict[str, object]:
    """Build the kwargs for `SongModel.shazam_song`.

    Args:
        progress: the port that will receive the events.

    Returns:
        A dictionary to pass as `**kwargs`. Its keys are a subset of
        `SongModel.shazam_song`'s parameters.
    """

    return _shazam_hooks(progress)


def _stage_hooks(progress: ProgressPort, stage: _Stage) -> dict[str, object]:
    """Frame a measured stage: start, progress, end.

    The `pre_`/`post_` hooks receive differently shaped arguments depending
    on the stage — `(video_props, m4a_path)` for audio,
    `(video_props, m4a_path, mp3_path)` for encoding, `(song)` for the
    cover art. None of them are of use to us: only the stage's identity
    matters, hence the `*_args` that accepts them all.
    """

    async def stage_started(*_args) -> None:
        progress.stage_started(stage.stage, stage.label)

    async def stage_done(*_args) -> None:
        progress.stage_done(stage.stage)

    return {
        stage.pre: stage_started,
        stage.on: ProgressBarInterface(
            label=stage.label,
            callback=_percent_forwarder(progress, stage.stage),
        ),
        stage.post: stage_done,
    }


def _shazam_hooks(progress: ProgressPort) -> dict[str, object]:
    """Frame Shazam recognition and report its result."""

    async def pre_shazam_song(_song) -> None:
        progress.stage_started(_SHAZAM_STAGE, _SHAZAM_LABEL)

    async def post_shazam_song(song) -> None:
        # `or 0`: song.py guards itself the same way (cf. fix_filename).
        # A missing score would make the hook fail, and with it the whole
        # import.
        progress.song_identified(
            song.shazam_artist,
            song.shazam_title,
            float(song.shazam_match_score or 0),
        )
        progress.stage_done(_SHAZAM_STAGE)

    return {
        "pre_shazam_song": pre_shazam_song,
        "post_shazam_song": post_shazam_song,
    }


def _percent_forwarder(progress: ProgressPort, stage: str):
    """Adapt the `(percentage, label)` signature expected by song.py.

    The label is ignored: the port already received it via `stage_started`,
    and song.py injects the file size into it, which varies from one call
    to the next.
    """

    def forward(percentage: int, label: str = "") -> None:
        progress.stage_progress(stage, float(percentage))

    return forward
