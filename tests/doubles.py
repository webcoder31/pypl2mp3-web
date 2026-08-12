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
