# Fondations (ports, services, tests) — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduire la couche de ports et de services décrite dans le spec, avec l'infrastructure de tests, et migrer une commande de bout en bout comme motif de référence — sans changer une seule ligne du comportement CLI observable.

**Architecture:** Deux ports (`InteractionPort`, `ProgressPort`) définissent les contrats entre l'orchestration et l'affichage. Les services portent l'orchestration débarrassée de tout `print` ; les modules `commands/` deviennent des façades d'affichage. `libs/` n'est pas touché : un adaptateur projette `ProgressPort` sur les dix-huit callbacks de `song.py`.

**Tech Stack:** Python 3.13, pytest + pytest-asyncio, dataclasses, `typing.Protocol`.

**Spec de référence:** `docs/superpowers/specs/2026-08-11-web-ui-design.md`

## Global Constraints

- Python requis : `~=3.13.0` (soit `>=3.13.0, <3.14`). Ne pas élargir.
- `pytubefix>=10.11.0,<11`. Ne pas revenir en 9.x : la 9.x renvoie des playlists vides.
- **`src/pypl2mp3/libs/` reste inchangé.** Aucune modification de `song.py`, `repository.py`, `logger.py`, `utils.py`, `exceptions.py` dans ce plan.
- **Ne jamais passer `client="WEB"`** à `YouTube()` ou `Playlist()`. Le défaut `ANDROID_VR` est requis, sinon le téléchargement échoue en `SABRError`.
- **Tout accès à un attribut pytubefix doit se trouver dans le bloc `try` protégé.** Le constructeur ne fait aucune E/S ; la requête part au premier accès d'attribut.
- **Aucune commande de listing local ne déclenche d'appel réseau**, même indirect.
- `ProgressPort` : méthodes **synchrones et non bloquantes**. `InteractionPort.ask` : **`async`**.
- Nom du package Python : `pypl2mp3` (inchangé). Commande CLI : `pypl2mp3` (inchangée).
- Aucune dépendance à une base de données. Le système de fichiers est la source de vérité.
- Les messages de commit sont en anglais, comme l'historique existant.

---

### Task 1: Infrastructure de tests et première régression

