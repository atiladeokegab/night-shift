import pytest

from core.stats import stats
from core.store import Store
from eval.record_adapter import main


def test_records_the_try_models_result_and_stats_shows_it(tmp_path):
    env = {"STORE_DIR": str(tmp_path)}
    main(["--status", "ready", "--kept", "31", "--agree", "23", "--total", "25"], env)
    adapter = stats(Store(tmp_path))["adapter"]
    assert (adapter["state"], adapter["kept"], adapter["agree"], adapter["total"]) == (
        "collecting",  # ready, but no version or verdict recorded
        31,
        23,
        25,
    )
    assert Store(tmp_path).all("adapter")[-1]["created_at"]


def test_training_needs_no_counts(tmp_path):
    main(["--status", "training"], {"STORE_DIR": str(tmp_path)})
    assert stats(Store(tmp_path))["adapter"]["state"] == "collecting"


@pytest.mark.parametrize(
    "args",
    [
        ["--status", "done"],
        ["--status", "ready", "--agree", "23"],
        ["--status", "ready", "--agree", "26", "--total", "25"],
        ["--status", "ready", "--agree", "-1", "--total", "25"],
        ["--status", "training", "--kept", "-3"],
    ],
)
def test_bad_results_are_refused_and_nothing_is_written(tmp_path, args):
    with pytest.raises(SystemExit):
        main(args, {"STORE_DIR": str(tmp_path)})
    assert Store(tmp_path).all("adapter") == []


def test_each_task_keeps_its_own_latest_record_and_adapter_stays_commentary(tmp_path):
    env = {"STORE_DIR": str(tmp_path)}
    store = Store(tmp_path)
    store.append("adapter", {"status": "training", "kept": 25})  # before tasks: commentary's
    main(["--task", "line_check", "--status", "training", "--kept", "40"], env)
    main(
        [
            "--task",
            "line_check",
            "--status",
            "ready",
            "--version",
            "1",
            "--version-id",
            "lc_1",
            "--score",
            "82",
            "--passed",
        ],
        env,
    )
    main(
        ["--task", "where_are_we", "--status", "ready", "--version", "2", "--version-id", "w_2"]
        + ["--score", "55.8", "--target", "95", "--failed", "--kept", "0"],
        env,
    )
    s = stats(store)
    line_check = s["adapters"]["line_check"]
    assert line_check["recorded_at"] == store.all("adapter")[-2]["created_at"]
    assert {k: v for k, v in line_check.items() if k not in ("recorded_at", "versions")} == {
        "state": "passed",  # Mubit's gate was recorded as passed
        "version": 1,
        "version_id": "lc_1",
        "score": 82.0,
        "target": None,
        "passed": True,
        "kept": None,  # the latest record didn't say: not carried over from the one before
        "source": "Mubit console",
    }
    where = s["adapters"]["where_are_we"]
    assert (where["version"], where["score"], where["target"], where["passed"]) == (
        2,
        55.8,
        95.0,
        False,
    )
    assert where["kept"] == 0  # the console's kept count, recorded as 0: not None, not requests
    assert s["adapters"]["commentary"]["kept"] == 25
    assert (s["adapter"]["state"], s["adapter"]["kept"]) == ("collecting", 25)


def test_a_task_with_no_record_is_absent_not_guessed(tmp_path):
    main(["--task", "line_check", "--status", "training"], {"STORE_DIR": str(tmp_path)})
    s = stats(Store(tmp_path))
    assert list(s["adapters"]) == ["line_check"]
    # no commentary record yet: no as-of time
    assert s["adapter"]["summary"] == "Collecting: no adapter version recorded yet."
    assert s["adapters"]["line_check"]["passed"] is None


@pytest.mark.parametrize(
    "args",
    [
        ["--task", "summary", "--status", "ready"],
        ["--status", "ready", "--version", "0"],
        ["--status", "ready", "--score", "101"],
        ["--status", "ready", "--score", "-1"],
        ["--status", "ready", "--passed", "--failed"],
        ["--status", "ready", "--passed"],  # a pass names its version
        ["--status", "ready", "--target", "101"],
        # a verdict needs the version it is about, by number and console ID (#321 review)
        ["--task", "score_check", "--status", "ready", "--passed"],
        ["--task", "score_check", "--status", "ready", "--version", "1", "--passed"],
        ["--task", "score_check", "--status", "ready", "--version-id", "ad_1", "--failed"],
        ["--task", "score_check", "--status", "ready", "--version", "1", "--version-id", ""]
        + ["--passed"],
    ],
)
def test_bad_task_results_are_refused_and_nothing_is_written(tmp_path, args):
    with pytest.raises(SystemExit):
        main(args, {"STORE_DIR": str(tmp_path)})
    assert Store(tmp_path).all("adapter") == []


def test_each_version_stays_on_record_with_its_id_and_source(tmp_path):
    """v1 then v2 of Score check (#321): both shown, each as its latest record says it."""
    env = {"STORE_DIR": str(tmp_path)}
    v1 = ["--task", "score_check", "--status", "ready", "--version", "1", "--version-id", "ad_1"]
    main([*v1, "--score", "88", "--target", "95", "--failed"], env)
    main([*v1, "--score", "88.5", "--target", "95", "--failed"], env)  # a re-read replaces it
    main(
        ["--task", "score_check", "--status", "ready", "--version", "2", "--version-id", "ad_2"]
        + ["--score", "96", "--target", "95", "--passed", "--source", "Mubit console, History"],
        env,
    )
    sc = stats(Store(tmp_path))["adapters"]["score_check"]
    assert (sc["version"], sc["version_id"], sc["source"]) == (2, "ad_2", "Mubit console, History")
    v = [(x["version"], x["version_id"], x["score"], x["passed"]) for x in sc["versions"]]
    assert v == [(1, "ad_1", 88.5, False), (2, "ad_2", 96.0, True)]


def test_a_pass_with_no_version_is_never_shown_as_passed(tmp_path):
    """A record from before the recorder's check (#321 review): no version, so no pass to show."""
    store = Store(tmp_path)
    store.append("adapter", {"task": "score_check", "status": "ready", "passed": True})
    sc = stats(store)["adapters"]["score_check"]
    assert (sc["state"], sc["passed"], sc["versions"]) == ("collecting", None, [])
