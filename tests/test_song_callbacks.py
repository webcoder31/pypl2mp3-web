"""Projection du ProgressPort sur les callbacks de SongModel.

Deux niveaux de preuve ici : des tests unitaires sur la forme des
dictionnaires rendus, et deux tests qui font réellement tourner
`SongModel.create_from_youtube` (sans réseau ni encodage) pour vérifier que
les callbacks ne sont pas écrasés en route et que rien n'atteint stdout.
"""

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from pypl2mp3.libs import song as song_module
from pypl2mp3.libs.song import (
    ProgressBarInterface,
    SongModel,
    SongModelException,
)
from pypl2mp3.services._song_callbacks import (
    create_from_youtube_callbacks,
    shazam_song_callbacks,
    update_cover_art_callbacks,
)

from tests.doubles import FakeProgress


def _fake_song(
    artist: str = "The Pharcyde",
    title: str = "Passin' Me By",
    score: float | None = 66.0,
):
    return SimpleNamespace(
        shazam_artist=artist,
        shazam_title=title,
        shazam_match_score=score,
    )


# ---------------------------------------------------------------------------
# Chaque constructeur ne rend que des clés acceptées par SON API
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "builder, api",
    [
        (create_from_youtube_callbacks, SongModel.create_from_youtube),
        (update_cover_art_callbacks, SongModel.update_cover_art),
        (shazam_song_callbacks, SongModel.shazam_song),
    ],
    ids=["create_from_youtube", "update_cover_art", "shazam_song"],
)
def test_every_returned_key_is_accepted_by_its_own_api(builder, api):
    kwargs = builder(FakeProgress())
    accepted = set(inspect.signature(api).parameters)

    assert kwargs, "un constructeur vide passerait ce test sans rien prouver"
    assert set(kwargs) <= accepted

    # Preuve directe : le splat lèverait TypeError sur une clé inconnue.
    inspect.signature(api).bind_partial(**kwargs)


# ---------------------------------------------------------------------------
# C1 : les drapeaux de verbosité, sans lesquels song.py écrase tout
# ---------------------------------------------------------------------------


def test_create_from_youtube_callbacks_pin_the_verbosity_flags():
    kwargs = create_from_youtube_callbacks(FakeProgress())

    assert kwargs["verbose"] is True
    assert kwargs["use_default_verbosity"] is False


class _FakeStream:
    """Un flux audio qui rend compte de sa progression sans ouvrir de socket."""

    filesize = 1_000_000
    filesize_mb = 1.0

    def __init__(self, video):
        self._video = video

    def download(self, output_path, filename):
        # pytubefix notifie les callbacks enregistrés à chaque bloc reçu.
        # Paliers de 5 % : au-delà de 10 % d'écart, song.py anime le passage
        # point par point avec une pause de 10 ms à chaque fois.
        for bytes_remaining in (950_000, 900_000):
            for callback in self._video.progress_callbacks:
                callback(self, b"", bytes_remaining)


class _FakeYouTube:
    """Remplace `pytubefix.YouTube` : mêmes attributs, aucun appel réseau."""

    def __init__(self, url: str):
        self.url = url
        self.video_id = "FAKEVIDEO01"
        self.author = "Fake Artist"
        self.title = "Fake Title"
        self.thumbnail_url = "https://example.invalid/cover.jpg"
        self.progress_callbacks = []
        self.streams = SimpleNamespace(
            get_audio_only=lambda: _FakeStream(self)
        )

    def register_on_progress_callback(self, callback) -> None:
        self.progress_callbacks.append(callback)


def _refuse_to_encode(*args, **kwargs):
    """Barrière d'arrêt : l'encodage MP3 est hors sujet pour ce test."""

    raise RuntimeError("encodage non simulé")


async def _drive_import(tmp_path, monkeypatch, **kwargs) -> None:
    """Faire tourner le vrai `create_from_youtube` jusqu'à l'encodage.

    Le pipeline traverse ainsi la récupération des informations vidéo, le
    téléchargement audio complet et l'entrée dans l'encodage, puis s'arrête
    net sur la barrière.
    """

    monkeypatch.setattr(song_module, "YouTube", _FakeYouTube)
    monkeypatch.setattr(song_module, "AudioFileClip", _refuse_to_encode)

    with pytest.raises(SongModelException):
        await SongModel.create_from_youtube("FAKEVIDEO01", tmp_path, **kwargs)


async def test_the_port_receives_events_and_stdout_stays_empty(
    tmp_path, monkeypatch, capsys
):
    """C1 : les callbacks survivent au vrai `create_from_youtube`.

    Retirer les deux drapeaux du constructeur fait échouer ce test : song.py
    remplacerait les callbacks par ses propres closures et le port ne
    verrait rien passer.
    """

    progress = FakeProgress()

    await _drive_import(
        tmp_path, monkeypatch, **create_from_youtube_callbacks(progress)
    )

    assert progress.events == [
        ("stage_started", "download_audio", "Streaming audio:"),
        ("stage_progress", "download_audio", 5.0),
        ("stage_progress", "download_audio", 10.0),
        ("stage_done", "download_audio"),
        ("stage_started", "mp3_encode", "Encoding audio stream to MP3:"),
    ]
    assert capsys.readouterr().out == ""


