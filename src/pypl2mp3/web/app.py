#!/usr/bin/env python3
"""FastAPI application serving the local web interface.

The server binds the loopback interface only. This is a single-user local
tool: it must never become reachable from the network because someone
passed the wrong flag.
"""

import asyncio
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pypl2mp3.services.check_new_songs import check_new_songs
from pypl2mp3.services.list_playlists import list_playlists
from pypl2mp3.services.list_songs import DEFAULT_MATCH_THRESHOLD, list_songs
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
    app.mount(
        "/static",
        StaticFiles(directory=package_root / "static"),
        name="static",
    )
    templates = Jinja2Templates(directory=str(package_root / "templates"))

    app.state.jobs = JobRegistry()

    def _job_fragment(
        request, job_id, playlist_id, state, result, error, elapsed=None
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
                "state": state,
                "result": result,
                "error": error,
                "elapsed": elapsed,
                # Rendered verbatim next to the status text. Empty for the
                # first second so a fast job never flashes " 0s".
                "tick": f" {elapsed}s" if elapsed else "",
                "polling": state in ("pending", "running", "busy"),
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
            )

        return {
            "state": job.state.value,
            "events": job.events,
            "result": job.result,
            "error": job.error,
        }

    @app.get("/", response_class=HTMLResponse)
    def inventory(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "playlists.html",
            {
                "summaries": list_playlists(app.state.repository_path),
                "repository": str(app.state.repository_path),
            },
        )

    @app.get("/songs", response_class=HTMLResponse)
    def songs(
        request: Request,
        playlist: str = "",
        q: str = "",
        junk: int = 0,
        match: float = DEFAULT_MATCH_THRESHOLD,
    ) -> HTMLResponse:
        """List songs, optionally scoped to a playlist and filtered.

        `junk=1` is the `junks` command: the same query with the flag
        flipped, which is why there is one route rather than two.
        """

        found = list_songs(
            app.state.repository_path,
            junk_only=bool(junk),
            keywords=q,
            match_threshold=match,
            playlist_identifier=playlist or None,
        )

        return templates.TemplateResponse(
            request,
            "songs.html",
            {
                "songs": found,
                "playlist": playlist,
                "query": q,
                "junk_only": bool(junk),
            },
        )

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
