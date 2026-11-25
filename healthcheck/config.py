from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .checks import CHECKS

REQUIRED = {
    "disk": ["path"],
    "memory": [],
    "service": ["unit"],
    "http": ["url"],
    "tls": ["host"],
    "backup": ["directory"],
}


class ConfigError(Exception):
    pass


@dataclass
class Config:
    server_name: str
    checks: list[dict]
    webhook_url: str | None = None
    state_file: Path | None = None
    alert_on_unknown: bool = True


def parse_config(data: dict) -> Config:
    errors = []
    checks = data.get("check", [])
    if not checks:
        errors.append("no [[check]] entries")

    seen = set()
    for i, check in enumerate(checks, start=1):
        kind = check.get("type")
        name = check.get("name")
        label = f"check {i} ({name or 'unnamed'})"
        if kind not in CHECKS:
            errors.append(f"{label}: unknown type {kind!r}, expected one of {', '.join(CHECKS)}")
            continue
        if not name:
            errors.append(f"{label}: missing name")
        elif name in seen:
            errors.append(f"{label}: duplicate name")
        seen.add(name)
        for key in REQUIRED[kind]:
            if key not in check:
                errors.append(f"{label}: missing {key}")

    if errors:
        raise ConfigError("; ".join(errors))

    alert = data.get("alert", {})
    state_file = alert.get("state_file")
    return Config(
        server_name=data.get("server", {}).get("name", "server"),
        checks=checks,
        # The webhook URL is a secret, so the environment variable wins over the file.
        webhook_url=os.getenv("HEALTHCHECK_WEBHOOK_URL") or alert.get("webhook_url") or None,
        state_file=Path(state_file) if state_file else None,
        alert_on_unknown=alert.get("alert_on_unknown", True),
    )


def load_config(path: str | Path) -> Config:
    try:
        with open(path, "rb") as f:
            return parse_config(tomllib.load(f))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
