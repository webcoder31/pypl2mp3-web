#!/usr/bin/env python3
"""In-process registry for long-running operations.

No broker and no database: this is a single-user local tool, and the
filesystem is the source of truth. A job that dies with the server loses
nothing that a fresh sync cannot recover — already written MP3 files stay
valid.

Each job keeps a bounded ring of its recent events so a browser that
reconnects mid-import can catch up instead of starting blind.
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Optional

# A plain stdlib logger, not the `pypl2mp3.libs.logger` singleton: that
# singleton is wired for the CLI's colorized, verbosity-flag-driven console
# output (it doubles as user-facing UI, per its own module docstring), and
# no module under `ports/`, `services/` or `web/` reaches into it. Using it
# here would tie this generic infra component to CLI-specific formatting and
# make every missed event print unconditionally to the server's console.
logger = logging.getLogger(__name__)

DEFAULT_MAX_EVENTS = 500


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobAlreadyRunning(Exception):
    """A job with this identifier is already active."""


@dataclass
class Job:
    """One long-running operation and everything observers need from it."""

    job_id: str
    state: JobState = JobState.PENDING
    result: object = None
    error: Optional[str] = None
    max_events: int = DEFAULT_MAX_EVENTS
    started_at: float = field(default_factory=time.monotonic)
    finished_at: Optional[float] = None
    # Latest known state, overwritten rather than accumulated: what a UI
    # polling once a second actually needs.
    current: dict = field(default_factory=dict)
    _events: deque = field(default_factory=deque, repr=False)
    task: Optional[asyncio.Task] = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self._events = deque(maxlen=self.max_events)

    @property
    def elapsed_seconds(self) -> int:
        """Whole seconds since the job started, frozen once it ends.

        Checking a large playlist can take minutes with nothing to show
        for it, and a static "Checking…" is indistinguishable from a hung
        server. This is what makes the wait legible.
        """

        end = time.monotonic() if self.finished_at is None else self.finished_at

        return int(end - self.started_at)

    @property
    def events(self) -> list[dict]:
        return list(self._events)

    def append_event(self, event: dict) -> None:
        """Record an event, keeping the ring free of progress noise.

        A download emits one event per percentage point, three times per
        song. An import of 34 songs produced over 10,000 events against a
        500-entry ring: every song boundary from the first two thirds of
        the run had already been overwritten before anything could read
        them.

        So percentages update `current` in place and never enter the ring.
        Transitions — a song starting, a stage finishing, a song being
        identified — are the history worth keeping.
        """

        if event.get("kind") == "stage_progress":
            self.current = {**self.current, **event}
            return

        if event.get("kind") == "stage_started" and event.get("stage"):
            # A new stage supersedes the previous percentage.
            self.current = {**event, "percent": None}
        else:
            self.current = {**self.current, **event}

        self._events.append(event)


class JobRegistry:
    """Track jobs by identifier for the lifetime of the server process."""

    def __init__(self, max_events: int = DEFAULT_MAX_EVENTS):
        self._jobs: dict[str, Job] = {}
        self._max_events = max_events

    def start(
        self,
        job_id: str,
        coro_factory: Callable[[Job], Awaitable[object]],
    ) -> Job:
        """Start a job, refusing to run one identifier twice at a time.

        Raises:
            JobAlreadyRunning: if that identifier is pending or running.
        """

        existing = self._jobs.get(job_id)
        if existing is not None and existing.state in {
            JobState.PENDING,
            JobState.RUNNING,
        }:
            raise JobAlreadyRunning(job_id)

        job = Job(job_id=job_id, max_events=self._max_events)
        self._jobs[job_id] = job
        job.task = asyncio.ensure_future(self._run(job, coro_factory))

        return job

    async def _run(
        self,
        job: Job,
        coro_factory: Callable[[Job], Awaitable[object]],
    ) -> None:
        job.state = JobState.RUNNING
        try:
            job.result = await coro_factory(job)
        except asyncio.CancelledError:
            # Partial work is preserved: whatever reached disk stays valid.
            job.state = JobState.CANCELLED
            raise
        except Exception as exc:
            job.state = JobState.FAILED
            job.error = f"{type(exc).__name__}: {exc}"
        else:
            job.state = JobState.COMPLETED
        finally:
            # In a finally so the cancelled path, which re-raises, is
            # stamped too.
            job.finished_at = time.monotonic()

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def emit(self, job_id: str, event: dict) -> None:
        """Record an event. Drops it and logs a warning for an unknown job.

        Called from the progress port, possibly from a worker thread, so it
        must stay cheap and must never raise into the caller. "Never raise"
        does not mean "never signal": a mismatch between the id passed to
        `start()` and the one passed here would otherwise discard every
        event for the life of the process with nothing observable anywhere.
        """

        job = self._jobs.get(job_id)
        if job is None:
            logger.warning(
                "emit() called for unknown job id %r; event dropped: %r",
                job_id,
                event,
            )
            return

        job.append_event(event)

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.task is None or job.task.done():
            return False

        return job.task.cancel()
