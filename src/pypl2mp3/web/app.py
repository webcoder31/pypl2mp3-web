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
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pypl2mp3.libs.song import SongModel
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

        return templates.TemplateResponse(
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
                check_new_songs, repository_path, playlist_id, progress
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
                # HTMX never swaps the DOM on a 4xx response, so a bare 409
                # here would look exactly like the inert button this task
                # exists to fix. Report the collision in-band instead.
                running = app.state.jobs.get(f"check:{playlist_id}")
                return _job_fragment(
                    request,
                    f"check:{playlist_id}",
                    playlist_id,
                    "busy",
                    None,
                    None,
                    running.elapsed_seconds if running else None,
                    running.current if running else None,
                )
            raise HTTPException(
                status_code=409, detail="already checking this playlist"
            )

        if is_htmx:
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

        return {"job_id": job.job_id}

    @app.post("/playlists/{playlist_id}/import")
    async def start_import(playlist_id: str, request: Request):
        """Import every song the playlist has and the repository lacks.

        Awaited directly on the server's loop, not handed to a worker
        thread: `create_from_youtube` now runs its own blocking steps —
        download, ffmpeg, cover art — through asyncio.to_thread, so the
        coroutine itself cooperates and the loop stays free.
        """

        loop = asyncio.get_running_loop()
        repository_path = app.state.repository_path
        is_htmx = request.headers.get("HX-Request") is not None
        job_id = f"import:{playlist_id}"

        async def work(job) -> dict:
            progress = WebProgress(app.state.jobs, job.job_id, loop)
            report = await import_playlist(
                repository_path, playlist_id, progress
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
                running = app.state.jobs.get(job_id)
                return _job_fragment(
                    request,
                    job_id,
                    playlist_id,
                    "busy",
                    None,
                    None,
                    running.elapsed_seconds if running else None,
                    running.current if running else None,
                )
            raise HTTPException(
                status_code=409, detail="already importing this playlist"
            )

        if is_htmx:
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
            },
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

    @app.get("/jobs/{job_id}/report", response_class=HTMLResponse)
    def job_report(job_id: str, request: Request) -> HTMLResponse:
        """The full outcome of a run, song by song.

        The inline fragment has room for counts only. Knowing which songs
        arrived, which did not, and why, is the whole point of running an
        import you cannot watch.
        """

        job = app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job")

        return templates.TemplateResponse(
            request,
            # In the console this lands in the inspector, so it must not
            # bring a whole document with it.
            (
                "_report.html"
                if request.headers.get("HX-Request") is not None
                else "report.html"
            ),
            {
                "job_id": job_id,
                "state": job.state.value,
                "result": job.result or {},
                "error": job.error,
                "elapsed": job.elapsed_seconds,
            },
        )

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
