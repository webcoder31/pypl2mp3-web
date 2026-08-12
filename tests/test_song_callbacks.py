"""Projection of the ProgressPort onto SongModel's callbacks.

Two levels of proof here: unit tests on the shape of the returned
dictionaries, and two tests that actually run
`SongModel.create_from_youtube` (without network or encoding) to verify
that the callbacks are not overwritten along the way and that nothing
reaches stdout.
"""

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from pypl2mp3.libs import song as song_module
from pypl2mp3.libs.song import (
    ProgressBarInterface,
    SongModel,
    SongModelException,
)
from pypl2mp3.services._song_callbacks import (
    create_from_youtube_callbacks,
    shazam_song_callbacks,
    update_cover_art_callbacks,
)

from tests.doubles import FakeProgress


def _fake_song(
    artist: str = "The Pharcyde",
    title: str = "Passin' Me By",
    score: float | None = 66.0,
):
    return SimpleNamespace(
        shazam_artist=artist,
        shazam_title=title,
        shazam_match_score=score,
    )


# ---------------------------------------------------------------------------
# Each builder returns only keys accepted by ITS OWN API
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "builder, api",
    [
        (create_from_youtube_callbacks, SongModel.create_from_youtube),
        (update_cover_art_callbacks, SongModel.update_cover_art),
        (shazam_song_callbacks, SongModel.shazam_song),
    ],
    ids=["create_from_youtube", "update_cover_art", "shazam_song"],
)
def test_every_returned_key_is_accepted_by_its_own_api(builder, api):
    kwargs = builder(FakeProgress())
    accepted = set(inspect.signature(api).parameters)

    assert kwargs, "an empty builder would pass this test without proving anything"
    assert set(kwargs) <= accepted

    # Direct proof: the splat would raise TypeError on an unknown key.
    inspect.signature(api).bind_partial(**kwargs)


# ---------------------------------------------------------------------------
# C1: the verbosity flags, without which song.py overwrites everything
# ---------------------------------------------------------------------------


def test_create_from_youtube_callbacks_pin_the_verbosity_flags():
    kwargs = create_from_youtube_callbacks(FakeProgress())

    assert kwargs["verbose"] is True
    assert kwargs["use_default_verbosity"] is False


class _FakeStream:
    """An audio stream reporting its own progress, without a socket."""

    filesize = 1_000_000
    filesize_mb = 1.0

    def __init__(self, video):
        self._video = video

    def download(self, output_path, filename):
        # pytubefix notifies the registered callbacks on every chunk
        # received. 5% steps: beyond a 10% gap, song.py animates the
        # transition point by point with a 10 ms pause each time.
        for bytes_remaining in (950_000, 900_000):
            for callback in self._video.progress_callbacks:
                callback(self, b"", bytes_remaining)


class _FakeYouTube:
    """Replaces `pytubefix.YouTube`: same attributes, no network call."""

    def __init__(self, url: str):
        self.url = url
        self.video_id = "FAKEVIDEO01"
        self.author = "Fake Artist"
        self.title = "Fake Title"
        self.thumbnail_url = "https://example.invalid/cover.jpg"
        self.progress_callbacks = []
        self.streams = SimpleNamespace(
            get_audio_only=lambda: _FakeStream(self)
        )

    def register_on_progress_callback(self, callback) -> None:
        self.progress_callbacks.append(callback)


def _refuse_to_encode(*args, **kwargs):
    """Stop barrier: MP3 encoding is out of scope for this test."""

    raise RuntimeError("encoding not simulated")


async def _drive_import(tmp_path, monkeypatch, **kwargs) -> None:
    """Run the real `create_from_youtube` up to the encoding step.

    The pipeline thus goes through fetching the video info, the full audio
    download, and entering the encoding step, then stops dead at the
    barrier.
    """

    monkeypatch.setattr(song_module, "YouTube", _FakeYouTube)
    monkeypatch.setattr(song_module, "AudioFileClip", _refuse_to_encode)

    with pytest.raises(SongModelException):
        await SongModel.create_from_youtube("FAKEVIDEO01", tmp_path, **kwargs)


async def test_the_port_receives_events_and_stdout_stays_empty(
    tmp_path, monkeypatch, capsys
):
    """C1: the callbacks survive the real `create_from_youtube`.

    Removing the two flags from the builder makes this test fail: song.py
    would replace the callbacks with its own closures and the port would
    see nothing come through.
    """

    progress = FakeProgress()

    await _drive_import(
        tmp_path, monkeypatch, **create_from_youtube_callbacks(progress)
    )

    assert progress.events == [
        ("stage_started", "download_audio", "Streaming audio:"),
        ("stage_progress", "download_audio", 5.0),
        ("stage_progress", "download_audio", 10.0),
        ("stage_done", "download_audio"),
        ("stage_started", "mp3_encode", "Encoding audio stream to MP3:"),
    ]
    assert capsys.readouterr().out == ""


