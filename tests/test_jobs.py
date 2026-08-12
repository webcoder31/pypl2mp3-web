"""The job registry tracks long operations and survives browser reconnects."""

import asyncio
import logging

import pytest

from pypl2mp3.web.jobs import (
    Job,
    JobAlreadyRunning,
    JobRegistry,
    JobState,
)


async def wait_for(registry, job_id):
    """Await a job's completion. Test-only: deliberately swallows
    CancelledError, which is why it must not live on the registry.

    Living on the registry would let cancelling the *waiter* forward onto
    the *job* (`await job.task` propagates a cancel to the awaited task),
    silently killing an import for every other observer just because one
    browser tab disconnected.
    """

    job = registry.get(job_id)
    if job is None or job.task is None:
        return
    try:
        await job.task
    except asyncio.CancelledError:
        pass


async def test_a_completed_job_reports_its_result():
    registry = JobRegistry()

    async def work(job: Job) -> str:
        return "done"

    job = registry.start("j1", work)
    await wait_for(registry, "j1")

    assert job.state is JobState.COMPLETED
    assert job.result == "done"
    assert job.error is None


async def test_a_failing_job_records_the_error_and_does_not_raise():
    registry = JobRegistry()

    async def work(job: Job) -> None:
        raise RuntimeError("boom")

    job = registry.start("j1", work)
    await wait_for(registry, "j1")

    assert job.state is JobState.FAILED
    assert "boom" in job.error


async def test_events_are_buffered_so_a_reconnecting_client_catches_up():
    registry = JobRegistry()

    async def work(job: Job) -> None:
        registry.emit("j1", {"kind": "progress", "percent": 50.0})

    registry.start("j1", work)
    await wait_for(registry, "j1")

    kinds = [event["kind"] for event in registry.get("j1").events]
    assert "progress" in kinds


def test_the_event_buffer_is_bounded():
    """An hours-long import must not grow the buffer without limit."""

    registry = JobRegistry(max_events=10)
    job = Job(job_id="j1", max_events=10)
    registry._jobs["j1"] = job

    for index in range(50):
        registry.emit("j1", {"kind": "progress", "n": index})

    assert len(job.events) == 10
    assert job.events[-1]["n"] == 49


async def test_starting_the_same_job_twice_is_refused():
    """Two concurrent imports of one playlist would download everything twice."""

    registry = JobRegistry()
    started = asyncio.Event()

    async def work(job: Job) -> None:
        started.set()
        await asyncio.sleep(1)

    registry.start("j1", work)
    await started.wait()

    with pytest.raises(JobAlreadyRunning):
        registry.start("j1", work)

    registry.cancel("j1")
    await wait_for(registry, "j1")


async def test_a_completed_job_id_can_be_started_again():
    """A finished job frees its id: retrying a completed import stays possible."""

    registry = JobRegistry()

    async def succeed(job: Job) -> str:
        return "done"

    registry.start("j1", succeed)
    await wait_for(registry, "j1")
    assert registry.get("j1").state is JobState.COMPLETED

    second = registry.start("j1", succeed)
    await wait_for(registry, "j1")

    assert second.state is JobState.COMPLETED


async def test_a_failed_job_id_can_be_started_again():
    """A failed import must be retriable, not permanently stuck on its id."""

    registry = JobRegistry()

    async def fail(job: Job) -> None:
        raise RuntimeError("boom")

    async def succeed(job: Job) -> str:
        return "done"

    registry.start("j1", fail)
    await wait_for(registry, "j1")
    assert registry.get("j1").state is JobState.FAILED

    second = registry.start("j1", succeed)
    await wait_for(registry, "j1")

    assert second.state is JobState.COMPLETED


async def test_a_cancelled_job_is_marked_cancelled_not_failed():
    registry = JobRegistry()
    started = asyncio.Event()

    async def work(job: Job) -> None:
        started.set()
        await asyncio.sleep(10)

    job = registry.start("j1", work)
    await started.wait()

    assert registry.cancel("j1") is True
    await wait_for(registry, "j1")

    assert job.state is JobState.CANCELLED
    assert job.task.cancelled(), (
        "CancelledError must propagate, or asyncio never learns the task "
        "was cancelled"
    )


def test_emit_warns_and_drops_the_event_for_an_unknown_job_id(caplog):
    """A job-id mismatch between start() and emit() must be observable,
    not a silent, permanent black hole for every subsequent event."""

    registry = JobRegistry()

    with caplog.at_level(logging.WARNING, logger="pypl2mp3.web.jobs"):
        registry.emit("no-such-job", {"kind": "progress"})

    assert registry.get("no-such-job") is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("no-such-job" in record.getMessage() for record in warnings)
