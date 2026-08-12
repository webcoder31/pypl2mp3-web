from pypl2mp3.ports.progress import NullProgress, ProgressPort

from tests.doubles import FakeProgress


def test_null_progress_accepts_every_call_and_returns_none():
    port = NullProgress()

    assert port.stage_started("download", "Streaming audio:") is None
    assert port.stage_progress("download", 42.0) is None
    assert port.stage_done("download") is None
    assert port.song_identified("The Pharcyde", "Passin' Me By", 66.0) is None


def test_fake_progress_records_events_in_order():
    port = FakeProgress()

    port.stage_started("download", "Streaming audio:")
    port.stage_progress("download", 50.0)
    port.stage_done("download")

    assert port.events == [
        ("stage_started", "download", "Streaming audio:"),
        ("stage_progress", "download", 50.0),
        ("stage_done", "download"),
    ]


def test_implementations_satisfy_the_protocol():
    assert isinstance(NullProgress(), ProgressPort)
    assert isinstance(FakeProgress(), ProgressPort)