async def test_without_the_flags_song_py_prints_and_the_port_gets_nothing(
    tmp_path, monkeypatch, capsys
):
    """Counter-proof of the previous test.

    It establishes two things: that song.py's prints are indeed visible to
    capsys (without which the silence assertion would prove nothing), and
    that it really is the flags that make the difference.
    """

    progress = FakeProgress()
    kwargs = create_from_youtube_callbacks(progress)
    del kwargs["verbose"]
    del kwargs["use_default_verbosity"]

    await _drive_import(tmp_path, monkeypatch, **kwargs)

    assert progress.events == []
    assert capsys.readouterr().out != ""


# ---------------------------------------------------------------------------
# I1: each stage announces itself, progresses, then ends
# ---------------------------------------------------------------------------


# The arguments match what song.py actually passes to the hooks: they
# differ from one stage to the next.
_STREAMING_STAGES = [
    (
        "download_audio",
        "pre_download_audio",
        "on_download_audio",
        "post_download_audio",
        (SimpleNamespace(youtube_id="FAKEVIDEO01"), Path("temp.m4a")),
    ),
    (
        "mp3_encode",
        "pre_mp3_encode",
        "on_mp3_encode",
        "post_mp3_encode",
        (
            SimpleNamespace(youtube_id="FAKEVIDEO01"),
            Path("temp.m4a"),
            Path("temp.mp3"),
        ),
    ),
    (
        "download_cover_art",
        "pre_download_cover_art",
        "on_download_cover_art",
        "post_download_cover_art",
        (_fake_song(),),
    ),
]


@pytest.mark.parametrize(
    "stage, pre, on, post, hook_args",
    _STREAMING_STAGES,
    ids=[case[0] for case in _STREAMING_STAGES],
)
async def test_each_streaming_stage_frames_itself_with_its_own_identity(
    stage, pre, on, post, hook_args
):
    """A wrong, shared, or ignored identifier makes this test fail.

    It also verifies that each hook accepts the shape of arguments that
    song.py passes it: a wrong arity would only show up in production.
    """

    progress = FakeProgress()
    kwargs = create_from_youtube_callbacks(progress)

    await kwargs[pre](*hook_args)
    kwargs[on].callback(42, label="label injected by song.py")
    await kwargs[post](*hook_args)

    assert progress.events == [
        ("stage_started", stage, kwargs[on].label),
        ("stage_progress", stage, 42.0),
        ("stage_done", stage),
    ]


def test_the_three_streaming_stages_do_not_share_an_identity():
    """Without this, a UI would not know which bar it is advancing."""

    progress = FakeProgress()
    kwargs = create_from_youtube_callbacks(progress)

    for _stage, _pre, on, _post, _args in _STREAMING_STAGES:
        kwargs[on].callback(1, label="")

    reported = [event[1] for event in progress.events]

    assert len(set(reported)) == 3, reported


def test_every_streaming_stage_carries_a_label():
    kwargs = create_from_youtube_callbacks(FakeProgress())

    for _stage, _pre, on, _post, _args in _STREAMING_STAGES:
        assert isinstance(kwargs[on], ProgressBarInterface), on
        assert kwargs[on].label, f"{on} must carry a label"


async def test_update_cover_art_callbacks_frame_the_cover_art_stage():
    progress = FakeProgress()
    kwargs = update_cover_art_callbacks(progress)
    song = _fake_song()

    await kwargs["pre_download_cover_art"](song)
    kwargs["on_download_cover_art"].callback(70, label="Downloading (12 Kb):")
    await kwargs["post_download_cover_art"](song)

    assert progress.events == [
        ("stage_started", "download_cover_art", "Downloading cover art:"),
        ("stage_progress", "download_cover_art", 70.0),
        ("stage_done", "download_cover_art"),
    ]


# ---------------------------------------------------------------------------
# Shazam: start, result, end
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "builder",
    [create_from_youtube_callbacks, shazam_song_callbacks],
    ids=["create_from_youtube", "shazam_song"],
)
async def test_shazam_hooks_frame_the_stage_and_report_the_song(builder):
    progress = FakeProgress()
    kwargs = builder(progress)

    await kwargs["pre_shazam_song"](None)
    await kwargs["post_shazam_song"](_fake_song())

    assert progress.events == [
        ("stage_started", "shazam", "Shazam-ing audio track:"),
        ("song_identified", "The Pharcyde", "Passin' Me By", 66.0),
        ("stage_done", "shazam"),
    ]


async def test_a_missing_shazam_score_does_not_sink_the_hook():
    """song.py turns any hook exception into an import failure."""

    progress = FakeProgress()
    kwargs = shazam_song_callbacks(progress)

    await kwargs["post_shazam_song"](_fake_song(score=None))

    assert ("song_identified", "The Pharcyde", "Passin' Me By", 0.0) \
        in progress.events
