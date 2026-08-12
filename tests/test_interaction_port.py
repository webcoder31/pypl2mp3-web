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
