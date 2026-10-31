import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "worker_pool_eval", Path(__file__).resolve().parents[1] / "scripts/eval_worker_pool.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_two_lanes_only_help_when_account_accepts_parallel_work():
    independent = evaluation.evaluate()["scenarios"]["independent_generation"]
    serialized = evaluation.evaluate()["scenarios"]["account_serialized"]
    assert independent[1]["modeled_last_event_seconds"] < independent[0]["modeled_last_event_seconds"]
    assert serialized[1]["modeled_last_event_seconds"] == serialized[0]["modeled_last_event_seconds"]


def test_local_measurement_uses_real_queue_without_browser():
    report = evaluation.measure_queue(rounds=2)
    assert report["distinct_jobs"] == 12
    assert report["claim_races_passed"] == 2
    assert report["admission"]["p95_ms"] >= 0


def test_each_lane_is_exclusive_and_uncertainty_stops_new_dispatch():
    for case in evaluation.evaluate()["scenarios"].values():
        for result in case:
            free = {}
            for event in result["events"]:
                assert event["start"] >= free.get(event["worker"], 0)
                free[event["worker"]] = event["end"]
    uncertain = evaluation.evaluate()["scenarios"]["uncertain_submission"]
    assert uncertain[0]["dispatched"] == 2
    assert uncertain[0]["completed"] == 1
    assert uncertain[1]["dispatched"] == 4
    assert uncertain[1]["completed"] == 2
    assert sum(e["state"] == "in_flight_at_halt" for e in uncertain[1]["events"]) == 1
