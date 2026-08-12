from pypl2mp3.libs.song import ProgressBarInterface
from pypl2mp3.services._song_callbacks import song_callbacks

from tests.doubles import FakeProgress


def test_returns_progress_bar_interfaces_for_the_three_streaming_stages():
    kwargs = song_callbacks(FakeProgress())

    for key in ("on_download_audio", "on_mp3_encode", "on_download_cover_art"):
        assert isinstance(kwargs[key], ProgressBarInterface), key
        assert kwargs[key].label, f"{key} doit porter un libellé"


def test_progress_bar_callback_forwards_percent_to_the_port():
    progress = FakeProgress()
    kwargs = song_callbacks(progress)

    kwargs["on_download_audio"].callback(42, "Streaming audio:")

    assert ("stage_progress", "download_audio", 42.0) in progress.events


def test_shazam_hooks_report_the_identified_song():
    progress = FakeProgress()
    kwargs = song_callbacks(progress)

    song = type(
        "FakeSong",
        (),
        {
            "shazam_artist": "The Pharcyde",
            "shazam_title": "Passin' Me By",
            "shazam_match_score": 66.0,
        },
    )()

    kwargs["post_shazam_song"](song)

    assert (
        "song_identified",
        "The Pharcyde",
        "Passin' Me By",
        66.0,
    ) in progress.events


def test_every_returned_key_is_accepted_by_create_from_youtube():
    import inspect

    from pypl2mp3.libs.song import SongModel

    accepted = set(
        inspect.signature(SongModel.create_from_youtube).parameters
    )
    assert set(song_callbacks(FakeProgress())) <= accepted
