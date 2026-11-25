import json

import pytest

from healthcheck.__main__ import main
from healthcheck.alert import format_alert, send_webhook, should_alert
from healthcheck.config import ConfigError, parse_config
from healthcheck.models import CheckResult, Status
from healthcheck.runner import run_checks
from healthcheck.state import changes, load_state, save_state


def test_config_reports_every_problem_at_once():
    with pytest.raises(ConfigError) as e:
        parse_config({"check": [
            {"type": "disk", "name": "A"},
            {"type": "ping", "name": "B"},
            {"type": "service", "name": "A", "unit": "x"},
            {"type": "memory"},
        ]})
    message = str(e.value)
    assert "check 1 (A): missing path" in message
    assert "unknown type 'ping'" in message
    assert "check 3 (A): duplicate name" in message
    assert "missing name" in message


def test_config_requires_checks():
    with pytest.raises(ConfigError, match="no \\[\\[check\\]\\]"):
        parse_config({})


def test_webhook_url_from_environment_wins(monkeypatch):
    monkeypatch.setenv("HEALTHCHECK_WEBHOOK_URL", "https://env")
    config = parse_config({"alert": {"webhook_url": "https://file"}, "check": [{"type": "memory", "name": "M"}]})
    assert config.webhook_url == "https://env"


def test_a_crashing_check_becomes_unknown_and_others_still_run(system):
    results = run_checks([{"type": "disk", "name": "Missing", "path": "/nope"},
                          {"type": "memory", "name": "Memory"}], system.env())
    assert results[0].status == Status.UNKNOWN
    assert "could not run" in results[0].message
    assert results[1].status == Status.OK


def test_changes_only_reports_transitions():
    previous = {"Disk": Status.OK, "Nginx": Status.CRIT, "Memory": Status.WARN}
    results = [
        CheckResult("Disk", Status.CRIT, "full"),
        CheckResult("Nginx", Status.OK, "active"),
        CheckResult("Memory", Status.WARN, "high"),
        CheckResult("New OK", Status.OK, "fine"),
        CheckResult("New bad", Status.WARN, "bad"),
    ]
    found = changes(previous, results)
    assert [c.result.name for c in found] == ["Disk", "Nginx", "New bad"]
    assert found[1].recovered


def test_alert_text_lists_problems_then_recoveries():
    text = format_alert("srv", changes({"Nginx": Status.CRIT}, [
        CheckResult("Disk", Status.CRIT, "/ 95% used"),
        CheckResult("Nginx", Status.OK, "nginx is active"),
    ]))
    assert text.splitlines() == [
        "srv: 1 problem(s), 1 recovered",
        "CRIT Disk: / 95% used",
        "RECOVERED Nginx: nginx is active",
    ]


def test_unknown_results_can_be_left_out_of_alerts():
    found = changes({}, [CheckResult("A", Status.UNKNOWN, "?"), CheckResult("B", Status.CRIT, "!")])
    assert [c.result.name for c in should_alert(found, alert_on_unknown=False)] == ["B"]


def test_webhook_payload_and_error():
    sent = []
    send_webhook("https://hook", "hello", post=lambda url, body, timeout: sent.append(json.loads(body)) or 200)
    assert sent == [{"text": "hello"}]
    with pytest.raises(RuntimeError, match="HTTP 500"):
        send_webhook("https://hook", "hello", post=lambda *a: 500)


def test_state_round_trip_and_corrupt_file(tmp_path):
    path = tmp_path / "sub" / "state.json"
    save_state(path, [CheckResult("A", Status.WARN, "")])
    assert load_state(path) == {"A": Status.WARN}
    path.write_text("not json")
    assert load_state(path) == {}
    assert load_state(None) == {}


def _write_config(tmp_path, webhook=""):
    config = tmp_path / "checks.toml"
    config.write_text(f'''
[server]
name = "test-server"
[alert]
webhook_url = "{webhook}"
state_file = "{tmp_path / 'state.json'}"
[[check]]
type = "service"
name = "Nginx"
unit = "nginx"
[[check]]
type = "memory"
name = "Memory"
''')
    return config


def test_main_prints_report_and_returns_worst_status(system, tmp_path, capsys):
    config = _write_config(tmp_path)
    assert main(["-c", str(config)], env=system.env()) == 0
    system.services["nginx"] = "inactive"
    assert main(["-c", str(config), "--json"], env=system.env()) == 2

    report = json.loads(capsys.readouterr().out.split("\n", 3)[-1])
    assert report["overall"] == "CRIT"
    assert report["checks"][0]["message"] == "nginx is inactive"
    assert json.loads((tmp_path / "state.json").read_text())["Nginx"] == "CRIT"


def test_main_keeps_old_state_when_the_alert_fails(system, tmp_path, monkeypatch, capsys):
    config = _write_config(tmp_path, webhook="https://hook")
    main(["-c", str(config)], env=system.env())

    def broken(*args):
        raise OSError("network down")

    monkeypatch.setattr("healthcheck.__main__.send_webhook", lambda url, text: broken())
    system.services["nginx"] = "failed"
    assert main(["-c", str(config)], env=system.env()) == 2
    assert "could not send alert: network down" in capsys.readouterr().err
    assert json.loads((tmp_path / "state.json").read_text())["Nginx"] == "OK"


def test_main_reports_bad_config(tmp_path, capsys):
    bad = tmp_path / "bad.toml"
    bad.write_text("[[check]]\ntype = 'disk'\n")
    assert main(["-c", str(bad)]) == 3
    assert "configuration error" in capsys.readouterr().err
