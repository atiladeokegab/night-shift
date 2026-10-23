import json
from pathlib import Path

import pytest

from agent.commentator import FakeProvider
from core.store import Store
from eval import agreement
from eval.agreement import compare, disagreement, main

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"
GOAL = {
    "idx": 5,
    "clock": "22:24",
    "players": {"shooter": "Lionel Messi"},
    "score": {"home": 1, "away": 0},
}


def match(name: str):
    data = json.loads((SAMPLE / name).read_text(encoding="utf-8"))
    return data["header"], data["moments"]


def line(text: str, first_word_ms: float = 400.0) -> dict:
    return {"text": text, "first_word_ms": first_word_ms, "latency_ms": 700}


class Adapter(FakeProvider):
    """The fake adapter: the big model's fake, but its line for one moment is replaced."""

    def __init__(self, bad: dict[str, str]):
        super().__init__()
        self.bad = bad  # the message's Moment field -> the line said instead

    def call(self, request: dict) -> dict:
        reply = super().call(request)
        message = request["messages"][0]["content"]
        for moment, said in self.bad.items():
            if f"Moment: {moment}\n" in message and reply["content"][0]["type"] == "text":
                reply["content"] = [{"type": "text", "text": said}]
        return reply


CAST = {
    "Lionel Messi",
    "Kylian Mbappé",
    "Raphaël Varane",
    "Emiliano Martínez",
    "Cristian Romero",
    "Mohammad Rizwan",
    "Arshdeep Singh",
    "B Kumar",
    "V Kohli",
    "Chris Smith",
    "Alex Smith",
    "Lewis Hamilton",
    "Max Verstappen",
    "Michael Jordan",
}


@pytest.mark.parametrize(
    "big, adapter",
    [
        ("Lionel Messi scores! 1-0!", "Messi scores, 1-0 to Argentina!"),
        (
            "Rizwan is out, caught by Kumar! Wicket!",
            "Caught! Mohammad Rizwan is out, Kumar takes it, wicket!",
        ),
        ("Lewis Hamilton wins at Silverstone by 1.5 seconds!", "Hamilton wins by 1.5 seconds!"),
        ("Rizwan is not out!", "Not out! Mohammad Rizwan survives!"),
        ("Jordan doesn't score, 86-87!", "Michael Jordan can't... no, he doesn't score! 86-87!"),
    ],
)
def test_the_same_facts_in_other_words_agree(big, adapter):
    assert disagreement(GOAL, line(big), line(adapter), CAST) is None


# Prometheus's after-merge finding on #75: each pair contradicts itself, and each once scored as
# agreement. Score order, outcome, negation, who did what, and which of two Smiths.
CONTRADICTIONS = [
    ("Messi! 1-0 Argentina!", "Messi! 0-1 Argentina!"),
    ("Bulls lead 87-86!", "Bulls lead 86-87!"),
    ("Kohli hits 6 off 3 balls, six!", "Kohli hits 3 off 6 balls, six!"),
    ("Hamilton wins by 1.5 seconds!", "Hamilton wins by 15 seconds!"),
    ("Messi scores! 1-0!", "Messi misses! 1-0!"),
    ("Messi scores!", "Messi's shot is saved!"),
    ("Messi scores!", "Messi hits the post!"),
    ("Rizwan is out!", "Rizwan is not out!"),
    ("Jordan scores!", "Jordan doesn't score!"),
    ("Goal! Varane!", "Own goal! Varane!"),
    ("Six for Kohli!", "Four for Kohli!"),
    ("Wicket! Rizwan caught!", "Wicket! Rizwan bowled!"),
    ("No-ball from Arshdeep!", "Wide from Arshdeep!"),
    ("Yellow card for Romero!", "Red card for Romero!"),
    ("Arshdeep Singh to Mohammad Rizwan, out!", "Mohammad Rizwan to Arshdeep Singh, out!"),
    ("Hamilton overtakes Verstappen!", "Verstappen overtakes Hamilton!"),
    ("Martínez saves from Mbappé!", "Mbappé saves from Martínez!"),
    ("Chris Smith takes the wicket!", "Alex Smith takes the wicket!"),
    ("Smith takes the wicket!", "Smith takes the wicket!"),
    ("Hamilton pits!", "Hamilton wins!"),
]


