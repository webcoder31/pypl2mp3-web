"""Regression: a network drop must not abort the whole import.

pytubefix loads lazily: the `YouTube(url)` constructor performs no I/O, the
request goes out on the first attribute access. The error handler must
therefore cover that access, not just the construction.
"""

import http.client
from types import SimpleNamespace

from pypl2mp3.commands import import_playlist as mod

VIDEO_IDS = ["AAAAAAAAAAA", "BBBBBBBBBBB"]
PLAYLIST_ID = "PLP6XxNg42qDGMg1cR2PPPzwdoAOD1MQ97"


class _FakePlaylist:
    """Minimal playlist: two videos, no network access."""

    def __init__(self, url, *args, **kwargs):
        self.videos = list(VIDEO_IDS)
        self.length = len(VIDEO_IDS)
        self.title = "fake"
        self.owner = "owner"
        self.playlist_id = PLAYLIST_ID
        self.video_urls = [
            f"https://www.youtube.com/watch?v={vid}" for vid in VIDEO_IDS
        ]


class _DisconnectingYouTube:
    """Silent constructor, the lazy access drops — just like pytubefix."""

    def __init__(self, url, *args, **kwargs):
        self.video_id = url.rsplit("=", 1)[-1]

    @property
    def author(self):
        raise http.client.RemoteDisconnected(
            "Remote end closed connection without response"
        )

    @property
    def title(self):
        return "title"


async def test_network_failure_skips_video_without_aborting_import(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(mod, "Playlist", _FakePlaylist)
    monkeypatch.setattr(mod, "YouTube", _DisconnectingYouTube)

    args = SimpleNamespace(
        repo=str(tmp_path),
        playlist=PLAYLIST_ID,
        keywords="",
        match=0,
        thresh=50,
        prompt=False,
    )

    # Must not raise: each video fails on its own.
    await mod.import_playlist(args)

    out = capsys.readouterr().out
    for video_id in VIDEO_IDS:
        assert video_id in out, (
            f"Video {video_id} should appear in the failure report"
        )
