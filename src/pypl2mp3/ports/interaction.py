#!/usr/bin/env python3
"""Contract for interaction between the orchestration and the user.

In a terminal, asking a question blocks on input. On a server, that is
forbidden. This port is the only boundary where the two worlds differ:
services consume it without knowing who they are talking to.
"""

from typing import Protocol, runtime_checkable

from pypl2mp3.libs.utils import prompt_user


class InteractionAbandoned(Exception):
    """The other party disappeared before answering.

    A service that receives this exception must treat the operation as
    abandoned, never as a crash.
    """


@runtime_checkable
class InteractionPort(Protocol):
    """Ask a question, get back an answer from a set of options."""

    async def ask(self, question: str, options: list[str]) -> str:
        ...


class ConsoleInteraction:
    """Terminal implementation: delegates to the existing `input()`.

    Blocking is acceptable here: the CLI has nothing else to do in the
    meantime. The behaviour is identical to what it was before the port was
    introduced.
    """

    async def ask(self, question: str, options: list[str]) -> str:
        return prompt_user(question, options)
