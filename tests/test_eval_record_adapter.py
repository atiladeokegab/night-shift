import pytest

from core.stats import stats
from core.store import Store
from eval.record_adapter import main


def test_records_the_try_models_result_and_stats_shows_it(tmp_path):
    env = {"STORE_DIR": str(tmp_path)}
    main(["--status", "ready", "--kept", "31", "--agree", "23", "--total", "25"], env)
    adapter = stats(Store(tmp_path))["adapter"]
    assert (adapter["status"], adapter["kept"], adapter["agree"], adapter["total"]) == (
        "ready",
        31,
        23,
        25,
    )
    assert Store(tmp_path).all("adapter")[-1]["created_at"]


def test_training_needs_no_counts(tmp_path):
    main(["--status", "training"], {"STORE_DIR": str(tmp_path)})
    assert stats(Store(tmp_path))["adapter"]["status"] == "training"


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
            "--score",
            "82",
            "--passed",
        ],
        env,
    )
    main(
        ["--task", "where_are_we", "--status", "ready", "--version", "2", "--score", "55.8"]
        + ["--target", "95", "--failed", "--kept", "0"],
        env,
    )
    s = stats(store)
    line_check = s["adapters"]["line_check"]
    assert line_check["recorded_at"] == store.all("adapter")[-2]["created_at"]
    assert {k: v for k, v in line_check.items() if k != "recorded_at"} == {
        "status": "ready",
        "version": 1,
        "score": 82.0,
        "target": None,
        "passed": True,
        "kept": None,  # the latest record didn't say: not carried over from the one before
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
    assert (s["adapter"]["status"], s["adapter"]["kept"]) == ("training", 25)


def test_a_task_with_no_record_is_absent_not_guessed(tmp_path):
    main(["--task", "line_check", "--status", "training"], {"STORE_DIR": str(tmp_path)})
    s = stats(Store(tmp_path))
    assert list(s["adapters"]) == ["line_check"]
    assert s["adapter"]["status"] == "not_trained"  # no commentary record yet
    assert s["adapters"]["line_check"]["passed"] is None


@pytest.mark.parametrize(
    "args",
    [
        ["--task", "summary", "--status", "ready"],
        ["--status", "ready", "--version", "0"],
        ["--status", "ready", "--score", "101"],
        ["--status", "ready", "--score", "-1"],
        ["--status", "ready", "--passed", "--failed"],
        ["--status", "ready", "--target", "101"],
    ],
)
def test_bad_task_results_are_refused_and_nothing_is_written(tmp_path, args):
    with pytest.raises(SystemExit):
        main(args, {"STORE_DIR": str(tmp_path)})
    assert Store(tmp_path).all("adapter") == []
