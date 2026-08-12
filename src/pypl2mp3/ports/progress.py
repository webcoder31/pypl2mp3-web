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
