"""Offline scheduling model, NOT a Chrome/ChatGPT throughput benchmark.

Run: python scripts/eval_worker_pool.py
Times are hypothetical service seconds. No requests or quota are consumed.
"""
import heapq
import json
import statistics


def measure_queue(rounds=30):
    """Measure actual local admission/claim paths; never execute browser work."""
    import tempfile
    import threading
    import time
    import uuid
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from chatgpt_api.extension_bridge import ExtensionQueue

    admission_ms = []
    claim_ms = []
    for _ in range(rounds):
        with tempfile.TemporaryDirectory(prefix="gpt-queue-eval-") as directory:
            queue = ExtensionQueue(Path(directory), "eval")
            client = str(uuid.uuid4())
            queue.pair(client, "eval", "Create image")
            gate = threading.Barrier(6)

            def submit(index):
                gate.wait()
                started = time.perf_counter()
                receipt = queue.submit("Synthetic agent %d" % index, "Create image")
                return receipt["job_id"], (time.perf_counter() - started) * 1000

            with ThreadPoolExecutor(max_workers=6) as pool:
                submitted = list(pool.map(submit, range(6)))
            assert len({job_id for job_id, _ in submitted}) == 6
            admission_ms.extend(elapsed for _, elapsed in submitted)
            expected = next(iter(queue.jobs))
            gate = threading.Barrier(6)

            def claim(_):
                gate.wait()
                started = time.perf_counter()
                receipt = queue.claim(client)
                return receipt, (time.perf_counter() - started) * 1000

            with ThreadPoolExecutor(max_workers=6) as pool:
                claims = list(pool.map(claim, range(6)))
            winners = [receipt for receipt, _ in claims if receipt]
            assert len(winners) == 1 and winners[0]["job_id"] == expected
            claim_ms.extend(elapsed for _, elapsed in claims)

    def summary(values):
        return {"p50_ms": round(statistics.median(values), 3),
                "p95_ms": round(sorted(values)[int((len(values) - 1) * .95)], 3)}

    return {"evidence": "actual local ExtensionQueue only; no HTTP/browser/generation",
            "rounds": rounds, "simultaneous_callers": 6, "distinct_jobs": rounds * 6,
            "claim_races_passed": rounds, "admission": summary(admission_ms),
            "claim": summary(claim_ms)}


def model(workers, *, serialized_account=False, cooldown=0, uncertain_job=None):
    durations = [40, 90, 30, 120, 60, 50]
    available = [(0, lane) for lane in range(workers)]
    account_available = 0
    completions = []
    events = []
    for index, duration in enumerate(durations):
        free, lane = heapq.heappop(available)
        start = max(free, account_available)
        end = start + duration
        events.append({"job": index, "worker": lane, "start": start, "end": end,
                       "state": "uncertain" if index == uncertain_job else "complete"})
        completions.append(end)
        if serialized_account:
            account_available = end + cooldown
        elif cooldown:
            account_available = start + cooldown
        heapq.heappush(available, (end, lane))
    if uncertain_job is not None:
        detected_at = events[uncertain_job]["end"]
        # Already-running work cannot be unsent. Stop only after detection.
        events = [event for event in events if event["start"] < detected_at]
        for event in events:
            if event["end"] > detected_at:
                event["state"] = "in_flight_at_halt"
        completions = [event["end"] for event in events
                       if event["state"] == "complete"]
    return {"workers": workers, "completed": len(completions), "dispatched": len(events),
            "modeled_last_event_seconds": max(e["end"] for e in events),
            "modeled_mean_completion_seconds": round(statistics.mean(completions), 2),
            "events": events}


def evaluate():
    scenarios = {"independent_generation": {}, "account_serialized": {"serialized_account": True},
                 "account_start_cooldown_90s": {"cooldown": 90},
                 "uncertain_submission": {"uncertain_job": 1}}
    return {"evidence": "hypothetical scheduling model; not measured provider performance",
            "service_seconds": [40, 90, 30, 120, 60, 50],
            "scenarios": {name: [model(n, **options) for n in (1, 2)]
                          for name, options in scenarios.items()}}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measure-queue", action="store_true")
    args = parser.parse_args()
    print(json.dumps(measure_queue() if args.measure_queue else evaluate(), indent=2))
