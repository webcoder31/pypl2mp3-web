#!/usr/bin/env python3
"""Projection d'un ProgressPort sur les callbacks de SongModel.

`SongModel.create_from_youtube` attend quinze callbacks distincts. Plutôt
que d'imposer cette forme aux services, on l'isole ici : écrit une fois,
utilisé par tous.

`libs/song.py` n'est pas modifié — c'est délibéré. Ce module fait 1777 lignes
et porte le téléchargement et le tagging ; y toucher reviendrait à risquer le
cœur de valeur pour un gain cosmétique.
"""

from pypl2mp3.libs.song import ProgressBarInterface
from pypl2mp3.ports.progress import ProgressPort

# Étapes exposant une progression chiffrée, et le libellé affiché pour chacune.
_STREAMING_STAGES = {
    "on_download_audio": ("download_audio", "Streaming audio:"),
    "on_mp3_encode": ("mp3_encode", "Encoding audio stream to MP3:"),
    "on_download_cover_art": ("download_cover_art", "Downloading cover art:"),
}


def song_callbacks(progress: ProgressPort) -> dict[str, object]:
    """Construire les kwargs de callbacks pour `create_from_youtube`.

    Args:
        progress: le port qui recevra les événements.

    Returns:
        Un dictionnaire à passer en `**kwargs`. Ses clés sont un
        sous-ensemble des paramètres de `SongModel.create_from_youtube`.
    """

    kwargs: dict[str, object] = {}

    for param, (stage, label) in _STREAMING_STAGES.items():
        kwargs[param] = ProgressBarInterface(
            label=label,
            callback=_percent_forwarder(progress, stage),
        )

    async def pre_shazam_song(_song) -> None:
        progress.stage_started("shazam", "Shazam-ing audio track:")

    async def post_shazam_song(song) -> None:
        progress.song_identified(
            song.shazam_artist,
            song.shazam_title,
            float(song.shazam_match_score),
        )

    kwargs["pre_shazam_song"] = pre_shazam_song
    kwargs["post_shazam_song"] = post_shazam_song

    return kwargs


def _percent_forwarder(progress: ProgressPort, stage: str):
    """Adapter la signature `(percentage, label)` attendue par song.py."""

    def forward(percentage: int, label: str = "") -> None:
        progress.stage_progress(stage, float(percentage))

    return forward
