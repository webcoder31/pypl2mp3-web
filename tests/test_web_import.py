"""Starting an import from the browser."""

import asyncio
import re
from pathlib import Path

import httpx
import pytest

from pypl2mp3.services import import_playlist as mod
from pypl2mp3.web.app import create_app

PLAYLIST_ID = "PLP6XxNg42qDGMg1cR2PPPzwdoAOD1MQ97"
REMOTE_IDS = ["AAAAAAAAAAA", "BBBBBBBBBBB"]
HX = {"HX-Request": "true"}

_MP3_FRAME = b"\xff\xfb\x90\xc0" + b"\x00" * 413


class _FakePlaylist:
    def __init__(self, url, *args, **kwargs):
        self.title = "fake"
        self.owner = "owner"
        self.length = len(REMOTE_IDS)
        self.video_urls = [
            f"https://www.youtube.com/watch?v={vid}" for vid in REMOTE_IDS
        ]


class _FakeYouTube:
    def __init__(self, url, *args, **kwargs):
        self.video_id = url.rsplit("=", 1)[-1]
        self.author = "ARTIST"
        self.title = "Title"


class _FakeSong:
    def __init__(self, youtube_id):
        self.filename = f"ARTIST - Title [{youtube_id}].mp3"
        self.artist = "ARTIST"
        self.title = "Title"
        self.shazam_match_score = 66.0
        self.has_junk_filename = False


def _install_fakes(monkeypatch, delay: float = 0.0):
    monkeypatch.setattr(mod, "Playlist", _FakePlaylist)
    monkeypatch.setattr(mod, "YouTube", _FakeYouTube)

    async def create(youtube_id, playlist_path, threshold, **kwargs):
        if delay:
            await asyncio.sleep(delay)
        (playlist_path / f"ARTIST - Title [{youtube_id}].mp3").write_bytes(
            _MP3_FRAME * 8
        )
        return _FakeSong(youtube_id)

    monkeypatch.setattr(mod.SongModel, "create_from_youtube", create)


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _settle(client, job_id):
    for _ in range(100):
        payload = (await client.get(f"/jobs/{job_id}")).json()
        if payload["state"] not in ("pending", "running"):
            return payload
        await asyncio.sleep(0.05)

    pytest.fail(f"job {job_id} never settled")


async def test_it_imports_and_reports_what_it_did(tmp_path, monkeypatch):
    _install_fakes(monkeypatch)

    async with _client(create_app(tmp_path)) as client:
        started = await client.post(f"/playlists/{PLAYLIST_ID}/import")
        assert started.status_code == 200
        job_id = started.json()["job_id"]
        assert job_id == f"import:{PLAYLIST_ID}"

        payload = await _settle(client, job_id)

    assert payload["state"] == "completed"
    assert len(payload["result"]["imported"]) == 2
    assert payload["result"]["failed"] == []

    written = list((tmp_path / f"owner - fake [{PLAYLIST_ID}]").glob("*.mp3"))
    assert len(written) == 2, "the songs should actually be on disk"


async def test_progress_events_name_the_song_being_imported(
    tmp_path, monkeypatch
):
    _install_fakes(monkeypatch)

    async with _client(create_app(tmp_path)) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/import")
        payload = await _settle(client, f"import:{PLAYLIST_ID}")

    labels = [
        event.get("label")
        for event in payload["events"]
        if event["kind"] == "stage_started" and event.get("stage") == "song"
    ]
    assert "1/2 ARTIST - Title" in labels
    assert "2/2 ARTIST - Title" in labels


