"""How well the check works (#219): the eval on the labelled prod lines goes red when it breaks."""

from eval import checker_eval

# Today's checker on the 300 labels: 15 of 15 flags right, all 15 wrong lines caught. Their misses
# were targeted (#293), so the held-out labels are the honest measure.
MIN_PRECISION, MIN_RECALL = 1.0, 1.0
# On the 300 held-out labels: 1 of 3 flags right, 1 of 6 wrong lines caught.
HELDOUT_PRECISION, HELDOUT_RECALL = 1 / 3, 1 / 6


def holds(out: dict, precision: float = MIN_PRECISION, recall: float = MIN_RECALL) -> bool:
    s = out["overall"]
    return (s["precision"] or 0) >= precision and (s["recall"] or 0) >= recall


def test_the_labels_are_the_stratified_sample_and_were_labelled():
    labels = checker_eval.load()
    assert len(labels) == checker_eval.SIZE
    assert {ln["label"] for ln in labels} == {"right", "wrong"}
    assert all(ln["why"] for ln in labels if ln["label"] == "wrong")
    per_match = {}
    for ln in labels:
        per_match[ln["match_id"]] = per_match.get(ln["match_id"], 0) + 1
    # every labelled match is bundled; one bundled after labelling (#246) has no prod lines yet
    assert set(per_match) <= set(checker_eval.bundled()) and len(per_match) >= 7
    assert min(per_match.values()) >= min(checker_eval.FLOOR, 25)  # F1 has 25 distinct lines


def test_todays_checker_holds_its_precision_and_recall():
    assert holds(checker_eval.evaluate(checker_eval.load()))


def test_the_held_out_labels_are_new_lines_and_were_labelled():
    labels = checker_eval.load(checker_eval.HELDOUT)
    assert len(labels) == checker_eval.SIZE
    assert {ln["label"] for ln in labels} == {"right", "wrong"}
    assert all(ln["why"] for ln in labels if ln["label"] == "wrong")
    keys = {(ln["match_id"], ln["moment_idx"], ln["text"]) for ln in labels}
    assert len(keys) == len(labels) and not keys & checker_eval.labelled()


def test_todays_checker_holds_its_held_out_precision_and_recall():
    out = checker_eval.evaluate(checker_eval.load(checker_eval.HELDOUT))
    assert holds(out, HELDOUT_PRECISION, HELDOUT_RECALL)


def test_the_eval_goes_red_when_the_checker_is_broken():
    labels = checker_eval.load()
    silent = checker_eval.evaluate(labels, check=lambda ln, cache: [])
    assert silent["overall"]["recall"] == 0 and not holds(silent)
    jumpy = checker_eval.evaluate(labels, check=lambda ln, cache: ["the score is wrong"])
    assert jumpy["overall"]["precision"] < 0.1 and not holds(jumpy)

    def blind(ln, cache):  # a checker that never reads the score
        return [r for r in checker_eval.verdict(ln, cache) if "score" not in r and "lead" not in r]

    assert not holds(checker_eval.evaluate(labels, check=blind))


def test_omissions_are_not_counted_as_wrong():
    reasons = ["the milestone is unsaid: 41 points", "the score is 65-75, not 58-75"]
    assert checker_eval.factual(reasons) == reasons[1:]
