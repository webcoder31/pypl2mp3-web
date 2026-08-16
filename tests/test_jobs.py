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


async def test_a_cancelled_job_id_can_be_started_again():
    """A cancelled import must be retriable: this is exactly what a user
    does after cancelling a bad network run."""

    registry = JobRegistry()
    started = asyncio.Event()

    async def block(job: Job) -> None:
        started.set()
        await asyncio.sleep(10)

    async def succeed(job: Job) -> str:
        return "done"

    registry.start("j1", block)
    await started.wait()

    assert registry.cancel("j1") is True
    await wait_for(registry, "j1")
    assert registry.get("j1").state is JobState.CANCELLED

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


def _feed(job, *events):
    for event in events:
        job.append_event(event)

    return job


def test_each_song_keeps_its_own_progress():
    """`current` is overwritten from one song to the next, which is right
    for a one-line ribbon and useless for a panel showing thirty rows.
    Every row has to survive the next row starting."""

    job = _feed(
        Job(job_id="import:PL1"),
        {"kind": "item_started", "item_id": "AAA", "label": "1/2"},
        {"kind": "stage_started", "stage": "download_audio", "label": "d"},
        {"kind": "stage_progress", "stage": "download_audio", "percent": 40.0},
        {"kind": "item_done", "item_id": "AAA"},
        {"kind": "item_started", "item_id": "BBB", "label": "2/2"},
        {"kind": "stage_progress", "stage": "download_audio", "percent": 10.0},
    )

    assert list(job.items) == ["AAA", "BBB"], "the order songs were announced"
    assert job.items["AAA"]["state"] == "done"
    assert job.items["BBB"]["state"] == "running"
    assert job.items["BBB"]["percent"] == 10.0
    assert job.items["AAA"]["percent"] != 10.0, (
        "the second song's progress landed on the first song's row"
    )


def test_a_percentage_updates_the_row_without_filling_the_ring():
    """The reason percentages were kept out of the ring in the first
    place: 34 songs produced over 10,000 events against 500 slots."""

    job = _feed(
        Job(job_id="import:PL1"),
        {"kind": "item_started", "item_id": "AAA", "label": "1/1"},
        *(
            {"kind": "stage_progress", "stage": "download_audio",
             "percent": float(p)}
            for p in range(101)
        ),
    )

    assert job.items["AAA"]["percent"] == 100.0
    assert len(job.events) == 1, (
        f"{len(job.events)} events kept; the ring is being flooded again"
    )


def test_a_new_stage_starts_its_bar_at_nothing():
    """Carrying the previous stage's percentage over would open the
    encoder's bar full and then jump it backwards."""

    job = _feed(
        Job(job_id="import:PL1"),
        {"kind": "item_started", "item_id": "AAA", "label": "1/1"},
        {"kind": "stage_progress", "stage": "download_audio", "percent": 98.0},
        {"kind": "stage_started", "stage": "mp3_encode", "label": "e"},
    )

    assert job.items["AAA"]["stage"] == "mp3_encode"
    assert not job.items["AAA"]["percent"], job.items["AAA"]


def test_a_score_lands_on_the_song_it_identified():
    job = _feed(
        Job(job_id="import:PL1"),
        {"kind": "item_started", "item_id": "AAA", "label": "1/2"},
        {"kind": "item_done", "item_id": "AAA"},
        {"kind": "item_started", "item_id": "BBB", "label": "2/2"},
        {"kind": "song_identified", "artist": "IAMX", "title": "Kiss",
         "score": 88.0},
    )

    assert job.items["BBB"]["score"] == 88.0
    assert "score" not in job.items["AAA"], (
        "the second song's identification was written onto the first"
    )


def test_a_failure_is_recorded_on_its_own_row():
    job = _feed(
        Job(job_id="import:PL1"),
        {"kind": "item_started", "item_id": "AAA", "label": "1/2"},
        {"kind": "item_failed", "item_id": "AAA", "reason": "age restricted",
         "issue": "AgeRestrictedError: nope"},
        {"kind": "item_started", "item_id": "BBB", "label": "2/2"},
    )

    assert job.items["AAA"]["state"] == "failed"
    assert job.items["AAA"]["reason"] == "age restricted"
    assert job.items["BBB"]["state"] == "running", (
        "one song's failure marked the next one failed too"
    )


def test_stages_without_an_item_are_not_an_error():
    """Checking a playlist reports stages and never announces an item."""

    job = _feed(
        Job(job_id="check:PL1"),
        {"kind": "stage_started", "stage": "check", "label": "Checking"},
        {"kind": "stage_progress", "stage": "check", "percent": 100.0},
    )

    assert job.items == {}
    assert job.current["stage"] == "check"


