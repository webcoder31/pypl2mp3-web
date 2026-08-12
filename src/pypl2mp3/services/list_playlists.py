#!/usr/bin/env python3
"""Inventaire des playlists locales.

Lecture du système de fichiers exclusivement : aucun appel réseau, jamais.
Le service ne connaît ni terminal ni navigateur ; il rend des données, la
façade se charge de les présenter.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from pypl2mp3.libs.utils import get_song_id_from_filename, natural_sort_key

# Un dossier de playlist se termine par son identifiant entre crochets.
_PLAYLIST_PATTERN = re.compile(r"^.*\[(.?[^\]]+)\]$")


@dataclass(frozen=True)
class PlaylistSummary:
    """Ce qu'on sait d'une playlist sans interroger YouTube."""

    path: Path
    playlist_id: str
    name: str
    total_songs: int
    junk_songs: int

    @property
    def valid_songs(self) -> int:
        """Titres correctement tagués, c'est-à-dire non « junk »."""

        return self.total_songs - self.junk_songs


def list_playlists(repository_path: Path) -> list[PlaylistSummary]:
    """Résumer chaque playlist du dépôt, triée par ordre naturel.

    Args:
        repository_path: dossier contenant les playlists.

    Returns:
        Un résumé par playlist. Liste vide si le dépôt n'en contient aucune.
    """

    paths = [
        Path(path)
        for path in repository_path.glob("*/")
        if _PLAYLIST_PATTERN.match(str(path))
    ]
    paths.sort(key=natural_sort_key)

    return [_summarize(path) for path in paths]


def _summarize(playlist_path: Path) -> PlaylistSummary:
    playlist_id = get_song_id_from_filename(playlist_path.name)

    return PlaylistSummary(
        path=playlist_path,
        playlist_id=playlist_id,
        name=playlist_path.name.replace(f"[{playlist_id}]", "").strip(),
        total_songs=len(list(playlist_path.glob("*.mp3"))),
        junk_songs=len(list(playlist_path.glob("* (JUNK).mp3"))),
    )
