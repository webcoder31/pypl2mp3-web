#!/usr/bin/env python3
"""Contract for progress reporting.

These methods are synchronous and must NEVER block: they are called from
`song.py`'s callbacks, in the middle of download loops where any wait would
degrade throughput.

The asymmetry with `InteractionPort.ask` (asynchronous) is intentional:
reporting progress waits for nothing, asking a question waits for an
answer.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class ProgressPort(Protocol):
    """Report the progress of a long-running operation."""

    def stage_started(self, stage: str, label: str) -> None:
        ...

    def stage_progress(self, stage: str, percent: float) -> None:
        ...

    def stage_done(self, stage: str) -> None:
        ...

    def song_identified(self, artist: str, title: str, score: float) -> None:
        ...


class NullProgress:
    """Displays nothing. For calls where nobody cares about progress."""

    def stage_started(self, stage: str, label: str) -> None:
        return None

    def stage_progress(self, stage: str, percent: float) -> None:
        return None

    def stage_done(self, stage: str) -> None:
        return None

    def song_identified(self, artist: str, title: str, score: float) -> None:
        return None
