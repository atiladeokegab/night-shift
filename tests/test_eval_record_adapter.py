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
