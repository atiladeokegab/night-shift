"""The booth's pair in a quiet stretch: no meta prefix spoken, no question asked twice, no season
question without a season fact, and nobody profiled who has no data."""

from core import insight
from core.insight import Gaps, unprefix
from core.store import Store
from data.matches import load_moments


def test_a_spoken_meta_prefix_is_stripped():
    assert unprefix("Julian, answering: he has nine goals.") == "he has nine goals."
    assert unprefix("Answering: nine goals.") == "nine goals."
    assert unprefix("Jim, answering - nine goals.") == "nine goals."
    assert unprefix("He is answering the call well.") == "He is answering the call well."


def gaps(tmp_path):
    return Gaps("3754092", Store(tmp_path))


def test_a_question_the_lead_asked_lately_is_not_asked_again(tmp_path):
    g = gaps(tmp_path)
    ask = "What's he done this season, Julian?"
    assert g.re_asked(ask, {"season": True}) is None
    g.asks += insight.questions(ask)
    assert g.re_asked("What has he done this season, Julian?", {"season": True})
    assert g.re_asked("Who takes the corner?", {"season": True}) is None
    g.asks += [{f"q{i}"} for i in range(insight.ASKS)]  # asked long ago: fair again
    assert g.re_asked(ask, {"season": True}) is None


def test_no_season_question_without_a_season_fact(tmp_path):
    g = gaps(tmp_path)
    assert g.re_asked("What's he done this season, Julian?", {}) == "season"
    assert g.re_asked("What's he done this season, Julian?", {"season": False}) == "season"
    assert g.re_asked("Was that a good first touch?", {}) is None


def test_the_season_flag_follows_the_fact():
    assert insight.HAS_SEASON.search("Hazard this season before tonight: 9 goals from 40 shots")
    assert not insight.HAS_SEASON.search("Hazard tonight: Shot x2")


def test_a_player_with_no_profile_is_never_the_stretchs_subject(tmp_path, monkeypatch):
    g = gaps(tmp_path)
    past = load_moments("3754092")[:10]
    pack = {"sport": "football", "players": {"Pape Sow": {}, "Eden Hazard": {}}}
    monkeypatch.setattr(g, "pack", lambda m: pack)
    monkeypatch.setattr(insight, "_profiles", lambda p, pa: ["Eden Hazard this season: 9 goals."])
    monkeypatch.setattr(
        insight,
        "_tallies",
        lambda p, pa: ["Pape Sow tonight: Shot x2", "Eden Hazard tonight: Goal x1"],
    )
    monkeypatch.setattr(
        insight, "_odds", lambda p, pa: ["Chance Pape Sow scores the next goal: 9%."]
    )
    got = g.about_one_player(past, True)
    assert got and got[1].startswith("Eden Hazard")
    assert g.focus == "Eden Hazard"


def test_a_line_that_admits_missing_data_is_caught():
    for text in (
        "Jim, I only have tonight: two shots.",
        "Career numbers I don't have, Jim, but he looks sharp.",
        "Nothing on tonight yet, Jim.",
    ):
        assert insight.admits(text), text
    assert not insight.admits("Nine goals from forty shots this season before tonight.")


def test_a_question_about_tonight_needs_a_tonight_fact(tmp_path):
    g = gaps(tmp_path)
    ask = "What's he done tonight, Julian?"
    assert g.re_asked(ask, {"season": True}) == "tonight"
    assert g.re_asked(ask, {"tonight": True}) is None


def test_a_stretch_takes_at_most_a_few_turns():
    assert insight.STRETCH_TURNS <= 4


def test_no_quiet_stretch_runs_past_its_turn_cap(tmp_path):
    from tests.test_insight import KOBE, replay

    lines, _ = replay(KOBE, Store(tmp_path))
    turns: dict[int, int] = {}
    for ln in lines:
        gap = ln.get("insight") or ln.get("reply")
        if gap:
            turns[gap["after_idx"]] = turns.get(gap["after_idx"], 0) + 1
    assert turns and max(turns.values()) <= insight.STRETCH_TURNS


def test_a_stored_line_that_admits_missing_data_is_made_again_not_a_crash(tmp_path):
    g = Gaps("0020500591", Store(tmp_path))
    past = load_moments("0020500591")[:10]
    m = past[-1]
    stored = {
        "line_id": "x",
        "text": "Jim, I only have tonight: twenty of thirty-one from the floor.",
        "insight": {
            "kind": "tally",
            "detail": "d",
            "heard": "",
            "by": "lead",
            "v": insight.VERSION,
        },
    }
    g.cached[(m["idx"], 0, False)] = stored
    made = []

    def commentate(stat, history):
        made.append(stat)
        return {"line_id": "y", "text": "Kobe has scored often tonight.", "usage": {}}

    g.line(past, 0, 0.0, commentate, end=600.0, orient=False)
    assert made  # made again, not an AttributeError