async def test_without_the_flags_song_py_prints_and_the_port_gets_nothing(
    tmp_path, monkeypatch, capsys
):
    """Contre-épreuve du test précédent.

    Elle établit deux choses : que les prints de song.py sont bien visibles
    par capsys (sans quoi l'assertion de silence ne prouverait rien), et que
    ce sont bien les drapeaux qui font la différence.
    """

    progress = FakeProgress()
    kwargs = create_from_youtube_callbacks(progress)
    del kwargs["verbose"]
    del kwargs["use_default_verbosity"]

    await _drive_import(tmp_path, monkeypatch, **kwargs)

    assert progress.events == []
    assert capsys.readouterr().out != ""


# ---------------------------------------------------------------------------
# I1 : chaque étape s'annonce, progresse, puis se termine
# ---------------------------------------------------------------------------


# Les arguments correspondent à ceux que song.py passe réellement aux hooks :
# ils diffèrent d'une étape à l'autre.
_STREAMING_STAGES = [
    (
        "download_audio",
        "pre_download_audio",
        "on_download_audio",
        "post_download_audio",
        (SimpleNamespace(youtube_id="FAKEVIDEO01"), Path("temp.m4a")),
    ),
    (
        "mp3_encode",
        "pre_mp3_encode",
        "on_mp3_encode",
        "post_mp3_encode",
        (
            SimpleNamespace(youtube_id="FAKEVIDEO01"),
            Path("temp.m4a"),
            Path("temp.mp3"),
        ),
    ),
    (
        "download_cover_art",
        "pre_download_cover_art",
        "on_download_cover_art",
        "post_download_cover_art",
        (_fake_song(),),
    ),
]


@pytest.mark.parametrize(
    "stage, pre, on, post, hook_args",
    _STREAMING_STAGES,
    ids=[case[0] for case in _STREAMING_STAGES],
)
async def test_each_streaming_stage_frames_itself_with_its_own_identity(
    stage, pre, on, post, hook_args
):
    """Un identifiant faux, partagé ou ignoré fait tomber ce test.

    Il vérifie aussi que chaque hook accepte la forme d'arguments que
    song.py lui passe : une arité fausse ne se verrait qu'en production.
    """

    progress = FakeProgress()
    kwargs = create_from_youtube_callbacks(progress)

    await kwargs[pre](*hook_args)
    kwargs[on].callback(42, label="libellé injecté par song.py")
    await kwargs[post](*hook_args)

    assert progress.events == [
        ("stage_started", stage, kwargs[on].label),
        ("stage_progress", stage, 42.0),
        ("stage_done", stage),
    ]


def test_the_three_streaming_stages_do_not_share_an_identity():
    """Sans quoi une UI ne saurait pas quelle barre elle fait avancer."""

    progress = FakeProgress()
    kwargs = create_from_youtube_callbacks(progress)

    for _stage, _pre, on, _post, _args in _STREAMING_STAGES:
        kwargs[on].callback(1, label="")

    reported = [event[1] for event in progress.events]

    assert len(set(reported)) == 3, reported


def test_every_streaming_stage_carries_a_label():
    kwargs = create_from_youtube_callbacks(FakeProgress())

    for _stage, _pre, on, _post, _args in _STREAMING_STAGES:
        assert isinstance(kwargs[on], ProgressBarInterface), on
        assert kwargs[on].label, f"{on} doit porter un libellé"


async def test_update_cover_art_callbacks_frame_the_cover_art_stage():
    progress = FakeProgress()
    kwargs = update_cover_art_callbacks(progress)
    song = _fake_song()

    await kwargs["pre_download_cover_art"](song)
    kwargs["on_download_cover_art"].callback(70, label="Downloading (12 Kb):")
    await kwargs["post_download_cover_art"](song)

    assert progress.events == [
        ("stage_started", "download_cover_art", "Downloading cover art:"),
        ("stage_progress", "download_cover_art", 70.0),
        ("stage_done", "download_cover_art"),
    ]


# ---------------------------------------------------------------------------
# Shazam : début, résultat, fin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "builder",
    [create_from_youtube_callbacks, shazam_song_callbacks],
    ids=["create_from_youtube", "shazam_song"],
)
async def test_shazam_hooks_frame_the_stage_and_report_the_song(builder):
    progress = FakeProgress()
    kwargs = builder(progress)

    await kwargs["pre_shazam_song"](None)
    await kwargs["post_shazam_song"](_fake_song())

    assert progress.events == [
        ("stage_started", "shazam", "Shazam-ing audio track:"),
        ("song_identified", "The Pharcyde", "Passin' Me By", 66.0),
        ("stage_done", "shazam"),
    ]


async def test_a_missing_shazam_score_does_not_sink_the_hook():
    """song.py transforme toute exception de hook en échec d'import."""

    progress = FakeProgress()
    kwargs = shazam_song_callbacks(progress)

    await kwargs["post_shazam_song"](_fake_song(score=None))

    assert ("song_identified", "The Pharcyde", "Passin' Me By", 0.0) \
        in progress.events
