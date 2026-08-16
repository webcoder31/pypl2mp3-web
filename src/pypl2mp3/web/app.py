#!/usr/bin/env python3
"""FastAPI application serving the local web interface.

The server binds the loopback interface only. This is a single-user local
tool: it must never become reachable from the network because someone
passed the wrong flag.
"""

import asyncio
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pypl2mp3.libs.song import SongModel
from pypl2mp3.libs.waveform import WaveformError, peaks_for
from pypl2mp3.services._song_callbacks import IMPORT_STAGES
from pypl2mp3.services.check_new_songs import check_new_songs
from pypl2mp3.services.list_artists import list_artists
from pypl2mp3.services.list_playlists import list_playlists
from pypl2mp3.services.find_song import SongNotFound, find_song_file
from pypl2mp3.services.fix_junks import apply_fix, propose_fix
from pypl2mp3.services.import_playlist import import_playlist
from pypl2mp3.services.junkize_songs import junkize_song
from pypl2mp3.services.list_songs import (
    DEFAULT_MATCH_THRESHOLD,
    list_songs,
    summarize,
)
from pypl2mp3.web.jobs import JobAlreadyRunning, JobRegistry
from pypl2mp3.web.web_progress import WebProgress

# Arbitrary, memorable, unlikely to collide with a dev server.
DEFAULT_PORT = 8731


