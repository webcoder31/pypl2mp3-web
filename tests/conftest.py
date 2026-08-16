"""Test-wide guards.

The suite must not reach the network. It slipped once, quietly: making
the playlist check name each missing song sent one YouTube request per
song, and the tests that exercised it went from instant to seconds and
started failing on their own polling budgets. Nothing said so — they had
patched `Playlist` and not `YouTube`, and the calls simply went out.

Blocking the socket makes that mistake loud instead of slow, and stops
the suite hammering the very service whose refusals it exists to handle.
"""

import socket

import pytest


class NetworkUsedInATest(RuntimeError):
    """Raised when a test tries to open a connection."""


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Refuse outbound connections for the length of every test.

    Loopback stays open: nothing here uses it, but a future test that
    starts a real server should fail on its own merits rather than on
    this.
    """

    real_connect = socket.socket.connect

    def refuse(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host in ("127.0.0.1", "::1", "localhost"):
            return real_connect(self, address, *args, **kwargs)

        raise NetworkUsedInATest(
            f"a test tried to reach {host}. Patch the client it goes "
            "through — YouTube here is always a double."
        )

    monkeypatch.setattr(socket.socket, "connect", refuse)
