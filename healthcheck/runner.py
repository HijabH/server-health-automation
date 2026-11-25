from __future__ import annotations

from .checks import CHECKS, Environment
from .models import CheckResult, Status


def run_checks(checks: list[dict], env: Environment) -> list[CheckResult]:
    results = []
    for cfg in checks:
        try:
            results.append(CHECKS[cfg["type"]](cfg, env))
        except Exception as e:  # one broken check must not stop the others
            results.append(CheckResult(cfg["name"], Status.UNKNOWN, f"check could not run: {e}"))
    return results
