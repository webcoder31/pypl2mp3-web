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
    """Report the progress of a long-running operation.

    Two levels, deliberately distinct. A *stage* is a measured phase of
    whatever is happening now — downloading, encoding — and there is only
    ever one. An *item* is one member of a batch, and it carries an
    identity, because a caller showing thirty rows has to know which row
    an event belongs to.

    Stage events are attributed to whichever item started last: the batch
    is walked one item at a time, so "now" is never ambiguous. That is
    what lets `song_identified` stay as it is — the callback that raises
    it has no idea which batch, if any, it is part of.
    """

    def stage_started(self, stage: str, label: str) -> None:
        ...

    def stage_progress(self, stage: str, percent: float) -> None:
        ...

    def stage_done(self, stage: str) -> None:
        ...

    def song_identified(self, artist: str, title: str, score: float) -> None:
        ...

    def item_started(self, item_id: str, label: str) -> None:
        ...

    def item_done(self, item_id: str) -> None:
        ...

    def item_failed(self, item_id: str, reason: str, issue: str) -> None:
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

    def item_started(self, item_id: str, label: str) -> None:
        return None

    def item_done(self, item_id: str) -> None:
        return None

    def item_failed(self, item_id: str, reason: str, issue: str) -> None:
        return None
