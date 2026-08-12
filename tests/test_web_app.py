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


def test_serve_binds_the_loopback_interface_only(tmp_path, monkeypatch):
    """A local tool must never be reachable from the network by accident.

    Checked at the call boundary rather than by reading the source: a
    source grep passes even when the host becomes a parameter or is read
    from the environment.
    """

    captured = {}

    def fake_run(app, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("pypl2mp3.web.app.uvicorn.run", fake_run)
    monkeypatch.setenv("PYPL2MP3_HOST", "0.0.0.0")

    serve(tmp_path, port=1234)

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 1234


def test_serve_exposes_no_way_to_change_the_host():
    """The host must not be overridable by a caller, by design."""

    parameters = inspect.signature(serve).parameters

    assert "host" not in parameters
