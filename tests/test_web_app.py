"""The web application must serve locally and never bind a public interface."""

import inspect
from pathlib import Path

import httpx

from pypl2mp3.web.app import create_app, serve


def test_create_app_returns_a_fastapi_application(tmp_path):
    app = create_app(tmp_path)

    assert app.title == "PYPL2MP3"


async def test_health_endpoint_reports_the_repository(tmp_path):
    app = create_app(tmp_path)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "repository": str(tmp_path)}


def test_serve_binds_the_loopback_interface_only():
    """A local tool must never be reachable from the network by accident."""

    source = inspect.getsource(serve)

    assert "127.0.0.1" in source
    assert "0.0.0.0" not in source
