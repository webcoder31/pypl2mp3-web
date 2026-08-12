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
