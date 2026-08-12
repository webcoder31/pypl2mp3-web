"""Comparing local against remote: the first genuinely long web job."""

from pathlib import Path

import pytest

from pypl2mp3.services import check_new_songs as mod
from pypl2mp3.services.check_new_songs import NewSongsReport, check_new_songs

from tests.doubles import FakeProgress

PLAYLIST_ID = "PLP6XxNg42qDGMg1cR2PPPzwdoAOD1MQ97"
REMOTE_IDS = ["AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"]


class _FakePlaylist:
    def __init__(self, url, *args, **kwargs):
        self.title = "fake"
        self.owner = "owner"
        self.length = len(REMOTE_IDS)
        self.video_urls = [
            f"https://www.youtube.com/watch?v={vid}" for vid in REMOTE_IDS
        ]


def _make_local(repo: Path, present: list[str]) -> None:
    folder = repo / f"owner - fake [{PLAYLIST_ID}]"
    folder.mkdir(parents=True)
    for vid in present:
        (folder / f"ARTIST - Title [{vid}].mp3").touch()


def test_reports_only_the_missing_videos(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "Playlist", _FakePlaylist)
    _make_local(tmp_path, ["AAAAAAAAAAA"])

    report = check_new_songs(tmp_path, PLAYLIST_ID, FakeProgress())

    assert isinstance(report, NewSongsReport)
    assert report.total_remote == 3
    assert report.already_local == 1
    assert sorted(report.missing) == ["BBBBBBBBBBB", "CCCCCCCCCCC"]


def test_reports_nothing_missing_when_local_is_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "Playlist", _FakePlaylist)
    _make_local(tmp_path, REMOTE_IDS)

    report = check_new_songs(tmp_path, PLAYLIST_ID, FakeProgress())

    assert report.missing == []


def test_it_reports_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "Playlist", _FakePlaylist)
    _make_local(tmp_path, [])
    progress = FakeProgress()

    check_new_songs(tmp_path, PLAYLIST_ID, progress)

    kinds = [event[0] for event in progress.events]
    assert "stage_started" in kinds
    assert "stage_done" in kinds


def test_a_remote_failure_surfaces_rather_than_reporting_zero(
    tmp_path, monkeypatch
):
    """Reporting "nothing new" after a network failure would be a lie."""

    class _Failing:
        def __init__(self, url, *args, **kwargs):
            raise RuntimeError("network down")

    monkeypatch.setattr(mod, "Playlist", _Failing)
    _make_local(tmp_path, [])

    with pytest.raises(Exception):
        check_new_songs(tmp_path, PLAYLIST_ID, FakeProgress())


class _FailingOnAttributeAccess:
    """pytubefix fetches lazily: the constructor is silent, reads fail.

    A guard placed only around `Playlist(url)` protects nothing, because
    the constructor does no I/O. The real request fires on the first
    attribute read (`.video_urls`, `.owner`, `.title`), so that is where a
    real network failure actually surfaces.
    """

    def __init__(self, url, *args, **kwargs):
        pass

    @property
    def video_urls(self):
        raise RuntimeError("network down")

    @property
    def owner(self):
        raise RuntimeError("network down")

    @property
    def title(self):
        raise RuntimeError("network down")


def test_a_failure_on_attribute_access_surfaces_too(tmp_path, monkeypatch):
    """The constructor can succeed while every attribute read still fails.

    This is the failure mode a bare `try/except` around the constructor
    would miss entirely: nothing raises until `.video_urls` (or `.owner`,
    or `.title`) is read one line later. Silently catching that and
    returning an empty report would report "nothing new" after a real
    network failure — exactly the lie the other failure test guards
    against, but from the other entry point.
    """

    monkeypatch.setattr(mod, "Playlist", _FailingOnAttributeAccess)
    _make_local(tmp_path, [])

    with pytest.raises(Exception):
        check_new_songs(tmp_path, PLAYLIST_ID, FakeProgress())


async def test_the_route_starts_a_job_and_exposes_its_status(
    tmp_path, monkeypatch
):
    import httpx

    from pypl2mp3.web.app import create_app

    monkeypatch.setattr(mod, "Playlist", _FakePlaylist)
    _make_local(tmp_path, [])
    app = create_app(tmp_path)

    # An ASYNC client, deliberately: the route schedules a background task on
    # the running loop. A sync httpx.Client drives the app through a
    # short-lived portal loop, so the task would be orphaned between the two
    # requests and the status read would be meaningless.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        started = await client.post(f"/playlists/{PLAYLIST_ID}/check")
        assert started.status_code == 200
        job_id = started.json()["job_id"]
        assert job_id == f"check:{PLAYLIST_ID}"

        status = await client.get(f"/jobs/{job_id}")
        assert status.status_code == 200
        assert status.json()["state"] in {"pending", "running", "completed"}

        assert (await client.get("/jobs/nope")).status_code == 404


async def test_the_route_carries_progress_events_through_to_the_job_status(
    tmp_path, monkeypatch
):
    """A progress event emitted by the service must be readable over HTTP.

    `WebProgress` is built with the job's own id, and the job is started
    with `f"check:{playlist_id}"`. If those two ever drifted apart,
    `JobRegistry.emit` would silently drop every event for an unknown job
    id, and a test that only checks the job's *state* would never notice —
    `events` would just stay empty forever. This test reads `events` back
    over HTTP to make sure that link actually holds.
    """

    import asyncio

    import httpx

    from pypl2mp3.web.app import create_app

    monkeypatch.setattr(mod, "Playlist", _FakePlaylist)
    _make_local(tmp_path, [])
    app = create_app(tmp_path)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        started = await client.post(f"/playlists/{PLAYLIST_ID}/check")
        assert started.status_code == 200
        job_id = started.json()["job_id"]

        # The job runs through asyncio.to_thread, so it settles on its own
        # schedule. Poll with a bound instead of a fixed sleep, and fail
        # loudly rather than hang if it never settles.
        status = None
        for _ in range(50):
            status = (await client.get(f"/jobs/{job_id}")).json()
            if status["state"] not in {"pending", "running"}:
                break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("job did not settle within the polling budget")

        assert status["state"] == "completed", status
        kinds = [event["kind"] for event in status["events"]]
        assert "stage_started" in kinds
        assert "stage_done" in kinds


async def test_a_second_check_on_the_same_playlist_is_refused(
    tmp_path, monkeypatch
):
    """Two checks on one playlist would duplicate the network work."""

    import asyncio

    import httpx

    from pypl2mp3.web.app import create_app

    # A playlist that never finishes, so the first job is still running when
    # the second request arrives. Without this the race is unwinnable.
    class _SlowPlaylist(_FakePlaylist):
        def __init__(self, url, *args, **kwargs):
            super().__init__(url, *args, **kwargs)
            import time

            time.sleep(2)

    monkeypatch.setattr(mod, "Playlist", _SlowPlaylist)
    _make_local(tmp_path, [])
    app = create_app(tmp_path)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        assert (
            await client.post(f"/playlists/{PLAYLIST_ID}/check")
        ).status_code == 200

        # Let the job reach RUNNING before asking again.
        await asyncio.sleep(0.1)

        second = await client.post(f"/playlists/{PLAYLIST_ID}/check")
        assert second.status_code == 409

        app.state.jobs.cancel(f"check:{PLAYLIST_ID}")