async def test_check_and_import_do_not_share_an_element_id(
    tmp_path, monkeypatch
):
    """Both target the same playlist; one DOM node cannot serve both.

    The ribbon keys its entries by that id and drops duplicates, so a
    collision here would have a started import evict a running check —
    or be silently swallowed by it.
    """

    _install_fakes(monkeypatch)
    monkeypatch.setattr(
        "pypl2mp3.services.check_new_songs.Playlist", _FakePlaylist
    )

    folder = tmp_path / f"owner - fake [{PLAYLIST_ID}]"
    folder.mkdir(parents=True)
    (folder / "ARTIST - Title [AAAAAAAAAAA].mp3").write_bytes(_MP3_FRAME * 8)

    app = create_app(tmp_path)

    async with _client(app) as client:
        check = (
            await client.post(f"/playlists/{PLAYLIST_ID}/check", headers=HX)
        ).text
        importing = (
            await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
        ).text

    check_id = re.search(r'<div id="([^"]+)"', check).group(1)
    import_id = re.search(r'<div id="([^"]+)"', importing).group(1)

    assert check_id != import_id, "the two job kinds collided on one id"


async def test_a_second_import_of_the_same_playlist_is_refused(
    tmp_path, monkeypatch
):
    _install_fakes(monkeypatch, delay=2.0)
    app = create_app(tmp_path)

    async with _client(app) as client:
        assert (
            await client.post(f"/playlists/{PLAYLIST_ID}/import")
        ).status_code == 200
        await asyncio.sleep(0.1)

        second = await client.post(f"/playlists/{PLAYLIST_ID}/import")
        assert second.status_code == 409

        app.state.jobs.cancel(f"import:{PLAYLIST_ID}")


async def test_progress_noise_does_not_evict_the_song_boundaries(
    tmp_path, monkeypatch
):
    """Regression: a real import overflowed the ring and lost its history.

    Each song emits one event per percentage point across three stages.
    Thirty-four songs produced over 10,000 events against a 500-entry
    ring, so every boundary from the first two thirds of the run was
    already overwritten by the time anything read them.
    """

    from pypl2mp3.web.jobs import Job

    job = Job(job_id="import:x", max_events=500)

    for song in range(1, 35):
        job.append_event(
            {"kind": "stage_started", "stage": "song", "label": f"{song}/34"}
        )
        for stage in ("download_audio", "mp3_encode", "download_cover_art"):
            job.append_event(
                {"kind": "stage_started", "stage": stage, "label": stage}
            )
            for percent in range(101):
                job.append_event(
                    {
                        "kind": "stage_progress",
                        "stage": stage,
                        "percent": float(percent),
                    }
                )
            job.append_event({"kind": "stage_done", "stage": stage})

    labels = [
        event["label"]
        for event in job.events
        if event["kind"] == "stage_started" and event["stage"] == "song"
    ]
    assert "1/34" in labels, "the first song was evicted from the ring"
    assert "34/34" in labels
    assert len(labels) == 34

    assert job.current["percent"] == 100.0
    assert not any(
        event["kind"] == "stage_progress" for event in job.events
    ), "percentages must not enter the ring"


async def test_the_fragment_names_the_song_instead_of_saying_checking(
    tmp_path, monkeypatch
):
    """An import that said "Checking…" for five minutes read as a hang."""

    _install_fakes(monkeypatch, delay=1.0)
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/import", headers=HX)
        await asyncio.sleep(0.3)
        fragment = (
            await client.get(f"/jobs/import:{PLAYLIST_ID}", headers=HX)
        ).text

        app.state.jobs.cancel(f"import:{PLAYLIST_ID}")

    assert "Checking" not in fragment, "that label belongs to the check job"
    assert "ARTIST - Title" in fragment, "the current song should be named"


async def test_the_song_name_survives_its_own_sub_stages():
    """Regression: the display named the stage but not the song.

    "Streaming audio: 42%" tells you nothing about which of 34 songs is
    downloading. The sub-stage used to overwrite the item name wholesale.
    """

    from pypl2mp3.web.jobs import Job

    job = Job(job_id="import:x")

    job.append_event(
        {"kind": "stage_started", "stage": "song", "label": "7/34 WU-TANG"}
    )
    job.append_event(
        {
            "kind": "stage_started",
            "stage": "download_audio",
            "label": "Streaming audio:",
        }
    )
    job.append_event(
        {"kind": "stage_progress", "stage": "download_audio", "percent": 42.0}
    )

    assert job.current["item"] == "7/34 WU-TANG", "the song name was lost"
    assert job.current["label"] == "Streaming audio:"
    assert job.current["percent"] == 42.0


