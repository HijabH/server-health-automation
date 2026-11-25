from __future__ import annotations

import json
from datetime import datetime

from .models import CheckResult, worst


def text_report(server: str, results: list[CheckResult], at: datetime) -> str:
    width = max((len(r.name) for r in results), default=0)
    lines = [f"{server}  {at:%Y-%m-%d %H:%M:%S %Z}  overall: {worst(r.status for r in results).name}"]
    for r in results:
        lines.append(f"  {r.status.name:<7} {r.name:<{width}}  {r.message}")
    return "\n".join(lines)


def json_report(server: str, results: list[CheckResult], at: datetime) -> str:
    return json.dumps({
        "server": server,
        "time": at.isoformat(timespec="seconds"),
        "overall": worst(r.status for r in results).name,
        "checks": [r.to_dict() for r in results],
    }, indent=2)
