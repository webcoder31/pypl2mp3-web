#!/usr/bin/env python3
"""Projection d'un ProgressPort sur les callbacks de SongModel.

Trois API de `SongModel` acceptent des hooks, et chacune n'accepte que les
siens : passer à `update_cover_art` le dictionnaire taillé pour
`create_from_youtube` lève un `TypeError`. D'où un constructeur par API,
plutôt qu'un dictionnaire unique qui ne conviendrait qu'à la première.

Deux pièges de `libs/song.py` sont neutralisés ici, une fois pour toutes :

- `create_from_youtube` réécrit ses quinze callbacks avec ses propres
  closures d'affichage tant que `use_default_verbosity` vaut `True` (et les
  annule tous si `verbose` ne vaut pas `True`). Les deux drapeaux font donc
  partie du dictionnaire rendu : un appelant ne peut plus les oublier.
- les hooks `pre_`/`post_` sont attendus (`await`), alors que le callback de
  progression d'un `ProgressBarInterface` est appelé de façon synchrone au
  cœur de la boucle de téléchargement. D'où l'asymétrie `async def` / `def`
  ci-dessous : l'inverser lève `TypeError` à l'exécution seulement.

`libs/song.py` n'est pas modifié — c'est délibéré. Ce module fait 1777 lignes
et porte le téléchargement et le tagging ; y toucher reviendrait à risquer le
cœur de valeur pour un gain cosmétique.
"""

from dataclasses import dataclass

from pypl2mp3.libs.song import ProgressBarInterface
from pypl2mp3.ports.progress import ProgressPort


@dataclass(frozen=True)
class _Stage:
    """Une étape chiffrée : son identité pour le port, ses hooks pour song.py.

    Attributes:
        stage: identifiant stable transmis au port.
        label: libellé lisible, également utilisé par les barres de song.py.
        pre: nom du paramètre appelé à l'entrée de l'étape.
        on: nom du paramètre recevant le `ProgressBarInterface`.
        post: nom du paramètre appelé à la sortie de l'étape.
    """

    stage: str
    label: str
    pre: str
    on: str
    post: str


# Les trois étapes exposant une progression chiffrée.
# Chacune porte son propre identifiant : c'est ce qui permet à une UI de
# distinguer le téléchargement de l'encodage.
_DOWNLOAD_AUDIO = _Stage(
    stage="download_audio",
    label="Streaming audio:",
    pre="pre_download_audio",
    on="on_download_audio",
    post="post_download_audio",
)

_MP3_ENCODE = _Stage(
    stage="mp3_encode",
    label="Encoding audio stream to MP3:",
    pre="pre_mp3_encode",
    on="on_mp3_encode",
    post="post_mp3_encode",
)

_DOWNLOAD_COVER_ART = _Stage(
    stage="download_cover_art",
    label="Downloading cover art:",
    pre="pre_download_cover_art",
    on="on_download_cover_art",
    post="post_download_cover_art",
)

# La reconnaissance Shazam n'expose aucun pourcentage : début et fin, rien
# entre les deux, plus le résultat de l'identification.
_SHAZAM_STAGE = "shazam"
_SHAZAM_LABEL = "Shazam-ing audio track:"


def create_from_youtube_callbacks(progress: ProgressPort) -> dict[str, object]:
    """Construire les kwargs de `SongModel.create_from_youtube`.

    Le dictionnaire rendu contient aussi `verbose` et `use_default_verbosity`
    : sans eux, song.py écraserait tous les callbacks et écrirait ses barres
    de progression sur stdout — rédhibitoire pour un serveur web.

    Args:
        progress: le port qui recevra les événements.

    Returns:
        Un dictionnaire à passer en `**kwargs`. Ses clés sont un
        sous-ensemble des paramètres de `SongModel.create_from_youtube`.
    """

    kwargs: dict[str, object] = {
        "verbose": True,
        "use_default_verbosity": False,
    }

    for stage in (_DOWNLOAD_AUDIO, _MP3_ENCODE, _DOWNLOAD_COVER_ART):
        kwargs.update(_stage_hooks(progress, stage))

    kwargs.update(_shazam_hooks(progress))

    return kwargs


def update_cover_art_callbacks(progress: ProgressPort) -> dict[str, object]:
    """Construire les kwargs de `SongModel.update_cover_art`.

    Args:
        progress: le port qui recevra les événements.

    Returns:
        Un dictionnaire à passer en `**kwargs`. Ses clés sont un
        sous-ensemble des paramètres de `SongModel.update_cover_art`.
    """

    return _stage_hooks(progress, _DOWNLOAD_COVER_ART)


def shazam_song_callbacks(progress: ProgressPort) -> dict[str, object]:
    """Construire les kwargs de `SongModel.shazam_song`.

    Args:
        progress: le port qui recevra les événements.

    Returns:
        Un dictionnaire à passer en `**kwargs`. Ses clés sont un
        sous-ensemble des paramètres de `SongModel.shazam_song`.
    """

    return _shazam_hooks(progress)


def _stage_hooks(progress: ProgressPort, stage: _Stage) -> dict[str, object]:
    """Encadrer une étape chiffrée : début, progression, fin.

    Les hooks `pre_`/`post_` reçoivent des arguments de formes différentes
    selon l'étape — `(video_props, m4a_path)` pour l'audio,
    `(video_props, m4a_path, mp3_path)` pour l'encodage, `(song)` pour la
    pochette. Aucun ne nous sert : seule l'identité de l'étape compte, d'où
    le `*_args` qui les accepte toutes.
    """

    async def stage_started(*_args) -> None:
        progress.stage_started(stage.stage, stage.label)

    async def stage_done(*_args) -> None:
        progress.stage_done(stage.stage)

    return {
        stage.pre: stage_started,
        stage.on: ProgressBarInterface(
            label=stage.label,
            callback=_percent_forwarder(progress, stage.stage),
        ),
        stage.post: stage_done,
    }


def _shazam_hooks(progress: ProgressPort) -> dict[str, object]:
    """Encadrer la reconnaissance Shazam et rapporter son résultat."""

    async def pre_shazam_song(_song) -> None:
        progress.stage_started(_SHAZAM_STAGE, _SHAZAM_LABEL)

    async def post_shazam_song(song) -> None:
        # `or 0` : song.py se protège de la même façon (cf. fix_filename).
        # Un score absent ferait échouer le hook, donc l'import entier.
        progress.song_identified(
            song.shazam_artist,
            song.shazam_title,
            float(song.shazam_match_score or 0),
        )
        progress.stage_done(_SHAZAM_STAGE)

    return {
        "pre_shazam_song": pre_shazam_song,
        "post_shazam_song": post_shazam_song,
    }


def _percent_forwarder(progress: ProgressPort, stage: str):
    """Adapter la signature `(percentage, label)` attendue par song.py.

    Le libellé est ignoré : le port l'a déjà reçu via `stage_started`, et
    song.py y injecte la taille du fichier, qui varie d'un appel à l'autre.
    """

    def forward(percentage: int, label: str = "") -> None:
        progress.stage_progress(stage, float(percentage))

    return forward