async def test_a_new_song_clears_the_previous_one_s_stage():
    """Otherwise song 8 would open still showing song 7's last percentage."""

    from pypl2mp3.web.jobs import Job

    job = Job(job_id="import:x")
    job.append_event(
        {"kind": "stage_started", "stage": "song", "label": "7/34 WU-TANG"}
    )
    job.append_event(
        {"kind": "stage_started", "stage": "mp3_encode", "label": "Encoding:"}
    )
    job.append_event(
        {"kind": "stage_progress", "stage": "mp3_encode", "percent": 99.0}
    )

    job.append_event(
        {"kind": "stage_started", "stage": "song", "label": "8/34 PHARCYDE"}
    )

    assert job.current["item"] == "8/34 PHARCYDE"
    assert job.current["label"] is None
    assert job.current["percent"] is None


async def test_the_report_lists_every_song_and_why_it_failed(
    tmp_path, monkeypatch
):
    """Counts fit inline; knowing which songs and why is the point of a
    report you read after an import you could not watch."""

    from pytubefix.exceptions import AgeRestrictedError

    async def mixed(youtube_id, playlist_path, threshold, **kwargs):
        if youtube_id == "AAAAAAAAAAA":
            wrapper = RuntimeError("Failed to fetch information")
            wrapper.__cause__ = AgeRestrictedError(youtube_id)
            raise wrapper
        (playlist_path / f"ARTIST - Title [{youtube_id}].mp3").write_bytes(
            _MP3_FRAME * 8
        )
        return _FakeSong(youtube_id)

    _install_fakes(monkeypatch)
    monkeypatch.setattr(mod.SongModel, "create_from_youtube", mixed)
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/import")
        await _settle(client, f"import:{PLAYLIST_ID}")

        report = await client.get(f"/jobs/import:{PLAYLIST_ID}/report")

    assert report.status_code == 200
    body = report.text

    # The song that made it, named rather than counted.
    assert "BBBBBBBBBBB" in body or "ARTIST - Title" in body
    # The one that did not, with a reason a human can act on — asserted
    # inside its own row, not merely somewhere on the page: the summary
    # paragraph names the reasons too, so a bare substring check passes
    # even when the per-song column is empty.
    import re as _re

    row = _re.search(
        r"<li>(?:(?!</li>).)*AAAAAAAAAAA(?:(?!</li>).)*</li>",
        body,
        _re.DOTALL,
    )
    assert row, "the failed song has no entry of its own"

    # The reason element itself, not the entry: the detail beside it
    # repeats the raw exception text, which contains the same words, so
    # an entry-wide substring check passes even with the reason emptied.
    cell = _re.search(r'<span class="job-error">([^<]*)</span>', row.group(0))
    assert cell, "the entry gives no reason"
    assert cell.group(1).strip() == "age restricted", (
        f"the reason says {cell.group(1)!r}"
    )


async def test_the_completed_fragment_links_to_the_report(
    tmp_path, monkeypatch
):
    _install_fakes(monkeypatch)
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/import")
        await _settle(client, f"import:{PLAYLIST_ID}")

        fragment = (
            await client.get(f"/jobs/import:{PLAYLIST_ID}", headers=HX)
        ).text

    assert f"/jobs/import:{PLAYLIST_ID}/report" in fragment


async def test_an_unmatched_import_is_offered_the_fix_screen(
    tmp_path, monkeypatch
):
    """A song can arrive on disk and still be junk; the report should say so."""

    class _JunkSong(_FakeSong):
        def __init__(self, youtube_id):
            super().__init__(youtube_id)
            self.shazam_match_score = None
            self.has_junk_filename = True

    async def unmatched(youtube_id, playlist_path, threshold, **kwargs):
        (playlist_path / f"ARTIST - Title [{youtube_id}].mp3").write_bytes(
            _MP3_FRAME * 8
        )
        return _JunkSong(youtube_id)

    _install_fakes(monkeypatch)
    monkeypatch.setattr(mod.SongModel, "create_from_youtube", unmatched)
    app = create_app(tmp_path)

    async with _client(app) as client:
        await client.post(f"/playlists/{PLAYLIST_ID}/import")
        await _settle(client, f"import:{PLAYLIST_ID}")
        body = (await client.get(f"/jobs/import:{PLAYLIST_ID}/report")).text

    assert "/fragments/inspector/AAAAAAAAAAA" in body


