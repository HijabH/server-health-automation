from __future__ import annotations

import fnmatch
import shutil
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .models import CheckResult, Status


@dataclass
class Environment:
    """Everything the checks read from the outside world, so tests can replace it."""

    disk_usage: Callable = shutil.disk_usage
    run: Callable = subprocess.run
    meminfo_path: Path = Path("/proc/meminfo")
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    http_get: Callable | None = None
    tls_expiry: Callable | None = None

    def __post_init__(self):
        self.http_get = self.http_get or _http_get
        self.tls_expiry = self.tls_expiry or _tls_expiry


def _threshold(value: float, warn: float, crit: float) -> Status:
    if value >= crit:
        return Status.CRIT
    if value >= warn:
        return Status.WARN
    return Status.OK


def check_disk(cfg: dict, env: Environment) -> CheckResult:
    path = cfg["path"]
    usage = env.disk_usage(path)
    percent = round(usage.used / usage.total * 100, 1)
    status = _threshold(percent, cfg.get("warn_percent", 80), cfg.get("crit_percent", 90))
    free_gb = round(usage.free / 1024**3, 1)
    return CheckResult(cfg["name"], status, f"{path} {percent}% used, {free_gb} GB free",
                       {"percent_used": percent, "free_gb": free_gb})


def check_memory(cfg: dict, env: Environment) -> CheckResult:
    values = {}
    for line in env.meminfo_path.read_text().splitlines():
        key, _, rest = line.partition(":")
        values[key] = int(rest.split()[0])
    total, available = values["MemTotal"], values["MemAvailable"]
    percent = round((total - available) / total * 100, 1)
    status = _threshold(percent, cfg.get("warn_percent", 85), cfg.get("crit_percent", 95))
    return CheckResult(cfg["name"], status, f"memory {percent}% used", {"percent_used": percent})


def check_service(cfg: dict, env: Environment) -> CheckResult:
    unit = cfg["unit"]
    result = env.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=10)
    state = result.stdout.strip() or "unknown"
    status = Status.OK if state == "active" else Status.CRIT
    return CheckResult(cfg["name"], status, f"{unit} is {state}", {"state": state})


def _http_get(url: str, timeout: float) -> int:
    request = urllib.request.Request(url, headers={"User-Agent": "server-health-automation"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as e:
        return e.code


def check_http(cfg: dict, env: Environment) -> CheckResult:
    url = cfg["url"]
    expected = cfg.get("expected_status", 200)
    started = time.monotonic()
    try:
        code = env.http_get(url, cfg.get("timeout_seconds", 10))
    except (urllib.error.URLError, OSError) as e:
        return CheckResult(cfg["name"], Status.CRIT, f"{url} unreachable: {getattr(e, 'reason', e)}")
    elapsed_ms = round((time.monotonic() - started) * 1000)

    if code != expected:
        return CheckResult(cfg["name"], Status.CRIT, f"{url} returned {code}, expected {expected}",
                           {"status_code": code, "ms": elapsed_ms})
    slow_ms = cfg.get("warn_ms")
    if slow_ms is not None and elapsed_ms > slow_ms:
        return CheckResult(cfg["name"], Status.WARN, f"{url} took {elapsed_ms} ms (limit {slow_ms} ms)",
                           {"status_code": code, "ms": elapsed_ms})
    return CheckResult(cfg["name"], Status.OK, f"{url} returned {code} in {elapsed_ms} ms",
                       {"status_code": code, "ms": elapsed_ms})


def _tls_expiry(host: str, port: int, timeout: float) -> datetime:
    context = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            not_after = tls.getpeercert()["notAfter"]
    return datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), timezone.utc)


def check_tls(cfg: dict, env: Environment) -> CheckResult:
    host, port = cfg["host"], cfg.get("port", 443)
    try:
        expires = env.tls_expiry(host, port, cfg.get("timeout_seconds", 10))
    except (ssl.SSLError, OSError) as e:
        return CheckResult(cfg["name"], Status.CRIT, f"TLS check for {host} failed: {e}")

    days = (expires - env.now()).days
    warn, crit = cfg.get("warn_days", 21), cfg.get("crit_days", 7)
    status = Status.CRIT if days < crit else Status.WARN if days < warn else Status.OK
    return CheckResult(cfg["name"], status, f"certificate for {host} expires in {days} days ({expires:%Y-%m-%d})",
                       {"days_left": days})


def check_backup(cfg: dict, env: Environment) -> CheckResult:
    directory = Path(cfg["directory"])
    pattern = cfg.get("pattern", "*")
    if not directory.is_dir():
        return CheckResult(cfg["name"], Status.CRIT, f"backup directory {directory} does not exist")

    files = [p for p in directory.iterdir() if p.is_file() and fnmatch.fnmatch(p.name, pattern)]
    if not files:
        return CheckResult(cfg["name"], Status.CRIT, f"no backups matching {pattern} in {directory}")

    newest = max(files, key=lambda p: p.stat().st_mtime)
    modified = datetime.fromtimestamp(newest.stat().st_mtime, timezone.utc)
    age_hours = round((env.now() - modified).total_seconds() / 3600, 1)
    size = newest.stat().st_size
    data = {"file": newest.name, "age_hours": age_hours, "size_bytes": size}

    if age_hours > cfg.get("max_age_hours", 26):
        return CheckResult(cfg["name"], Status.CRIT, f"newest backup {newest.name} is {age_hours} h old", data)
    if size < cfg.get("min_size_bytes", 1):
        return CheckResult(cfg["name"], Status.CRIT, f"newest backup {newest.name} is only {size} bytes", data)
    return CheckResult(cfg["name"], Status.OK, f"newest backup {newest.name} is {age_hours} h old", data)


CHECKS = {
    "disk": check_disk,
    "memory": check_memory,
    "service": check_service,
    "http": check_http,
    "tls": check_tls,
    "backup": check_backup,
}
