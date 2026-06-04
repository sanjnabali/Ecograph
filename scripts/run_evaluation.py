"""
scripts/run_evaluation.py

Run all EcoGraph benchmarks and print a summary report.

Benchmarks:
    retrieval   - GraphRAG Precision@5 (target > 85%)
    plume       - CNN mean IoU (target > 80%)
    e2e         - End-to-end agent scenarios

Usage:
    python scripts/run_evaluation.py               # all benchmarks
    python scripts/run_evaluation.py --only retrieval
    python scripts/run_evaluation.py --only plume
    python scripts/run_evaluation.py --only e2e
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_evaluation")


def run_retrieval() -> dict:
    from ecograph.evaluation.retrieval_precision import run_retrieval_benchmark
    metrics = run_retrieval_benchmark()
    return {
        "benchmark": "GraphRAG Retrieval",
        "precision_at_5": f"{metrics.precision_at_k:.3f}",
        "ndcg_at_5": f"{metrics.ndcg_at_k:.3f}",
        "n_queries": metrics.n_queries,
        "target": "Precision@5 > 0.85",
        "passed": metrics.target_met,
    }


def run_plume() -> dict:
    from ecograph.evaluation.plume_detection_iou import run_plume_benchmark
    metrics = run_plume_benchmark()
    return {
        "benchmark": "Plume Detection",
        "mean_iou": f"{metrics.mean_iou:.3f}",
        "mean_dice": f"{metrics.mean_dice:.3f}",
        "n_tiles": metrics.n_tiles,
        "target": "mean IoU > 0.80",
        "passed": metrics.target_met,
    }


def run_e2e() -> dict:
    from ecograph.evaluation.e2e_scenarios import run_all_scenarios
    results = run_all_scenarios()
    n_passed = sum(1 for r in results if r.passed)
    details = [
        {"name": r.name, "passed": r.passed, "duration_s": f"{r.duration_s:.1f}",
         "failed_checks": r.failed_checks, "error": r.error}
        for r in results
    ]
    return {
        "benchmark": "E2E Scenarios",
        "passed": n_passed == len(results),
        "n_passed": n_passed,
        "n_total": len(results),
        "scenarios": details,
    }


def _print_summary(results: list[dict]) -> None:
    print("\n" + "=" * 60)
    print(" ECOGRAPH EVALUATION SUMMARY")
    print("-" * 60)
    all_passed = True
    for r in results:
        status = "PASS" if r.get("passed") else "FAIL"
        all_passed = all_passed and r.get("passed", False)
        print(f"[{status}] {r['benchmark']}")
        for k, v in r.items():
            if k not in ("benchmark", "passed", "scenarios"):
                print(f"    {k}: {v}")
        if "scenarios" in r:
            for s in r["scenarios"]:
                s_status = "PASS" if s["passed"] else "FAIL"
                print(f"      [{s_status}] {s['name']} ({s['duration_s']}s)")
                if s.get("failed_checks"):
                    print(f"        failed: {s['failed_checks']}")
                if s.get("error"):
                    print(f"        error: {s['error']}")
    print("\n" + "=" * 60)
    print(f"Overall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    print("=" * 60 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run EcoGraph benchmarks")
    parser.add_argument(
        "--only",
        choices=["retrieval", "plume", "e2e"],
        default=None,
        help="Run only one benchmark",
    )
    args = parser.parse_args()

    results: list[dict] = []

    run_all = args.only is None
    if run_all or args.only == "retrieval":
        try:
            results.append(run_retrieval())
        except Exception as exc:
            logger.error("Retrieval benchmark error: %s", exc)
            results.append({"benchmark": "GraphRAG Retrieval", "passed": False, "error": str(exc)})

    if run_all or args.only == "plume":
        try:
            results.append(run_plume())
        except Exception as exc:
            logger.error("Plume benchmark error: %s", exc)
            results.append({"benchmark": "Plume Detection", "passed": False, "error": str(exc)})

    if run_all or args.only == "e2e":
        try:
            results.append(run_e2e())
        except Exception as exc:
            logger.error("E2E benchmark error: %s", exc)
            results.append({"benchmark": "E2E Scenarios", "passed": False, "error": str(exc)})

    _print_summary(results)


if __name__ == "__main__":
    main()