#!/usr/bin/env python3
"""FastAPI application serving the local web interface.

The server binds the loopback interface only. This is a single-user local
tool: it must never become reachable from the network because someone
passed the wrong flag.
"""

from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pypl2mp3.services.list_playlists import list_playlists

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
