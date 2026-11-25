import os
import urllib.error
from datetime import timedelta

from conftest import NOW, Usage
from healthcheck.checks import check_backup, check_disk, check_http, check_memory, check_service, check_tls
from healthcheck.models import Status, worst


def test_disk_thresholds(system):
    cfg = {"name": "Root", "path": "/", "warn_percent": 80, "crit_percent": 90}
    gb = 1024**3
    for used, expected in [(50, Status.OK), (80, Status.WARN), (95, Status.CRIT)]:
        system.disks["/"] = Usage(100 * gb, used * gb, (100 - used) * gb)
        result = check_disk(cfg, system.env())
        assert result.status == expected
        assert result.data["percent_used"] == used
    assert "5.0 GB free" in result.message


def test_memory_uses_available_not_free(system):
    result = check_memory({"name": "Memory"}, system.env())
    assert result.status == Status.OK
    assert result.data["percent_used"] == 50.0


def test_memory_critical(system):
    system.meminfo.write_text("MemTotal: 1000 kB\nMemAvailable: 20 kB\n")
    assert check_memory({"name": "Memory"}, system.env()).status == Status.CRIT


def test_service_active_and_stopped(system):
    assert check_service({"name": "Nginx", "unit": "nginx"}, system.env()).status == Status.OK
    system.services["nginx"] = "failed"
    result = check_service({"name": "Nginx", "unit": "nginx"}, system.env())
    assert result.status == Status.CRIT
    assert result.message == "nginx is failed"


def test_http_ok_wrong_status_and_unreachable(system):
    cfg = {"name": "API", "url": "https://x/api/ping"}
    system.http["https://x/api/ping"] = 200
    assert check_http(cfg, system.env()).status == Status.OK

    system.http["https://x/api/ping"] = 503
    result = check_http(cfg, system.env())
    assert result.status == Status.CRIT
    assert "returned 503, expected 200" in result.message

    system.http["https://x/api/ping"] = urllib.error.URLError("connection refused")
    result = check_http(cfg, system.env())
    assert result.status == Status.CRIT
    assert "unreachable: connection refused" in result.message


def test_http_slow_response_warns(system):
    system.http["https://x"] = 200
    result = check_http({"name": "API", "url": "https://x", "warn_ms": -1}, system.env())
    assert result.status == Status.WARN


def test_tls_expiry_thresholds(system):
    cfg = {"name": "TLS", "host": "example.org", "warn_days": 21, "crit_days": 7}
    for days, expected in [(60, Status.OK), (20, Status.WARN), (3, Status.CRIT), (-1, Status.CRIT)]:
        system.certs["example.org"] = NOW + timedelta(days=days, hours=1)
        assert check_tls(cfg, system.env()).status == expected


def test_tls_handshake_failure_is_critical(system):
    system.certs["example.org"] = OSError("certificate verify failed")
    result = check_tls({"name": "TLS", "host": "example.org"}, system.env())
    assert result.status == Status.CRIT
    assert "verify failed" in result.message


def _backup(directory, name, hours_old, size=2048):
    path = directory / name
    path.write_bytes(b"x" * size)
    ts = (NOW - timedelta(hours=hours_old)).timestamp()
    os.utime(path, (ts, ts))
    return path


def test_backup_uses_newest_matching_file(system, tmp_path):
    _backup(tmp_path, "dhis2-old.sql.gz", 50)
    _backup(tmp_path, "dhis2-new.sql.gz", 3)
    _backup(tmp_path, "notes.txt", 0)
    cfg = {"name": "Backup", "directory": str(tmp_path), "pattern": "dhis2-*.sql.gz", "max_age_hours": 26}
    result = check_backup(cfg, system.env())
    assert result.status == Status.OK
    assert result.data["file"] == "dhis2-new.sql.gz"
    assert result.data["age_hours"] == 3.0


def test_backup_too_old_too_small_or_missing(system, tmp_path):
    cfg = {"name": "Backup", "directory": str(tmp_path), "pattern": "*.gz", "max_age_hours": 26, "min_size_bytes": 1000}
    assert check_backup(cfg, system.env()).status == Status.CRIT  # no files

    _backup(tmp_path, "a.gz", 30)
    assert "30.0 h old" in check_backup(cfg, system.env()).message

    _backup(tmp_path, "b.gz", 1, size=10)
    assert "only 10 bytes" in check_backup(cfg, system.env()).message

    missing = dict(cfg, directory=str(tmp_path / "nope"))
    assert "does not exist" in check_backup(missing, system.env()).message


def test_worst_status_ranks_crit_over_warn_over_unknown():
    assert worst([]) == Status.OK
    assert worst([Status.OK, Status.UNKNOWN]) == Status.UNKNOWN
    assert worst([Status.UNKNOWN, Status.WARN]) == Status.WARN
    assert worst([Status.WARN, Status.CRIT, Status.OK]) == Status.CRIT