@pytest.mark.parametrize("big, adapter", CONTRADICTIONS)
def test_contradictory_lines_disagree(big, adapter):
    assert disagreement(GOAL, line(big), line(adapter), CAST) is not None


def test_lines_with_no_outcome_to_compare_disagree():
    why = disagreement(GOAL, line("What a moment for Messi!"), line("What a moment for Messi!"))
    assert why == "no outcome to compare"


@pytest.mark.parametrize(
    "adapter, why",
    [
        (line("Di María scores, 1-0!"), "names [], big model ['Lionel Messi']"),
        (line("Messi scores, 2-0!"), "numbers ['2', '0'], big model ['1', '0']"),
        (line("Messi misses, 1-0!"), "outcome ['miss'], big model ['goal']"),
        (line("   "), "adapter empty"),
        (None, "adapter skipped"),
        (line("Messi scores, 1-0!", first_word_ms=2400), "adapter late (2400 ms)"),
    ],
)
def test_a_wrong_empty_skipped_or_late_adapter_line_disagrees(adapter, why):
    assert disagreement(GOAL, line("Messi scores, 1-0!"), adapter) == why


def test_a_skipped_or_late_big_model_line_disagrees_too():
    assert disagreement(GOAL, None, line("Messi! 1-0!")) == "big model skipped"
    late = {"text": "Messi! 1-0!", "first_word_ms": None, "latency_ms": 1900}
    assert disagreement(GOAL, late, line("Messi! 1-0!")) == "big model late (1900 ms)"


def test_seeded_with_one_known_bad_line_it_reports_one_disagreement():
    cricket = match("cricket-1298150.json")
    # Rizwan caught off Arshdeep at 3.6; the adapter has the wrong batsman out
    bad = Adapter({"innings 1, 3.6": "Babar Azam is out!"})
    report = compare([cricket], FakeProvider(), bad, per_match=4)
    assert (report["agree"], report["total"]) == (3, 4)
    assert report["disagreements"] == [
        {"match_id": "1298150", "idx": 3, "why": "names ['Babar Azam'], big model []"}
    ]
    assert compare([cricket], FakeProvider(), Adapter({}), per_match=4)["agree"] == 4


def test_an_untrained_adapter_is_not_tested_and_nothing_is_called(tmp_path, monkeypatch, capsys):
    def no_calls(*_):
        raise AssertionError("an untrained adapter must not be called")

    monkeypatch.setattr(agreement, "held_out_matches", no_calls)
    report = main(
        [], {"STORE_DIR": str(tmp_path), "MUBIT_API_KEY": "k", "MUBIT_ADAPTER_MODEL": "m"}
    )
    assert report == {
        "tested": False,
        "reason": "the adapter isn't trained (status not_trained, kept not recorded of 25)",
    }
    assert capsys.readouterr().out.startswith("not tested: the adapter isn't trained")


@pytest.mark.parametrize(
    "env, reason",
    [
        ({}, "MUBIT_ADAPTER_MODEL is not set: the app has no way to call the adapter"),
        ({"MUBIT_ADAPTER_MODEL": "m"}, "MUBIT_API_KEY is not set"),
    ],
)
def test_a_ready_adapter_the_app_cannot_call_is_not_tested(tmp_path, env, reason):
    Store(tmp_path).append("adapter", {"status": "ready", "kept": 31})
    assert main([], {"STORE_DIR": str(tmp_path), **env}) == {"tested": False, "reason": reason}


def test_a_ready_adapter_is_compared_on_held_out_matches_with_recording_off(tmp_path, monkeypatch):
    Store(tmp_path).append("adapter", {"status": "ready", "kept": 31})
    made, models = [], []

    class Provider(FakeProvider):
        def __init__(self, key, record=True):
            super().__init__()
            made.append(record)

        def call(self, request):
            models.append(request["model"])
            return super().call(request)

    monkeypatch.setattr(agreement, "MubitProvider", Provider)
    monkeypatch.setattr(
        agreement, "held_out_matches", lambda f, c: [match("football-3906390.json")]
    )
    env = {"STORE_DIR": str(tmp_path), "MUBIT_API_KEY": "k", "MUBIT_ADAPTER_MODEL": "adapter-v1"}
    report = main(["--per-match", "3"], env)
    assert (report["tested"], report["agree"], report["total"]) == (True, 3, 3)
    assert made == [False, False]  # held-out moments never train the task
    assert "adapter-v1" in models and "claude-haiku-4-5" in models