Le projet n'a aucun test. Cette tâche en pose le cadre et y verse la régression du bug corrigé le 2026-08-11 (une coupure réseau tuait l'import entier).

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/test_import_playlist_resilience.py`

**Interfaces:**
- Consumes: rien.
- Produces: `pytest` exécutable à la racine ; répertoire `tests/` où les tâches suivantes ajoutent leurs fichiers.

- [ ] **Step 1: Déclarer pytest en dépendance de développement et le configurer**

`pytest` et `pytest-asyncio` ne sont aujourd'hui présents que **par transitivité via `shazamio`**. S'appuyer là-dessus est fragile : une mise à jour de `shazamio` les ferait disparaître. On les déclare explicitement.

Ajouter à la fin de `pyproject.toml` :

```toml
[dependency-groups]
dev = [
    "pytest>=7.4,<9",
    "pytest-asyncio>=0.20,<1",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

`asyncio_mode = "auto"` évite d'avoir à décorer chaque test asynchrone avec `@pytest.mark.asyncio`.

- [ ] **Step 2: Synchroniser l'environnement**

Run: `uv sync`
Expected: succès, aucune erreur de résolution.

- [ ] **Step 3: Créer le paquet de tests**

Créer `tests/__init__.py`, fichier vide.

- [ ] **Step 4: Écrire le test de régression**

Créer `tests/test_import_playlist_resilience.py` :

```python
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
```

- [ ] **Step 5: Lancer le test**

Run: `uv run pytest tests/test_import_playlist_resilience.py -v`
Expected: PASS. Le correctif est déjà présent dans la base héritée (commit `b489fc7`) ; ce test le verrouille contre une régression future.

- [ ] **Step 6: Vérifier que le test détecte bien le bug**

Contrôle que le test n'est pas complaisant. Réintroduire temporairement le bug dans `src/pypl2mp3/commands/import_playlist.py` : supprimer la ligne `video_author, video_title = video.author, video.title` du bloc `try`, et rétablir `video.author` / `video.title` aux trois usages qui suivent.

Run: `uv run pytest tests/test_import_playlist_resilience.py -v`
Expected: FAIL avec `RemoteDisconnected`.

Puis annuler la modification : `git checkout src/pypl2mp3/commands/import_playlist.py`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml tests/
git commit -m "test: add pytest setup and a network-resilience regression test"
```

---

### Task 2: Port d'interaction

**Files:**
- Create: `src/pypl2mp3/ports/__init__.py`
- Create: `src/pypl2mp3/ports/interaction.py`
- Create: `tests/doubles.py`
- Create: `tests/test_interaction_port.py`

**Interfaces:**
- Consumes: `pypl2mp3.libs.utils.prompt_user(question: str, options: list[str]) -> str`
- Produces:
  - `InteractionPort` — protocole, méthode `async def ask(self, question: str, options: list[str]) -> str`
  - `InteractionAbandoned(Exception)` — levée quand l'interlocuteur disparaît avant de répondre. **Sans consommateur dans ce plan** : c'est `WebInteraction` (plan 2) qui la lèvera à la fermeture du navigateur. Elle est définie ici parce qu'elle fait partie du contrat du port, pas de son implémentation web. Ne pas la supprimer en la prenant pour du code mort.
  - `ConsoleInteraction` — implémentation terminal
  - `tests.doubles.FakeInteraction(answers: list[str])` — doublure scriptée, expose `asked: list[tuple[str, list[str]]]`

- [ ] **Step 1: Créer le paquet ports**

Créer `src/pypl2mp3/ports/__init__.py`, fichier vide.

- [ ] **Step 2: Écrire le test du port console**

Créer `tests/test_interaction_port.py` :

```python
from pypl2mp3.ports.interaction import ConsoleInteraction

from tests.doubles import FakeInteraction


async def test_console_interaction_returns_user_answer(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt: "YES")

    answer = await ConsoleInteraction().ask("Continuer", ["yes", "no"])

    # prompt_user normalise en minuscules ; le port ne doit pas altérer cela.
    assert answer == "yes"


async def test_fake_interaction_returns_scripted_answers():
    fake = FakeInteraction(["yes", "no"])

    assert await fake.ask("Q1", ["yes", "no"]) == "yes"
    assert await fake.ask("Q2", ["yes", "no"]) == "no"
    assert fake.asked == [("Q1", ["yes", "no"]), ("Q2", ["yes", "no"])]


async def test_fake_interaction_fails_loudly_when_script_runs_out():
    fake = FakeInteraction([])

    try:
        await fake.ask("Q", ["yes"])
    except AssertionError as exc:
        assert "Q" in str(exc)
    else:
        raise AssertionError("aurait dû lever AssertionError")
```

- [ ] **Step 3: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/test_interaction_port.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'pypl2mp3.ports.interaction'`

- [ ] **Step 4: Écrire le port**

Créer `src/pypl2mp3/ports/interaction.py` :

```python
#!/usr/bin/env python3
"""Contrat d'interaction entre l'orchestration et l'utilisateur.

En terminal, poser une question bloque sur une saisie. Sur un serveur, c'est
interdit. Ce port est la seule frontière où les deux mondes diffèrent : les
services le consomment sans savoir à qui ils s'adressent.
"""

from typing import Protocol, runtime_checkable

from pypl2mp3.libs.utils import prompt_user


class InteractionAbandoned(Exception):
    """L'interlocuteur a disparu avant de répondre.

    Un service qui reçoit cette exception doit traiter l'opération comme
    abandonnée, jamais comme un plantage.
    """


@runtime_checkable
class InteractionPort(Protocol):
    """Poser une question, obtenir une réponse parmi des options."""

    async def ask(self, question: str, options: list[str]) -> str:
        ...


class ConsoleInteraction:
    """Implémentation terminal : délègue à l'`input()` existant.

    Bloquer est acceptable ici : la CLI n'a rien d'autre à faire pendant ce
    temps. Le comportement est identique à celui d'avant l'introduction du
    port.
    """

    async def ask(self, question: str, options: list[str]) -> str:
        return prompt_user(question, options)
```

- [ ] **Step 5: Écrire la doublure de test**

Créer `tests/doubles.py` :

```python
"""Doublures des ports, pour tester les services sans terminal ni réseau."""


class FakeInteraction:
    """Répond selon un script prédéfini et consigne les questions posées."""

    def __init__(self, answers: list[str]):
        self._answers = list(answers)
        self.asked: list[tuple[str, list[str]]] = []

    async def ask(self, question: str, options: list[str]) -> str:
        self.asked.append((question, list(options)))
        if not self._answers:
            raise AssertionError(
                f"Aucune réponse scriptée restante pour : {question!r}"
            )
        return self._answers.pop(0)
```

- [ ] **Step 6: Lancer les tests**

Run: `uv run pytest tests/test_interaction_port.py -v`
Expected: 3 PASS

- [ ] **Step 7: Commit**

```bash
git add src/pypl2mp3/ports/ tests/doubles.py tests/test_interaction_port.py
git commit -m "feat: add the interaction port with console and fake implementations"
```

---

### Task 3: Port de progression

**Files:**
- Create: `src/pypl2mp3/ports/progress.py`
- Modify: `tests/doubles.py`
- Create: `tests/test_progress_port.py`

**Interfaces:**
- Consumes: rien de `libs/`.
- Produces:
  - `ProgressPort` — protocole à quatre méthodes **synchrones** : `stage_started(stage: str, label: str) -> None`, `stage_progress(stage: str, percent: float) -> None`, `stage_done(stage: str) -> None`, `song_identified(artist: str, title: str, score: float) -> None`
  - `NullProgress` — implémentation neutre, utile quand aucun affichage n'est voulu
  - `tests.doubles.FakeProgress` — enregistre les appels dans `events: list[tuple]`

- [ ] **Step 1: Écrire le test**

Créer `tests/test_progress_port.py` :

```python
from pypl2mp3.ports.progress import NullProgress, ProgressPort

from tests.doubles import FakeProgress


def test_null_progress_accepts_every_call_and_returns_none():
    port = NullProgress()

    assert port.stage_started("download", "Streaming audio:") is None
    assert port.stage_progress("download", 42.0) is None
    assert port.stage_done("download") is None
    assert port.song_identified("The Pharcyde", "Passin' Me By", 66.0) is None


def test_fake_progress_records_events_in_order():
    port = FakeProgress()

    port.stage_started("download", "Streaming audio:")
    port.stage_progress("download", 50.0)
    port.stage_done("download")

    assert port.events == [
        ("stage_started", "download", "Streaming audio:"),
        ("stage_progress", "download", 50.0),
        ("stage_done", "download"),
    ]


def test_implementations_satisfy_the_protocol():
    assert isinstance(NullProgress(), ProgressPort)
    assert isinstance(FakeProgress(), ProgressPort)
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/test_progress_port.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'pypl2mp3.ports.progress'`

- [ ] **Step 3: Écrire le port**

Créer `src/pypl2mp3/ports/progress.py` :

```python
#!/usr/bin/env python3
"""Contrat de signalement d'avancement.

Ces méthodes sont synchrones et ne doivent JAMAIS bloquer : elles sont
appelées depuis les callbacks de `song.py`, au cœur de boucles de
téléchargement où une attente dégraderait le débit.

L'asymétrie avec `InteractionPort.ask` (asynchrone) est voulue : signaler un
avancement n'attend rien, poser une question attend une réponse.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class ProgressPort(Protocol):
    """Signaler l'avancement d'une opération longue."""

    def stage_started(self, stage: str, label: str) -> None:
        ...

    def stage_progress(self, stage: str, percent: float) -> None:
        ...

    def stage_done(self, stage: str) -> None:
        ...

    def song_identified(self, artist: str, title: str, score: float) -> None:
        ...


class NullProgress:
    """N'affiche rien. Pour les appels où l'avancement n'intéresse personne."""

    def stage_started(self, stage: str, label: str) -> None:
        return None

    def stage_progress(self, stage: str, percent: float) -> None:
        return None

    def stage_done(self, stage: str) -> None:
        return None

    def song_identified(self, artist: str, title: str, score: float) -> None:
        return None
```

- [ ] **Step 4: Ajouter la doublure**

Ajouter à la fin de `tests/doubles.py` :

```python
class FakeProgress:
    """Enregistre les événements reçus, sans rien afficher."""

    def __init__(self):
        self.events: list[tuple] = []

    def stage_started(self, stage: str, label: str) -> None:
        self.events.append(("stage_started", stage, label))

    def stage_progress(self, stage: str, percent: float) -> None:
        self.events.append(("stage_progress", stage, percent))

    def stage_done(self, stage: str) -> None:
        self.events.append(("stage_done", stage))

    def song_identified(self, artist: str, title: str, score: float) -> None:
        self.events.append(("song_identified", artist, title, score))
```

- [ ] **Step 5: Lancer les tests**

Run: `uv run pytest tests/test_progress_port.py -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add src/pypl2mp3/ports/progress.py tests/doubles.py tests/test_progress_port.py
git commit -m "feat: add the progress port with null and fake implementations"
```

---

### Task 4: Adaptateur ProgressPort vers les callbacks de song.py

`SongModel.create_from_youtube` accepte dix-huit paramètres de callback (`song.py:514-535`). On ne touche pas à cette signature : `song.py` fait 1777 lignes et porte le cœur de valeur. L'adaptateur absorbe la verrue, une fois pour toutes.

**Files:**
- Create: `src/pypl2mp3/services/__init__.py`
- Create: `src/pypl2mp3/services/_song_callbacks.py`
- Create: `tests/test_song_callbacks.py`

**Interfaces:**
- Consumes: `ProgressPort` (Task 3) ; `pypl2mp3.libs.song.ProgressBarInterface`, dataclass de champs `label: str` et `callback: Optional[Callable[[int, str], None]]`.
- Produces: `song_callbacks(progress: ProgressPort) -> dict[str, object]` — dictionnaire à passer tel quel en `**kwargs` à `SongModel.create_from_youtube`.

- [ ] **Step 1: Écrire le test**

Créer `tests/test_song_callbacks.py` :

```python
from pypl2mp3.libs.song import ProgressBarInterface
from pypl2mp3.services._song_callbacks import song_callbacks

from tests.doubles import FakeProgress


def test_returns_progress_bar_interfaces_for_the_three_streaming_stages():
    kwargs = song_callbacks(FakeProgress())

    for key in ("on_download_audio", "on_mp3_encode", "on_download_cover_art"):
        assert isinstance(kwargs[key], ProgressBarInterface), key
        assert kwargs[key].label, f"{key} doit porter un libellé"


def test_progress_bar_callback_forwards_percent_to_the_port():
    progress = FakeProgress()
    kwargs = song_callbacks(progress)

    kwargs["on_download_audio"].callback(42, "Streaming audio:")

    assert ("stage_progress", "download_audio", 42.0) in progress.events


def test_shazam_hooks_report_the_identified_song():
    progress = FakeProgress()
    kwargs = song_callbacks(progress)

    song = type(
        "FakeSong",
        (),
        {
            "shazam_artist": "The Pharcyde",
            "shazam_title": "Passin' Me By",
            "shazam_match_score": 66.0,
        },
    )()

    kwargs["post_shazam_song"](song)

    assert (
        "song_identified",
        "The Pharcyde",
        "Passin' Me By",
        66.0,
    ) in progress.events


def test_every_returned_key_is_accepted_by_create_from_youtube():
    import inspect

    from pypl2mp3.libs.song import SongModel

    accepted = set(
        inspect.signature(SongModel.create_from_youtube).parameters
    )
    assert set(song_callbacks(FakeProgress())) <= accepted
```

Le dernier test est le garde-fou qui compte : il détecte immédiatement une faute de frappe dans un nom de paramètre, erreur qui passerait autrement inaperçue jusqu'à l'exécution.

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/test_song_callbacks.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'pypl2mp3.services'`

- [ ] **Step 3: Créer le paquet services**

Créer `src/pypl2mp3/services/__init__.py`, fichier vide.

- [ ] **Step 4: Écrire l'adaptateur**

Créer `src/pypl2mp3/services/_song_callbacks.py` :

```python
#!/usr/bin/env python3
"""Projection d'un ProgressPort sur les callbacks de SongModel.

`SongModel.create_from_youtube` attend dix-huit callbacks distincts. Plutôt
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

    kwargs["pre_shazam_song"] = lambda _song: progress.stage_started(
        "shazam", "Shazam-ing audio track:"
    )
    kwargs["post_shazam_song"] = lambda song: progress.song_identified(
        song.shazam_artist,
        song.shazam_title,
        float(song.shazam_match_score),
    )

    return kwargs


def _percent_forwarder(progress: ProgressPort, stage: str):
    """Adapter la signature `(percentage, label)` attendue par song.py."""

    def forward(percentage: int, label: str = "") -> None:
        progress.stage_progress(stage, float(percentage))

    return forward
```

- [ ] **Step 5: Lancer les tests**

Run: `uv run pytest tests/test_song_callbacks.py -v`
Expected: 4 PASS

- [ ] **Step 6: Commit**

```bash
git add src/pypl2mp3/services/ tests/test_song_callbacks.py
git commit -m "feat: map the progress port onto SongModel callbacks"
```

---

### Task 5: Service list_playlists et façade CLI

Première migration complète, choisie parce qu'elle est la plus simple : listing local pur, sans interaction ni réseau. Elle fixe le motif que les commandes suivantes suivront.

**Files:**
- Create: `src/pypl2mp3/services/list_playlists.py`
- Modify: `src/pypl2mp3/commands/list_playlists.py` (réécriture complète, 152 lignes → façade d'affichage)
- Create: `tests/test_list_playlists_service.py`

**Interfaces:**
- Consumes: `pypl2mp3.libs.utils.natural_sort_key`, `pypl2mp3.libs.utils.get_song_id_from_filename`
- Produces:
  - `PlaylistSummary` — dataclass gelée : `path: Path`, `playlist_id: str`, `name: str`, `total_songs: int`, `junk_songs: int`, propriété `valid_songs: int`
  - `list_playlists(repository_path: Path) -> list[PlaylistSummary]`

- [ ] **Step 1: Écrire le test du service**

Créer `tests/test_list_playlists_service.py` :

```python
from pathlib import Path

from pypl2mp3.services.list_playlists import PlaylistSummary, list_playlists


def _make_playlist(repo: Path, name: str, songs: int, junks: int) -> Path:
    folder = repo / name
    folder.mkdir()
    for index in range(songs):
        (folder / f"ARTIST - Song {index} [vid{index:07d}].mp3").touch()
    for index in range(junks):
        (folder / f"ARTIST - Junk {index} [jnk{index:07d}] (JUNK).mp3").touch()
    return folder


def test_returns_empty_list_when_repository_has_no_playlist(tmp_path):
    assert list_playlists(tmp_path) == []


def test_summarizes_songs_and_junks(tmp_path):
    _make_playlist(tmp_path, "Owner - Alpha [PL0000000000000000000000000000001]", 3, 1)

    summaries = list_playlists(tmp_path)

    assert len(summaries) == 1
    summary = summaries[0]
    assert isinstance(summary, PlaylistSummary)
    assert summary.playlist_id == "PL0000000000000000000000000000001"
    assert summary.name == "Owner - Alpha"
    assert summary.total_songs == 4  # les junks comptent dans le total
    assert summary.junk_songs == 1
    assert summary.valid_songs == 3


def test_ignores_folders_without_a_bracketed_id(tmp_path):
    (tmp_path / "pas-une-playlist").mkdir()
    _make_playlist(tmp_path, "Owner - Alpha [PL0000000000000000000000000000001]", 1, 0)

    assert len(list_playlists(tmp_path)) == 1


def test_sorts_playlists_naturally(tmp_path):
    for label in ("Owner - B", "Owner - A", "Owner - C"):
        _make_playlist(tmp_path, f"{label} [PL{label[-1] * 32}]", 1, 0)

    names = [summary.name for summary in list_playlists(tmp_path)]

    assert names == ["Owner - A", "Owner - B", "Owner - C"]


def test_performs_no_network_call(tmp_path, monkeypatch):
    """Un listing local ne doit jamais toucher au réseau, même indirectement."""

    import socket

    def _forbidden(*args, **kwargs):
        raise AssertionError("un listing local a tenté un accès réseau")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    _make_playlist(tmp_path, "Owner - Alpha [PL0000000000000000000000000000001]", 1, 0)

    assert len(list_playlists(tmp_path)) == 1
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/test_list_playlists_service.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'pypl2mp3.services.list_playlists'`

- [ ] **Step 3: Écrire le service**

Créer `src/pypl2mp3/services/list_playlists.py` :

```python
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
```

- [ ] **Step 4: Lancer les tests du service**

Run: `uv run pytest tests/test_list_playlists_service.py -v`
Expected: 5 PASS

- [ ] **Step 5: Réduire la commande à une façade d'affichage**

Remplacer intégralement le contenu de `src/pypl2mp3/commands/list_playlists.py` par :

```python
#!/usr/bin/env python3
"""
PYPL2MP3: YouTube playlist MP3 converter and player,
with Shazam song identification and tagging capabilities.

This module displays the playlist inventory. All logic lives in
`pypl2mp3.services.list_playlists`; this file only formats output.

Copyright 2024 © Thierry Thiers <webcoder31@gmail.com>
License: CeCILL-C (http://www.cecill.info)
Repository: https://github.com/webcoder31/pypl2mp3
"""

# Python core modules
from pathlib import Path

# Third party packages
from colorama import Fore, Back, Style, init

# pypl2mp3 libs
from pypl2mp3.libs.utils import CountFormatter
from pypl2mp3.services.list_playlists import PlaylistSummary, list_playlists

# Automatically clear style on each print
init(autoreset=True)


def list_playlists_command(args: any) -> None:
    """
    Display all playlists in the repository with their song statistics.

    Args:
        args: Command line arguments containing the repository path (args.repo)
    """

    summaries = list_playlists(Path(args.repo))

    if not summaries:
        print(f"{Back.MAGENTA}{Style.BRIGHT}"
            + f" No playlists found in repository ")
        return

    print(f"\n{Back.YELLOW}{Style.BRIGHT}"
        + f" Found {len(summaries)} playlists in repository. ")

    _display_playlists_details(summaries)


def _display_playlists_details(summaries: list[PlaylistSummary]) -> None:
    """
    Display detailed information for each playlist.

    Args:
        summaries: Playlist summaries, already sorted by the service
    """

    count_formatter = CountFormatter(len(summaries))
    placeholder = count_formatter.placeholder()

    for index, summary in enumerate(summaries, 1):
        counter = count_formatter.format(index)

        # Display playlist information
        print(
            f"\n{counter}  "
            f"{Fore.LIGHTYELLOW_EX}{summary.name}"
        )
        print(
            f"{placeholder}  "
            f"{Fore.LIGHTBLUE_EX}{Style.BRIGHT}ID: {Style.NORMAL}"
            f"{summary.playlist_id}"
        )

        # Display playlist statistics
        print(
            f"{placeholder}  {Style.BRIGHT}"
            f"Number of well tagged songs .... {summary.valid_songs}"
        )
        print(
            f"{placeholder}  {Style.BRIGHT}"
            f"Number of junk songs ........... {summary.junk_songs}"
        )
        print(
            f"{placeholder}  {Fore.LIGHTGREEN_EX}{Style.BRIGHT}"
            f"Total .......................... {summary.total_songs}"
        )
```

La fonction est renommée `list_playlists_command` pour ne plus entrer en collision avec le service du même nom.

- [ ] **Step 6: Mettre à jour le lanceur dans main.py**

Dans `src/pypl2mp3/main.py`, remplacer le corps de `_run_list_playlists` (lignes 81-82) :

```python
    from pypl2mp3.commands.list_playlists import list_playlists_command
    list_playlists_command(args)
```

- [ ] **Step 7: Vérifier que le comportement observable est inchangé**

Run: `uv run pypl2mp3 playlists`
Expected: sortie strictement identique à celle d'avant la migration — mêmes playlists, mêmes compteurs, mêmes couleurs. C'est le critère d'acceptation de cette tâche.

- [ ] **Step 8: Lancer toute la suite**

Run: `uv run pytest -v`
Expected: tous les tests PASS (1 + 3 + 3 + 4 + 5 = 16).

- [ ] **Step 9: Commit**

```bash
git add src/pypl2mp3/services/list_playlists.py \
        src/pypl2mp3/commands/list_playlists.py \
        src/pypl2mp3/main.py \
        tests/test_list_playlists_service.py
git commit -m "refactor: extract the playlist inventory into a service"
```

---

### Task 6: Code de sortie non nul sur erreur fatale

`main()` capture l'exception, journalise en `CRITICAL`, puis retourne `None`. Le point d'entrée fait `sys.exit(main())`, donc `sys.exit(None)`, donc **code 0**. Un script appelant conclut au succès alors que la commande a échoué. Constaté le 2026-08-11.

**Files:**
- Modify: `src/pypl2mp3/main.py:682-701`
- Create: `tests/test_exit_code.py`

**Interfaces:**
- Consumes: rien.
- Produces: `main() -> int` — `0` en succès, `1` sur erreur fatale, `130` sur interruption clavier.

- [ ] **Step 1: Écrire le test**

Créer `tests/test_exit_code.py` :

```python
import subprocess
import sys


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pypl2mp3.main", *args],
        capture_output=True,
        text=True,
    )


def test_successful_command_exits_zero(tmp_path):
    result = _run("playlists", "-r", str(tmp_path))

    assert result.returncode == 0


def test_fatal_error_exits_non_zero(tmp_path):
    # Un identifiant de playlist invalide provoque une erreur fatale.
    result = _run("import", "not-a-playlist-id", "-r", str(tmp_path))

    assert result.returncode != 0, (
        "une erreur critique doit produire un code de sortie non nul"
    )
```

- [ ] **Step 2: Lancer le test pour vérifier qu'il échoue**

Run: `uv run pytest tests/test_exit_code.py -v`
Expected: `test_fatal_error_exits_non_zero` FAIL — le code retourné est `0`.

Si `test_successful_command_exits_zero` échoue aussi, c'est que `python -m pypl2mp3.main` n'est pas exécutable en l'état : ajouter alors `sys.exit(main())` sous le `if __name__ == "__main__":` de `main.py` avant de poursuivre.

- [ ] **Step 3: Faire renvoyer un code par main()**

Dans `src/pypl2mp3/main.py`, remplacer le bloc des lignes 682-701 par :

```python
    # Execute appropriate command runner
    exit_code = 0
    try:
        args.func(args)
    except KeyboardInterrupt:
        # Handle CTRL+C (SIGINT) to exit properly
        logger.info(
            f"User interrupted the \"{args.command}\" command execution"
        )
        exit_code = 130  # shell convention: 128 + SIGINT
    except Exception as error:
        # Catch any unhandled error
        print()
        logger.critical(
            error, 
            f"The \"{args.command}\" command failed due to a critical error"
        )
        exit_code = 1

    # Log end of program execution
    end_time = (datetime.datetime.now()).time().strftime('%H:%M:%S')
    logger.info("PYPL2MP3 finished at " + end_time)
    print(f"\n{Fore.LIGHTGREEN_EX}PYPL2MP3 FINISHED AT {end_time}\n")

    return exit_code
```

- [ ] **Step 4: Propager le code au point d'entrée**

Remplacer la fin de `src/pypl2mp3/main.py` :

```python
# Main entry point
# This allows the module to be run as a script or imported
# without executing the main function, to be used in other modules
if __name__ == "__main__":
    sys.exit(main())
```

Vérifier que `import sys` figure bien dans les imports du module ; l'ajouter sinon.

- [ ] **Step 5: Lancer les tests**

Run: `uv run pytest tests/test_exit_code.py -v`
Expected: 2 PASS

- [ ] **Step 6: Vérifier le comportement réel**

```bash
uv run pypl2mp3 playlists ; echo "code = $?"
```
Expected: `code = 0`

```bash
uv run pypl2mp3 import not-a-playlist-id ; echo "code = $?"
```
Expected: `code = 1`

- [ ] **Step 7: Lancer toute la suite**

Run: `uv run pytest -v`
Expected: 18 PASS

- [ ] **Step 8: Commit**

```bash
git add src/pypl2mp3/main.py tests/test_exit_code.py
git commit -m "fix: return a non-zero exit code when a command fails"
```

---

## Ce que ce plan ne fait pas

Bornes explicites, pour éviter la dérive :

- **Aucune modification de `libs/`.** Si une tâche semble l'exiger, c'est le signe d'une erreur de conception : s'arrêter et en discuter.
- **Aucun code web.** FastAPI, WebSocket et registre de jobs appartiennent au plan 2.
- **Sept commandes restent non migrées** : `import`, `fix`, `songs`, `junks`, `junkize`, `videos`, `play`. Elles conservent leur forme actuelle et continuent de fonctionner. Le plan 3 les traitera, en suivant le motif fixé par la tâche 5.
- **`fix_junks.py` (733 lignes, 115 d'affichage) n'est pas touché.** C'est le module le plus intriqué ; il se traitera en dernier, une fois le motif rodé sur les commandes simples.
