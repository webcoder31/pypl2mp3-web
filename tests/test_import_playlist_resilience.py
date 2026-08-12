"""Régression : une coupure réseau ne doit pas interrompre tout l'import.

pytubefix charge en différé : le constructeur `YouTube(url)` ne fait aucune
E/S, la requête part au premier accès d'attribut. Le gestionnaire d'erreur
doit donc couvrir cet accès, pas seulement la construction.
"""

import http.client
from types import SimpleNamespace

from pypl2mp3.commands import import_playlist as mod

VIDEO_IDS = ["AAAAAAAAAAA", "BBBBBBBBBBB"]
PLAYLIST_ID = "PLP6XxNg42qDGMg1cR2PPPzwdoAOD1MQ97"


class _FakePlaylist:
    """Playlist minimale : deux vidéos, aucun accès réseau."""

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
    """Constructeur silencieux, l'accès paresseux coupe — comme pytubefix."""

    def __init__(self, url, *args, **kwargs):
        self.video_id = url.rsplit("=", 1)[-1]

    @property
    def author(self):
        raise http.client.RemoteDisconnected(
            "Remote end closed connection without response"
        )

    @property
    def title(self):
        return "titre"


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

    # Ne doit pas lever : chaque vidéo échoue isolément.
    await mod.import_playlist(args)

    out = capsys.readouterr().out
    for video_id in VIDEO_IDS:
        assert video_id in out, (
            f"La vidéo {video_id} devrait figurer au rapport d'échecs"
        )
