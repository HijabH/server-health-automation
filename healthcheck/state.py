from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .models import CheckResult, Status


@dataclass(frozen=True)
class Change:
    result: CheckResult
    previous: Status | None

    @property
    def recovered(self) -> bool:
        return self.result.status == Status.OK


def load_state(path: Path | None) -> dict[str, Status]:
    if path is None or not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
        return {name: Status[value] for name, value in raw.items()}
    except (ValueError, KeyError):
        return {}


def save_state(path: Path | None, results: list[CheckResult]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({r.name: r.status.name for r in results}, indent=2))
    tmp.replace(path)


def changes(previous: dict[str, Status], results: list[CheckResult]) -> list[Change]:
    """Checks whose status differs from the last run. A new check counts only if it is not OK."""
    found = []
    for result in results:
        before = previous.get(result.name)
        if before is None and result.status == Status.OK:
            continue
        if before != result.status:
            found.append(Change(result, before))
    return found
