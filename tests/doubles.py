"""Test doubles for the ports, to test services without terminal or network."""


class FakeInteraction:
    """Answers from a predefined script and records the questions asked."""

    def __init__(self, answers: list[str]):
        self._answers = list(answers)
        self.asked: list[tuple[str, list[str]]] = []

    async def ask(self, question: str, options: list[str]) -> str:
        self.asked.append((question, list(options)))
        if not self._answers:
            raise AssertionError(
                f"No scripted answer left for: {question!r}"
            )
        return self._answers.pop(0)


class FakeProgress:
    """Records the events received, without displaying anything."""

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

    def item_listed(self, item_id: str, label: str) -> None:
        self.events.append(("item_listed", item_id, label))

    def item_started(self, item_id: str, label: str) -> None:
        self.events.append(("item_started", item_id, label))

    def item_done(self, item_id: str, label: str = "") -> None:
        self.events.append(("item_done", item_id, label))

    def item_failed(self, item_id: str, reason: str, issue: str) -> None:
        self.events.append(("item_failed", item_id, reason, issue))