async def test_an_unknown_job_report_is_a_404(tmp_path):
    async with _client(create_app(tmp_path)) as client:
        assert (await client.get("/jobs/nope/report")).status_code == 404


def _client_for(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _finished_job(app, job_id, result, fail=False):
    """Run a job to a terminal state and return once it is there."""

    async def work(job):
        if fail:
            raise RuntimeError("half way through")

        return result

    app.state.jobs.start(job_id, work)
    for _ in range(100):
        state = app.state.jobs.get(job_id).state.value
        if state not in ("pending", "running"):
            return state
        await asyncio.sleep(0.01)

    raise AssertionError("the job never finished")


async def test_a_finished_import_tells_the_page_the_repository_changed(
    tmp_path,
):
    """The songs landed on disk and the listing kept showing what it had.

    #list and #nav refetch on songsChanged, and nothing but a save was
    ever firing it — so an import wrote the files and the page had no
    way of knowing.
    """

    app = create_app(tmp_path)
    await _finished_job(
        app,
        f"import:{PLAYLIST_ID}",
        {"imported": [{"youtube_id": "AAAAAAAAAAA"}], "failed": []},
    )

    async with _client_for(app) as client:
        response = await client.get(f"/jobs/import:{PLAYLIST_ID}", headers=HX)

    assert response.headers.get("HX-Trigger") == "songsChanged", (
        "the import finished and the page was never told"
    )


async def test_an_import_still_running_does_not(tmp_path):
    """The fragment polls every second. Firing on each poll would refetch
    the listing and the nav once a second for the whole import."""

    app = create_app(tmp_path)
    started = asyncio.Event()
    release = asyncio.Event()

    async def work(job):
        started.set()
        await release.wait()

        return {"imported": [], "failed": []}

    app.state.jobs.start(f"import:{PLAYLIST_ID}", work)
    await started.wait()

    try:
        async with _client_for(app) as client:
            response = await client.get(
                f"/jobs/import:{PLAYLIST_ID}", headers=HX
            )
        assert "HX-Trigger" not in response.headers, response.headers
    finally:
        release.set()


async def test_checking_for_new_songs_does_not(tmp_path):
    """Checking reads YouTube and writes nothing. A refetch of 928 rows
    would be pure waste."""

    app = create_app(tmp_path)
    await _finished_job(
        app, f"check:{PLAYLIST_ID}", {"missing": [{"youtube_id": "A" * 11}]}
    )

    async with _client_for(app) as client:
        response = await client.get(f"/jobs/check:{PLAYLIST_ID}", headers=HX)

    assert "HX-Trigger" not in response.headers, response.headers


async def test_an_import_that_brought_nothing_back_does_not(tmp_path):
    """"Up to date" is the common case, and it changed no file."""

    app = create_app(tmp_path)
    await _finished_job(
        app, f"import:{PLAYLIST_ID}", {"imported": [], "failed": []}
    )

    async with _client_for(app) as client:
        response = await client.get(f"/jobs/import:{PLAYLIST_ID}", headers=HX)

    assert "HX-Trigger" not in response.headers, response.headers


async def test_an_import_that_broke_part_way_still_does(tmp_path):
    """It carries no report, so what it wrote before stopping is unknown.
    One wasted refetch beats songs sitting on disk that the page denies
    exist."""

    app = create_app(tmp_path)
    state = await _finished_job(app, f"import:{PLAYLIST_ID}", None, fail=True)
    assert state == "failed", state

    async with _client_for(app) as client:
        response = await client.get(f"/jobs/import:{PLAYLIST_ID}", headers=HX)

    assert response.headers.get("HX-Trigger") == "songsChanged"