def create_app(repository_path: Path) -> FastAPI:
    """Build the application for a given playlist repository.

    Args:
        repository_path: folder where playlists are stored.

    Returns:
        A configured FastAPI application.
    """

    app = FastAPI(title="PYPL2MP3", docs_url=None, redoc_url=None)
    app.state.repository_path = Path(repository_path)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "repository": str(app.state.repository_path),
        }

    package_root = Path(__file__).parent

    class RevalidatingStatics(StaticFiles):
        """Static files the browser must always check before reusing.

        Starlette sends an ETag and a Last-Modified but no Cache-Control,
        which leaves the browser to guess how long a file stays fresh.
        Chrome guesses a tenth of the file's age — so a stylesheet last
        touched ten hours ago is held for an hour without asking, and an
        edit simply does not arrive. That cost a whole round of chasing a
        bug that had already been fixed.

        `no-cache` does not mean "do not store": it means "revalidate
        first". With the ETag already there that is one 304 per load,
        over the loopback interface.
        """

        def file_response(self, *args, **kwargs):
            response = super().file_response(*args, **kwargs)
            response.headers["cache-control"] = "no-cache"

            return response

    app.mount(
        "/static",
        RevalidatingStatics(directory=package_root / "static"),
        name="static",
    )
    templates = Jinja2Templates(directory=str(package_root / "templates"))

    app.state.jobs = JobRegistry()

    # Waveform extractions in flight, by song. Two requests for the same
    # song — a double click, or the player and a reload racing — would
    # otherwise each run ffmpeg and each write the file, and the second
    # write could land on top of the first. They share one task instead.
    # Per app rather than module-level: every app has its own event loop,
    # and a task belongs to the loop that created it.
    app.state.peak_jobs: dict[str, asyncio.Task] = {}

    def _count_reasons(failures) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in failures:
            counts[item.reason] = counts.get(item.reason, 0) + 1

        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    def _playlist_name(playlist_id: str) -> str:
        """The playlist's display name, without counting its songs.

        One directory listing. list_playlists would do, but it globs
        every playlist's MP3s to count them, and this runs once a second
        while a job polls.
        """

        # [[] and []] match literal brackets in fnmatch.
        for folder in app.state.repository_path.glob(f"*[[]{playlist_id}[]]"):
            return folder.name.replace(f"[{playlist_id}]", "").strip()

        return playlist_id

    def _job_fragment(
        request, job_id, playlist_id, state, result, error, elapsed=None,
        current=None
    ):
        """Render the self-polling fragment consumed by HTMX.

        `polling` is false for every terminal state, so the returned
        fragment carries no `hx-trigger` and the browser stops polling on
        its own — no client-side counter or stop condition needed. "busy"
        (a duplicate click while a job is already running) is *not*
        terminal: the fragment still carries the id the button targets, so
        if it did not keep polling, the swap on the second click would
        replace the live polling element with a dead one and the browser
        would never learn the job finished.
        """

        response = templates.TemplateResponse(
            request,
            "job.html",
            {
                "job_id": job_id,
                "playlist_id": playlist_id,
                "playlist_name": _playlist_name(playlist_id),
                # Two job kinds can target the same playlist. Without the
                # kind in the element id, a check and an import would fight
                # over one DOM node and swap each other away.
                "kind": job_id.partition(":")[0] or "job",
                "state": state,
                "result": result,
                "error": error,
                "elapsed": elapsed,
                "current": current or {},
                # What to say when no song has been announced yet.
                "busy_label": (
                    "Importing" if job_id.startswith("import:")
                    else "Checking"
                ),
                # Rendered verbatim next to the status text. Empty for the
                # first second so a fast job never flashes " 0s".
                "tick": f" {elapsed}s" if elapsed else "",
                "polling": state in ("pending", "running", "busy"),
            },
        )

        # #list and #nav refetch on songsChanged, and until now only a
        # save fired it — so an import wrote its files and the page had
        # no way of knowing. The songs were on disk and the listing kept
        # showing what it had.
        if _wrote_songs(job_id, state, result):
            response.headers["HX-Trigger"] = "songsChanged"

        return response

    def _wrote_songs(job_id: str, state: str, result) -> bool:
        """Whether a job in this state has put songs on disk.

        Checking only reads YouTube, so it never has. An import has,
        unless it finished having found nothing to fetch — which is the
        common case and would otherwise refetch the whole listing for
        nothing.

        A failed or cancelled import carries no report, so what it wrote
        before stopping is unknown: it counts. One wasted refetch beats
        songs sitting on disk that the page denies exist.
        """

        if not job_id.startswith("import:"):
            return False

        if state in ("pending", "running", "busy"):
            return False

        if state == "completed":
            return bool((result or {}).get("imported"))

        return True

    def _shazam_fragment(request, youtube_id: str, job):
        """Shazam's answer, or the poll that waits for it."""

        return templates.TemplateResponse(
            request,
            "_shazam.html",
            {
                "youtube_id": youtube_id,
                "state": job.state.value,
                "result": job.result,
                "error": job.error,
                "tick": (
                    f" {job.elapsed_seconds}s" if job.elapsed_seconds else ""
                ),
                "polling": job.state.value in ("pending", "running"),
            },
        )

    @app.post("/playlists/{playlist_id}/check")
    async def start_check(playlist_id: str, request: Request):
        loop = asyncio.get_running_loop()
        repository_path = app.state.repository_path
        is_htmx = request.headers.get("HX-Request") is not None

        async def work(job) -> dict:
            progress = WebProgress(app.state.jobs, job.job_id, loop)
            # Run in a worker thread: song.py and pytubefix block
            # synchronously, and the event loop must stay responsive.
            report = await asyncio.to_thread(
                check_new_songs,
                repository_path,
                playlist_id,
                progress,
                # The panel lists what it finds for ticking, and a list
                # of eleven-character video ids is not something anyone
                # can choose from.
                True,
            )
            return {
                "total_remote": report.total_remote,
                "already_local": report.already_local,
                "missing": report.missing,
            }

        try:
            job = app.state.jobs.start(f"check:{playlist_id}", work)
        except JobAlreadyRunning:
            if is_htmx:
                # HTMX never swaps the DOM on a 4xx, so a bare 409 would
                # look exactly like an inert button. Answer in-band with
                # the pane, which already shows the run in progress.
                return templates.TemplateResponse(
                    request,
                    "_imports.html",
                    _imports_context(request, playlist_id),
                )
            raise HTTPException(
                status_code=409, detail="already checking this playlist"
            )

        if is_htmx:
            # The pane, not a ribbon entry: this is the panel the button
            # opened, and it is where the whole run is watched.
            return templates.TemplateResponse(
                request,
                "_imports.html",
                _imports_context(request, playlist_id),
            )

        return {"job_id": job.job_id}

    @app.post("/playlists/{playlist_id}/import")
    async def start_import(playlist_id: str, request: Request):
        """Import the songs that were ticked, or everything missing.

        Awaited directly on the server's loop, not handed to a worker
        thread: `create_from_youtube` now runs its own blocking steps —
        download, ffmpeg, cover art — through asyncio.to_thread, so the
        coroutine itself cooperates and the loop stays free.
        """

        loop = asyncio.get_running_loop()
        repository_path = app.state.repository_path
        is_htmx = request.headers.get("HX-Request") is not None
        job_id = f"import:{playlist_id}"

        # The ticked rows, straight off the form. Absent means no panel
        # sent them — the CLI's behaviour, everything missing. Present
        # and empty means every row was unticked, which is a request to
        # import nothing, and the service keeps those two apart.
        form = await request.form()
        only = form.getlist("songs") if "songs" in form else None

        async def work(job) -> dict:
            progress = WebProgress(app.state.jobs, job.job_id, loop)
            report = await import_playlist(
                repository_path, playlist_id, progress, only=only
            )
            return {
                "total_remote": report.total_remote,
                "already_local": report.already_local,
                "imported": [
                    {
                        "youtube_id": song.youtube_id,
                        "filename": song.filename,
                        "artist": song.artist,
                        "title": song.title,
                        "score": song.shazam_match_score,
                        # Imported but unmatched: on disk, still needing a
                        # trip through the fix screen.
                        "is_junk": song.is_junk,
                    }
                    for song in report.imported
                ],
                "failed": [
                    {
                        "youtube_id": item.youtube_id,
                        "reason": item.reason,
                        "issue": item.issue,
                    }
                    for item in report.failed
                ],
                # Grouped so the page can say "12 age restricted" instead
                # of listing 22 opaque lines.
                "failed_by_reason": _count_reasons(report.failed),
            }

        try:
            job = app.state.jobs.start(job_id, work)
        except JobAlreadyRunning:
            if is_htmx:
                # HTMX never swaps the DOM on a 4xx, so a bare 409 would
                # look exactly like an inert button. Answer in-band with
                # the pane, which already shows the run in progress.
                return templates.TemplateResponse(
                    request,
                    "_imports.html",
                    _imports_context(request, playlist_id),
                )
            raise HTTPException(
                status_code=409, detail="already importing this playlist"
            )

        if is_htmx:
            # The pane, not a ribbon entry: this is the panel the button
            # opened, and it is where the whole run is watched.
            return templates.TemplateResponse(
                request,
                "_imports.html",
                _imports_context(request, playlist_id),
            )

        return {"job_id": job.job_id}

    @app.get("/jobs/{job_id}")
    def job_status(job_id: str, request: Request):
        job = app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job")

        if request.headers.get("HX-Request") is not None:
            # Job ids are minted as f"check:{playlist_id}" by start_check
            # above; recover the playlist id so the fragment's element id
            # matches the one the button's hx-target points at.
            playlist_id = job_id.partition(":")[2] or job_id
            return _job_fragment(
                request,
                job.job_id,
                playlist_id,
                job.state.value,
                job.result,
                job.error,
                job.elapsed_seconds,
                job.current,
            )

        return {
            "state": job.state.value,
            "current": job.current,
            "events": job.events,
            "result": job.result,
            "error": job.error,
        }

    def _selection(
        playlist: str, q: str, junk: int, match: float, artist: str = ""
    ):
        """The songs a query selects. Shared by the shell and the fragment.

        The artist filter is applied here rather than pushed into
        list_songs: picking a name off the nav means that name exactly,
        not the fuzzy scoring the search box wants.
        """

        songs = list_songs(
            app.state.repository_path,
            junk_only=bool(junk),
            keywords=q,
            match_threshold=match,
            playlist_identifier=playlist or None,
        )

        if artist:
            wanted = artist.casefold()
            songs = [s for s in songs if s.artist.casefold() == wanted]

        return songs

    @app.get("/", response_class=HTMLResponse)
    def console(
        request: Request,
        playlist: str = "",
        q: str = "",
        junk: int = 0,
        artist: str = "",
        match: float = DEFAULT_MATCH_THRESHOLD,
    ) -> HTMLResponse:
        """The whole application, in one page.

        Everything is here: playlists, the listing, the inspector, and a
        player that outlives every interaction. The query lives in the
        URL so reloading restores the view.
        """

        summaries = list_playlists(app.state.repository_path)

        # The unfiltered set, which the artist presets are grouped from.
        # A pass over 900 songs costs 1.4s, so when nothing is filtered —
        # the usual case — the listing reuses this rather than asking
        # again for the same thing.
        everything = _selection(playlist, "", 0, match)
        filtered = (
            everything
            if not (q or junk or artist)
            else _selection(playlist, q, junk, match, artist)
        )

        return templates.TemplateResponse(
            request,
            "console.html",
            {
                "summaries": summaries,
                "artists": list_artists(everything),
                "songs": filtered,
                "show_playlist": not playlist,
                "playlist": playlist,
                "query": q,
                "junk_only": bool(junk),
                "artist": artist,
                "total_songs": sum(s.total_songs for s in summaries),
                "total_junk": sum(s.junk_songs for s in summaries),
                "repository": str(app.state.repository_path),
                # The pane is included in the shell rather than fetched
                # after it, so a reload during an import shows the import
                # rather than an empty tab that fills in a second later.
                **_imports_context(request, playlist),
            },
        )

    def _merge_items(listed, working) -> list[dict]:
        """The list as it was drawn up, with the work done to it since.

        Order comes from the list: it is the order the songs will be
        fetched in, so a row never moves under the pointer. A song the
        working job knows and the list does not is appended — the list
        can be missing, after a restart, and a run with no rows at all
        would be worse than rows in an unexpected order.
        """

        names = {
            item["item_id"]: item.get("label")
            for item in (listed.items.values() if listed else ())
        }

        # Which songs there are is the working job's to say once it
        # exists: you may have ticked four of five, and the fifth must
        # not sit there looking like it is still coming.
        source = working or listed
        rows = []
        for item in (source.items.values() if source else ()):
            row = dict(item)
            # The sweep announces a position, not a name. Whatever the
            # list called the song is what the reader recognises.
            row["label"] = names.get(item["item_id"]) or row.get("label") or ""
            rows.append(row)

        return rows

    def _imports_context(request, playlist: str) -> dict:
        """What the imports pane shows, and which job it is watching.

        Whichever of the two started last. While an import runs, that is
        the import: the list you chose from is history and the rows that
        matter are the ones being fetched. The moment you ask for a new
        list, it is the check — and that half was missing, so a finished
        import stayed on screen for ever and a second one could never be
        started.
        """

        checking = app.state.jobs.get(f"check:{playlist}") if playlist else None
        running = app.state.jobs.get(f"import:{playlist}") if playlist else None
        both = [job for job in (checking, running) if job is not None]
        job = max(both, key=lambda one: one.started_at) if both else None

        if job is None:
            phase = "idle"
        elif job is running:
            phase = (
                "importing"
                if job.state.value in ("pending", "running")
                else "done"
            )
        else:
            phase = (
                "checking"
                if job.state.value in ("pending", "running")
                else "choosing"
            )

        # The check produced the list and its names; the import is
        # working through it and knows only the songs it has reached.
        # Neither alone is the pane: showing the import's items would
        # drop every song not yet started and label the one in flight
        # "1/4", and showing the check's would never move.
        # The check always supplies the names; the import supplies the
        # rows only when it is the run being shown.
        items = _merge_items(checking, running if job is running else None)
        states = [item.get("state") for item in items]

        return {
            "playlist_id": playlist,
            "playlist_name": _playlist_name(playlist) if playlist else "",
            "phase": phase,
            "items": items,
            "done_count": states.count("done"),
            "failed_count": states.count("failed"),
            # Empty for the first second, so a fast check never flashes
            # " 0s" before it has said anything.
            "tick": (
                f" {job.elapsed_seconds}s"
                if job and job.elapsed_seconds
                else ""
            ),
            "stages": IMPORT_STAGES,
            "polling": phase in ("checking", "importing"),
        }

    @app.get("/fragments/imports", response_class=HTMLResponse)
    def imports_fragment(
        request: Request, playlist: str = ""
    ) -> HTMLResponse:
        """The imports pane: what there is to fetch, and how it is going."""

        return templates.TemplateResponse(
            request, "_imports.html", _imports_context(request, playlist)
        )

    @app.get("/fragments/nav", response_class=HTMLResponse)
    def nav_fragment(
        request: Request,
        playlist: str = "",
        artist: str = "",
        match: float = DEFAULT_MATCH_THRESHOLD,
    ) -> HTMLResponse:
        """Playlists and artist presets, for the selected scope.

        Refetched when the playlist changes: the presets cover that
        playlist, so leaving the old ones on screen would offer artists
        the listing can no longer show.
        """

        summaries = list_playlists(app.state.repository_path)

        return templates.TemplateResponse(
            request,
            "_nav.html",
            {
                "summaries": summaries,
                "artists": list_artists(_selection(playlist, "", 0, match)),
                "playlist": playlist,
                "artist": artist,
                "total_songs": sum(s.total_songs for s in summaries),
            },
        )

    @app.get("/fragments/list", response_class=HTMLResponse)
    def list_fragment(
        request: Request,
        playlist: str = "",
        q: str = "",
        junk: int = 0,
        artist: str = "",
        match: float = DEFAULT_MATCH_THRESHOLD,
    ) -> HTMLResponse:
        """The listing on its own, for the console to swap in."""

        return templates.TemplateResponse(
            request,
            "_list.html",
            {
                "songs": _selection(playlist, q, junk, match, artist),
                # Repeating one playlist's name down 874 rows teaches
                # nothing. It earns its place only when the selection
                # spans more than one.
                "show_playlist": not playlist,
            },
        )

    def _current_playlist(request) -> str:
        """The playlist the browser is looking at, if any.

        Routes that answer with one row rather than a whole listing need
        it to render that row like its neighbours. htmx sends the page's
        address in HX-Current-URL; there is nowhere else to read it from.
        """

        current = request.headers.get("HX-Current-URL", "")

        return parse_qs(urlparse(current).query).get("playlist", [""])[0]

    def _summary_or_404(youtube_id: str):
        try:
            return summarize(SongModel(
                find_song_file(app.state.repository_path, youtube_id)
            ))
        except SongNotFound:
            raise HTTPException(status_code=404, detail="unknown song")

    @app.get("/fragments/inspector/{youtube_id}", response_class=HTMLResponse)
    def inspector_fragment(youtube_id: str, request: Request) -> HTMLResponse:
        """One song's details and the form that changes them."""

        return templates.TemplateResponse(
            request,
            "_inspector.html",
            {"song": _summary_or_404(youtube_id)},
        )

    @app.get("/fragments/workbench/{youtube_id}", response_class=HTMLResponse)
    def workbench_fragment(
        youtube_id: str, request: Request
    ) -> HTMLResponse:
        """The same song, laid out for judging a run of them.

        A separate template rather than a flag on the inspector: this one
        asks Shazam on sight, which the inspector deliberately does not.
        """

        return templates.TemplateResponse(
            request,
            "_workbench.html",
            {"song": _summary_or_404(youtube_id)},
        )

    @app.get("/fragments/shazam/{youtube_id}", response_class=HTMLResponse)
    def shazam_fragment(youtube_id: str, request: Request) -> HTMLResponse:
        """Where a running identification has got to."""

        job = app.state.jobs.get(f"shazam:{youtube_id}")
        if job is None:
            raise HTTPException(status_code=404, detail="no such job")

        return _shazam_fragment(request, youtube_id, job)


    @app.post("/songs/{youtube_id}/shazam")
    async def shazam_song(youtube_id: str, request: Request):
        """Ask Shazam what this is. Writes nothing.

        A job rather than a held-open request: identification takes
        seconds, and SongModel waits 15s between calls.
        """

        loop = asyncio.get_running_loop()
        repository_path = app.state.repository_path
        job_id = f"shazam:{youtube_id}"

        async def work(job) -> dict:
            progress = WebProgress(app.state.jobs, job.job_id, loop)
            proposal = await propose_fix(repository_path, youtube_id, progress)
            return {
                "matched": proposal.matched,
                "artist": proposal.shazam_artist,
                "title": proposal.shazam_title,
                "cover_art_url": proposal.shazam_cover_art_url,
                "score": proposal.shazam_match_score,
            }

        try:
            job = app.state.jobs.start(job_id, work)
        except JobAlreadyRunning:
            job = app.state.jobs.get(job_id)

        if request.headers.get("HX-Request") is not None:
            return _shazam_fragment(request, youtube_id, job)

        return {"job_id": job.job_id}

    @app.post("/songs/{youtube_id}/fix")
    async def submit_fix(youtube_id: str, request: Request):
        """Write the metadata the user settled on."""

        form = await request.form()

        try:
            result = await apply_fix(
                app.state.repository_path,
                youtube_id,
                artist=str(form.get("artist", "")).strip(),
                title=str(form.get("title", "")).strip(),
                cover_art_url=str(form.get("cover_art_url", "")).strip(),
            )
        except SongNotFound:
            raise HTTPException(status_code=404, detail="unknown song")

        # The file was renamed, but it keeps its YouTube id, so the finder
        # locates it again under its new name.
        song = summarize(SongModel(
            find_song_file(app.state.repository_path, youtube_id)
        ))

        if request.headers.get("HX-Request") is not None:
            # HX-Trigger rather than an out-of-band row swap: fixing a junk
            # song makes it not junk, so in a junk-filtered listing the row
            # must *leave*, not update. Only the server knows whether the
            # song still belongs to the current selection, so the console
            # refetches the listing and finds out.
            response = templates.TemplateResponse(
                request,
                "_inspector.html",
                {"song": song, "saved": True},
            )
            response.headers["HX-Trigger"] = "songsChanged"
            return response

        # A plain form POST navigates to whatever comes back, so returning
        # JSON left the browser showing raw data. Send it back to the list
        # it came from. 303 so a reload does not re-submit the form.
        return RedirectResponse(url="/?junk=1", status_code=303)

    @app.get("/songs/{youtube_id}/cover")
    def song_cover(youtube_id: str) -> Response:
        """Serve the embedded cover art, if the file carries one."""

        try:
            song = SongModel(
                find_song_file(app.state.repository_path, youtube_id)
            )
        except SongNotFound:
            raise HTTPException(status_code=404, detail="unknown song")

        pictures = song.mp3.tags.getall("APIC") if song.mp3.tags else []
        if not pictures:
            raise HTTPException(status_code=404, detail="no cover art")

        return Response(
            content=pictures[0].data,
            media_type=pictures[0].mime or "image/jpeg",
        )

    @app.get("/songs/{youtube_id}/audio")
    def song_audio(youtube_id: str) -> FileResponse:
        """Stream one song's MP3.

        FileResponse handles Range requests, which is what lets the
        browser's audio element seek without downloading the whole file
        first.
        """

        try:
            song_file = find_song_file(app.state.repository_path, youtube_id)
        except SongNotFound:
            raise HTTPException(status_code=404, detail="unknown song")

        return FileResponse(
            song_file, media_type="audio/mpeg", filename=song_file.name
        )

    @app.get("/songs/{youtube_id}/peaks")
    async def song_peaks(youtube_id: str) -> Response:
        """Serve one song's waveform, as one loudness per bar.

        Values run 0 to 1 rather than the 0 to 255 stored in the file:
        the endpoint should be readable on its own, and 400 short decimals
        cost under 3 KB over a loopback interface.

        Decoding blocks for about half a second the first time, so it goes
        to a thread. Every later request reads the tag and returns at once.
        """

        try:
            song_file = find_song_file(app.state.repository_path, youtube_id)
        except SongNotFound:
            raise HTTPException(status_code=404, detail="unknown song")

        jobs = app.state.peak_jobs
        task = jobs.get(youtube_id)
        if task is None:
            task = asyncio.create_task(asyncio.to_thread(peaks_for, song_file))
            jobs[youtube_id] = task
            task.add_done_callback(lambda _: jobs.pop(youtube_id, None))

        try:
            # Shielded so that a listener skipping to the next song — which
            # cancels this request — does not also kill a decode that other
            # listeners, or the next request for this song, are waiting on.
            peaks = await asyncio.shield(task)
        except WaveformError as error:
            # No waveform is not a broken page: the player falls back to
            # the plain bar, which seeks exactly as well.
            raise HTTPException(status_code=404, detail=str(error))

        return JSONResponse([round(value / 255, 3) for value in peaks])

    @app.post("/songs/{youtube_id}/junkize")
    def junkize(youtube_id: str, request: Request):
        """Clear one song's metadata and mark it as junk.

        Destructive and not undoable, so the button carries an hx-confirm.
        The route returns the song's row re-rendered from its new state,
        which replaces itself in place — the listing shows the outcome
        without a reload.
        """

        try:
            result = junkize_song(app.state.repository_path, youtube_id)
        except SongNotFound:
            raise HTTPException(status_code=404, detail="unknown song")

        song = summarize(SongModel(result.path))

        if request.headers.get("HX-Request") is not None:
            return templates.TemplateResponse(
                request,
                "_song_row.html",
                {
                    "song": song,
                    "junkized": True,
                    # The replaced row has to match its neighbours, and
                    # only the page knows whether a playlist is
                    # selected. HX-Current-URL is where htmx puts it.
                    "show_playlist": not _current_playlist(request),
                },
            )

        return {
            "youtube_id": result.youtube_id,
            "previous_filename": result.previous_filename,
            "filename": result.filename,
        }

    return app


def serve(repository_path: Path, port: int = DEFAULT_PORT) -> None:
    """Run the server until interrupted.

    Binds 127.0.0.1 unconditionally — the host is deliberately not a
    parameter.
    """

    uvicorn.run(
        create_app(repository_path),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
