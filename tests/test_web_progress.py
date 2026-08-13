"""Progress events must reach the job from a worker thread, safely."""

import asyncio

from pypl2mp3.ports.progress import ProgressPort
from pypl2mp3.web.jobs import Job, JobRegistry
from pypl2mp3.web.web_progress import WebProgress


async def wait_for(registry, job_id):
    """Await a job's completion.

    `JobRegistry` deliberately has no public `wait`: living on the registry
    would let cancelling the *waiter* forward onto the *job* (`await
    job.task` propagates a cancel to the awaited task), silently killing an
    import for every other observer just because one test coroutine was
    torn down. See `tests/test_jobs.py` for the original of this helper.
    """

    job = registry.get(job_id)
    if job is None or job.task is None:
        return
    try:
        await job.task
    except asyncio.CancelledError:
        pass


async def test_it_satisfies_the_progress_port():
    registry = JobRegistry()
    progress = WebProgress(registry, "j1", asyncio.get_running_loop())

    assert isinstance(progress, ProgressPort)


async def test_events_reach_the_job():
    registry = JobRegistry()
    loop = asyncio.get_running_loop()

    async def work(job: Job) -> None:
        progress = WebProgress(registry, "j1", loop)
        progress.stage_started("download_audio", "Streaming audio:")
        progress.stage_progress("download_audio", 42.0)
        progress.stage_done("download_audio")
        await asyncio.sleep(0)  # let the loop drain the scheduled callbacks

    registry.start("j1", work)
    await wait_for(registry, "j1")
    await asyncio.sleep(0)

    job = registry.get("j1")

    # Percentages never enter the ring: one per point, three stages per
    # song, would erase every song boundary of a long import. They update
    # `current` in place instead.
    kinds = [event["kind"] for event in job.events]
    assert kinds == ["stage_started", "stage_done"]
    assert job.current["percent"] == 42.0


async def test_events_emitted_from_a_worker_thread_reach_the_job():
    """The real caller is song.py, running inside asyncio.to_thread."""

    registry = JobRegistry()
    loop = asyncio.get_running_loop()

    async def work(job: Job) -> None:
        progress = WebProgress(registry, "j1", loop)

        def in_thread() -> None:
            progress.stage_progress("download_audio", 10.0)

        await asyncio.to_thread(in_thread)
        await asyncio.sleep(0)

    registry.start("j1", work)
    await wait_for(registry, "j1")
    await asyncio.sleep(0)

    # A percentage updates `current` rather than the ring — see above.
    assert registry.get("j1").current["percent"] == 10.0


async def test_the_port_never_blocks_its_caller():
    """song.py calls this inside download loops; blocking would throttle it."""

    registry = JobRegistry()
    progress = WebProgress(registry, "j1", asyncio.get_running_loop())

    started = asyncio.get_running_loop().time()
    for index in range(1000):
        progress.stage_progress("download_audio", float(index % 100))
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 0.5, f"1000 emissions took {elapsed:.3f}s"


async def test_song_identified_carries_the_match():
    registry = JobRegistry()
    loop = asyncio.get_running_loop()

    async def work(job: Job) -> None:
        WebProgress(registry, "j1", loop).song_identified(
            "The Pharcyde", "Passin' Me By", 66.0
        )
        await asyncio.sleep(0)

    registry.start("j1", work)
    await wait_for(registry, "j1")
    await asyncio.sleep(0)

    identified = [
        event
        for event in registry.get("j1").events
        if event["kind"] == "song_identified"
    ]
    assert identified[0]["artist"] == "The Pharcyde"
    assert identified[0]["score"] == 66.0
