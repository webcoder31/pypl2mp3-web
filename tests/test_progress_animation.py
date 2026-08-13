"""The terminal animation must stay for the CLI and go for the web.

Stepping through every intermediate percentage with a blocking
time.sleep(0.01) is what makes a terminal bar glide. Nothing watches a
terminal when the caller is a web server, and the pause costs up to a
second per stage there.
"""

import time

from pypl2mp3.libs.song import ProgressBarInterface, SongModel
from pypl2mp3.services._song_callbacks import (
    create_from_youtube_callbacks,
    update_cover_art_callbacks,
)

from tests.doubles import FakeProgress


def _bar(animate: bool):
    seen = []
    bar = SongModel.TerminalProgressBar(
        progress_callback=lambda value, label="": seen.append(value),
        label="Streaming audio:",
        animate=animate,
    )

    return bar, seen


def test_the_cli_keeps_its_animation_by_default():
    """No caller should have to ask for the behaviour it already had."""

    assert ProgressBarInterface().animate is True
    assert SongModel.TerminalProgressBar(label="x:").animate is True


def test_animating_walks_every_intermediate_value():
    bar, seen = _bar(animate=True)

    bar.update_progress_bar(40)

    assert seen == list(range(0, 41)), "the bar should glide, not jump"


def test_not_animating_reports_the_value_once():
    bar, seen = _bar(animate=False)

    bar.update_progress_bar(40)

    assert seen == [40], "without animation the bar jumps straight there"


def test_a_small_step_is_never_animated_either_way():
    """Under the 10-point threshold the animation never applied."""

    for animate in (True, False):
        bar, seen = _bar(animate=animate)
        bar.update_progress_bar(5)
        assert seen == [5]


def test_the_animation_is_what_costs_the_time():
    _, _ = _bar(animate=True)

    animated_bar, _ = _bar(animate=True)
    started = time.perf_counter()
    animated_bar.update_progress_bar(100)
    animated = time.perf_counter() - started

    plain_bar, _ = _bar(animate=False)
    started = time.perf_counter()
    plain_bar.update_progress_bar(100)
    plain = time.perf_counter() - started

    assert animated > 0.5, "100 steps at 10ms should take about a second"
    assert plain < 0.05, "without animation there is nothing to wait for"


def test_the_web_adapters_turn_the_animation_off():
    for build in (create_from_youtube_callbacks, update_cover_art_callbacks):
        kwargs = build(FakeProgress())
        bars = [
            value
            for value in kwargs.values()
            if isinstance(value, ProgressBarInterface)
        ]
        assert bars, f"{build.__name__} produced no progress bars"
        for bar in bars:
            assert bar.animate is False, build.__name__
