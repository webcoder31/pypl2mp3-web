"""The job registry tracks long operations and survives browser reconnects."""

import asyncio

import pytest

from pypl2mp3.web.jobs import (
    Job,
    JobAlreadyRunning,
    JobRegistry,
    JobState,
)


async def test_a_completed_job_reports_its_result():
    registry = JobRegistry()

    async def work(job: Job) -> str:
        return "done"

    job = registry.start("j1", work)
    await registry.wait("j1")

    assert job.state is JobState.COMPLETED
    assert job.result == "done"
    assert job.error is None


async def test_a_failing_job_records_the_error_and_does_not_raise():
    registry = JobRegistry()

    async def work(job: Job) -> None:
        raise RuntimeError("boom")

    job = registry.start("j1", work)
    await registry.wait("j1")

    assert job.state is JobState.FAILED
    assert "boom" in job.error


async def test_events_are_buffered_so_a_reconnecting_client_catches_up():
    registry = JobRegistry()

    async def work(job: Job) -> None:
        registry.emit("j1", {"kind": "progress", "percent": 50.0})

    registry.start("j1", work)
    await registry.wait("j1")

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
    await registry.wait("j1")


async def test_a_cancelled_job_is_marked_cancelled_not_failed():
    registry = JobRegistry()
    started = asyncio.Event()

    async def work(job: Job) -> None:
        started.set()
        await asyncio.sleep(10)

    job = registry.start("j1", work)
    await started.wait()

    assert registry.cancel("j1") is True
    await registry.wait("j1")

    assert job.state is JobState.CANCELLED
