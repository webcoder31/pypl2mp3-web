#!/usr/bin/env python3
"""ProgressPort implementation that feeds a job's event buffer.

Two constraints shape this file.

First, the port's methods are synchronous and must never block: song.py
calls them from inside download loops, where waiting would throttle the
transfer.

Second, downloads run inside asyncio.to_thread, because song.py sleeps
synchronously in its own progress path (update_progress_bar animates any
jump over ten points with time.sleep(0.01) per point). So these methods are
called from a worker thread and must hand events back to the event loop
with call_soon_threadsafe rather than touching loop state directly.
"""

import asyncio

from pypl2mp3.web.jobs import JobRegistry


class WebProgress:
    """Turn progress callbacks into job events, safely across threads."""

    def __init__(
        self,
        registry: JobRegistry,
        job_id: str,
        loop: asyncio.AbstractEventLoop,
    ):
        self._registry = registry
        self._job_id = job_id
        self._loop = loop

    def _emit(self, event: dict) -> None:
        """Schedule the event on the loop. Returns immediately."""

        self._loop.call_soon_threadsafe(
            self._registry.emit, self._job_id, event
        )

    def stage_started(self, stage: str, label: str) -> None:
        self._emit({"kind": "stage_started", "stage": stage, "label": label})

    def stage_progress(self, stage: str, percent: float) -> None:
        self._emit(
            {"kind": "stage_progress", "stage": stage, "percent": percent}
        )

    def stage_done(self, stage: str) -> None:
        self._emit({"kind": "stage_done", "stage": stage})

    def item_listed(self, item_id: str, label: str) -> None:
        self._emit(
            {"kind": "item_listed", "item_id": item_id, "label": label}
        )

    def item_started(self, item_id: str, label: str) -> None:
        self._emit(
            {"kind": "item_started", "item_id": item_id, "label": label}
        )

    def item_done(self, item_id: str) -> None:
        self._emit({"kind": "item_done", "item_id": item_id})

    def item_failed(self, item_id: str, reason: str, issue: str) -> None:
        self._emit(
            {
                "kind": "item_failed",
                "item_id": item_id,
                "reason": reason,
                "issue": issue,
            }
        )

    def song_identified(
        self, artist: str, title: str, score: float
    ) -> None:
        self._emit(
            {
                "kind": "song_identified",
                "artist": artist,
                "title": title,
                "score": score,
            }
        )
