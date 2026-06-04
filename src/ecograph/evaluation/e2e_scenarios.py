from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Scenario definition
# -----------------------------------------------------------------------------

@dataclass
class Scenario:
    name: str
    query: str
    assertions: list[Callable[[dict], bool]]
    description: str = ""

def _has_key(key: str) -> Callable[[dict], bool]:
    return lambda state: bool(state.get(key))

def _no_errors(state: dict) -> bool:
    return not state.get("errors")

def _has_report(state: dict) -> bool:
    return bool(state.get("report_markdown") or state.get("report_path"))

def _has_recommendations(state: dict) -> bool:
    plan = state.get("supply_mitigation_plan", {})
    return bool(plan.get("recommendations"))

SCENARIOS: list[Scenario] = [
    Scenario(
        name="smoke_test",
        query="What are the top Scope-3 emission hotspots in our supply chain?",
        assertions=[
            _no_errors,
            _has_report,
            _has_key("data_analyst_summary"),
        ],
        description="Basic smoke test: pipeline completes without errors.",
    ),
    Scenario(
        name="mitigation_plan",
        query="Suggest supply chain optimisations to reduce Scope-3 emissions by 20%.",
        assertions=[
            _no_errors,
            _has_recommendations,
            _has_report,
        ],
        description="Agent generates concrete mitigation recommendations.",
    ),
    Scenario(
        name="satellite_verification",
        query="Verify reported emissions for our top supplier using satellite data.",
        assertions=[
            _no_errors,
            _has_key("satellite_verification"),
            _has_report,
        ],
        description="Satellite agent runs plume detection and cross-checks self-reported data.",
    ),
    Scenario(
        name="compliance_check",
        query="Are our current suppliers compliant with GHG Protocol Scope-3 requirements?",
        assertions=[
            _no_errors,
            _has_key("compliance_status"),
            _has_report,
        ],
        description="Validator checks regulatory alignment.",
    ),
]

# -----------------------------------------------------------------------------
# Runner
# -----------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    name: str
    passed: bool
    duration_s: float
    failed_checks: list[str]
    error: str = ""

def run_scenario(scenario: Scenario, timeout_s: int = 300) -> ScenarioResult:
    """Execute a single scenario and return the result."""
    from ecograph.agents.graph import get_agent
    
    agent = get_agent()
    start = time.time()
    failed = []
    error_msg = ""
    
    try:
        state = agent.invoke({"query": scenario.query, "iteration_count": 0, "errors": []})
        for check in scenario.assertions:
            try:
                if not check(state):
                    failed.append(check.__name__ if hasattr(check, "__name__") else str(check))
            except Exception as exc:
                failed.append(f"assertion_error:{exc}")
    except Exception as exc:
        error_msg = str(exc)
        logger.error("Scenario '%s' raised exception: %s", scenario.name, exc)
    
    duration = time.time() - start
    passed = not failed and not error_msg
    
    level = logging.INFO if passed else logging.WARNING
    logger.log(
        level,
        "Scenario '%s': %s (%.1fs)",
        scenario.name, "PASSED" if passed else "FAILED", duration,
    )
    
    return ScenarioResult(
        name=scenario.name,
        passed=passed,
        duration_s=duration,
        failed_checks=failed,
        error=error_msg,
    )

def run_all_scenarios(
    scenarios: list[Scenario] | None = None
) -> list[ScenarioResult]:
    """Run all scenarios and return results."""
    target = scenarios or SCENARIOS
    results = [run_scenario(s) for s in target]
    n_passed = sum(1 for r in results if r.passed)
    logger.info("E2E scenarios: %d/%d passed.", n_passed, len(results))
    return results