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