def test_a_listed_song_is_not_a_running_one():
    """The whole reason item_listed exists.

    A panel shows thirty rows to tick before a single one is downloaded.
    Drawing them as running would promise work that has not started, and
    leave nothing to distinguish the row being fetched right now.
    """

    job = _feed(
        Job(job_id="check:PL1"),
        {"kind": "item_listed", "item_id": "AAA", "label": "IAMX - Kiss"},
        {"kind": "item_listed", "item_id": "BBB", "label": "IAMX - Spit It"},
        {"kind": "item_started", "item_id": "BBB", "label": "2/2"},
    )

    assert job.items["AAA"]["state"] == "pending", (
        "a row nobody has started reads as running, so the panel cannot "
        "show which song is actually being worked on"
    )
    assert job.items["BBB"]["state"] == "running"


def test_starting_a_song_keeps_the_name_it_was_listed_under():
    """The sweep announces a position — "2/12" — not a name. Overwriting
    the label with it emptied the row the moment work began on it."""

    job = _feed(
        Job(job_id="import:PL1"),
        {"kind": "item_listed", "item_id": "AAA", "label": "IAMX - Kiss"},
        {"kind": "item_started", "item_id": "AAA", "label": "1/12"},
    )

    assert job.items["AAA"]["label"] == "IAMX - Kiss"
    assert job.items["AAA"]["position"] == "1/12"


def test_each_stage_of_a_song_keeps_its_own_bar():
    """Four bars are shown at once. One running figure would make three
    of them lie about where they are."""

    job = _feed(
        Job(job_id="import:PL1"),
        {"kind": "item_started", "item_id": "AAA", "label": "1/1"},
        {"kind": "stage_started", "stage": "download_audio", "label": "d"},
        {"kind": "stage_progress", "stage": "download_audio", "percent": 60.0},
        {"kind": "stage_done", "stage": "download_audio"},
        {"kind": "stage_started", "stage": "mp3_encode", "label": "e"},
        {"kind": "stage_progress", "stage": "mp3_encode", "percent": 20.0},
    )

    stages = job.items["AAA"]["stages"]
    assert stages["download_audio"] == 100.0, stages
    assert stages["mp3_encode"] == 20.0, stages
    assert "download_cover_art" not in stages, (
        "a stage nobody has reached is already reporting progress"
    )


def test_a_stage_appears_the_moment_it_begins():
    """Shazam reports no percentage at all. Waiting for one before
    drawing its bar would mean never drawing it."""

    job = _feed(
        Job(job_id="import:PL1"),
        {"kind": "item_started", "item_id": "AAA", "label": "1/1"},
        {"kind": "stage_started", "stage": "shazam", "label": "s"},
    )

    assert job.items["AAA"]["stages"]["shazam"] == 0.0


def test_a_position_never_becomes_a_name():
    """"1/11" appeared where a song title belonged.

    The sweep announces a position, because until YouTube answers that is
    all it has. Falling back to it when the listing had no name dressed a
    song nobody could name as a song called "1/11" — and the row already
    has an honest way to show that case, with the id and a link.
    """

    job = _feed(
        Job(job_id="import:PL1"),
        {"kind": "item_listed", "item_id": "AAA", "label": ""},
        {"kind": "item_started", "item_id": "AAA", "label": "1/11"},
    )

    assert job.items["AAA"]["label"] == "", job.items["AAA"]
    assert job.items["AAA"]["position"] == "1/11"


def test_a_song_gets_the_name_it_turned_out_to_have():
    """YouTube would not say what the video was; Shazam recognised it,
    and that is the name now on the file. The row said "unnamed" beside
    a 100% match."""

    job = _feed(
        Job(job_id="import:PL1"),
        {"kind": "item_listed", "item_id": "AAA", "label": ""},
        {"kind": "item_started", "item_id": "AAA", "label": "3/11"},
        {"kind": "item_done", "item_id": "AAA",
         "label": "Rattlesnake Milk - Die Young"},
    )

    assert job.items["AAA"]["label"] == "Rattlesnake Milk - Die Young"


def test_a_row_that_already_reads_well_keeps_its_name():
    """The listing's name is what the reader recognised the song by. A
    second opinion on the title, arriving at the end, is not an
    improvement."""

    job = _feed(
        Job(job_id="import:PL1"),
        {"kind": "item_listed", "item_id": "AAA",
         "label": "thebeautyofgemina - RIVER (OFFICIAL LYRIC VIDEO)"},
        {"kind": "item_started", "item_id": "AAA", "label": "2/11"},
        {"kind": "item_done", "item_id": "AAA",
         "label": "The Beauty Of Gemina - River"},
    )

    assert job.items["AAA"]["label"].startswith("thebeautyofgemina")
