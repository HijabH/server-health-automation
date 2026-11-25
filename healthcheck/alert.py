from __future__ import annotations

import json
import urllib.request
from typing import Callable

from .models import Status
from .state import Change


def format_alert(server: str, found: list[Change]) -> str:
    problems = [c for c in found if not c.recovered]
    recovered = [c for c in found if c.recovered]
    lines = [f"{server}: {len(problems)} problem(s), {len(recovered)} recovered"]
    for c in problems:
        lines.append(f"{c.result.status.name} {c.result.name}: {c.result.message}")
    for c in recovered:
        lines.append(f"RECOVERED {c.result.name}: {c.result.message}")
    return "\n".join(lines)


def _post(url: str, body: bytes, timeout: float) -> int:
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status


def send_webhook(url: str, text: str, post: Callable[[str, bytes, float], int] = _post) -> None:
    # {"text": ...} is accepted by Slack, Microsoft Teams and Mattermost incoming webhooks.
    status = post(url, json.dumps({"text": text}).encode(), 10)
    if status >= 300:
        raise RuntimeError(f"webhook returned HTTP {status}")


def should_alert(found: list[Change], alert_on_unknown: bool) -> list[Change]:
    if alert_on_unknown:
        return found
    return [c for c in found if c.result.status != Status.UNKNOWN]
