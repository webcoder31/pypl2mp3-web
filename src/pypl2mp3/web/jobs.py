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

# Stage name a producer uses to announce which item it is working on. The
# sub-stages that follow belong to it, and its name must outlive them in
# `Job.current` — see append_event.
ITEM_STAGE = "song"


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
    # One entry per member of a batch, in the order they were announced.
    # `current` says what is happening now and forgets what came before;
    # a panel showing thirty songs at once needs all thirty to persist,
    # each with its own stage, percentage, score and error.
    items: dict = field(default_factory=dict)
    # Which item stage events belong to. The batch is walked one item at
    # a time, so "now" is never ambiguous — and that is what lets the
    # stage callbacks stay ignorant of the batch they are part of.
    in_flight: Optional[str] = None
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

        kind = event.get("kind")

        if kind == "item_listed":
            # Known to be part of the batch, nothing done to it yet. The
            # row exists so it can be ticked; it is not running, and
            # drawing it as running would promise work that has not
            # started.
            self.items[event["item_id"]] = {
                "item_id": event["item_id"],
                "label": event.get("label", ""),
                "state": "pending",
                "stage": None,
                "percent": None,
            }
            self._events.append(event)
            return

        if kind == "item_started":
            known = self.items.get(event["item_id"], {})
            self.items[event["item_id"]] = {
                "item_id": event["item_id"],
                # Whatever the listing called it, and nothing else. The
                # label the sweep passes is a position — "3/12" — so
                # falling back to it dressed a song nobody could name as
                # a song called "3/12". A name we do not have is better
                # left absent: the row says so, and shows the id and a
                # link to the video instead.
                "label": known.get("label", ""),
                "position": event.get("label", ""),
                "state": "running",
                "stage": None,
                "percent": None,
            }
            self.in_flight = event["item_id"]
            self._events.append(event)
            return

        if kind in ("item_done", "item_failed"):
            item = self.items.setdefault(
                event["item_id"], {"item_id": event["item_id"], "label": ""}
            )
            item.update(
                {
                    "state": "done" if kind == "item_done" else "failed",
                    "stage": None,
                    "percent": None,
                    "reason": event.get("reason"),
                    "issue": event.get("issue"),
                }
            )
            if self.in_flight == event["item_id"]:
                self.in_flight = None
            self._events.append(event)
            return

        if kind == "stage_progress":
            self.current = {**self.current, "percent": event.get("percent")}
            self._touch_item(percent=event.get("percent"))
            self._stage_percent(event.get("stage"), event.get("percent"))
            return

        if event.get("kind") == "stage_started":
            if event.get("stage") == ITEM_STAGE:
                # A new item: keep its name for the whole of its work, and
                # clear whatever the previous item's last stage left behind.
                self.current = {
                    "item": event.get("label"),
                    "stage": None,
                    "label": None,
                    "percent": None,
                }
            else:
                # A sub-stage of the current item. It replaces the previous
                # sub-stage and its percentage, but must not erase the item
                # name — doing so left the display showing "Streaming
                # audio: 42%" with no clue which song that was.
                self.current = {
                    **self.current,
                    "stage": event.get("stage"),
                    "label": event.get("label"),
                    "percent": None,
                }
                # A new stage starts at nothing, not at the last stage's
                # percentage: the bar would otherwise open full.
                self._touch_item(
                    stage=event.get("stage"),
                    stage_label=event.get("label"),
                    percent=None,
                )
                # Zero rather than absent: the bar has to appear the
                # moment the stage begins, or a stage with no measured
                # progress — Shazam — would never show at all.
                self._stage_percent(event.get("stage"), 0.0)
        elif kind == "stage_done":
            self.current = {**self.current, **event}
            self._touch_item(percent=100.0)
            self._stage_percent(event.get("stage"), 100.0)
        elif kind == "song_identified":
            self.current = {**self.current, **event}
            self._touch_item(
                artist=event.get("artist"),
                title=event.get("title"),
                score=event.get("score"),
            )
        else:
            self.current = {**self.current, **event}

        self._events.append(event)

    def _stage_percent(self, stage: str, percent) -> None:
        """Remember how far one stage of the song in flight has got.

        Per stage rather than one running figure: a song has four of
        them, they are shown together, and a single number would make
        three of the four bars lie about where they are.
        """

        item = self.items.get(self.in_flight)
        if item is None:
            return

        item.setdefault("stages", {})[stage] = percent

    def _touch_item(self, **changes) -> None:
        """Apply a stage event to whichever item is in flight.

        Nothing in flight is not an error: `check` reports stages without
        ever announcing an item, and a stage that arrives between two
        songs belongs to neither.
        """

        item = self.items.get(self.in_flight)
        if item is None:
            return

        item.update(changes)


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
