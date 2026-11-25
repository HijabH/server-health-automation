# Server Health Automation

![tests](https://github.com/HijabH/server-health-automation/actions/workflows/ci.yml/badge.svg)

A small Python tool that runs scheduled health checks on a Linux server and sends an alert to Slack, Microsoft Teams or Mattermost when something changes. It needs nothing beyond the Python standard library, so it can run on a locked-down production server.

I looked after the Linux and Windows servers behind national health information systems (DHIS2, PostgreSQL, Tomcat, Nginx), where problems such as a full database disk, an expired certificate or a backup that silently stopped were found too late. This tool automates those morning checks.

```text
$ python -m healthcheck --config /etc/server-health/checks.toml
dhis2-prod-01  2026-11-25 06:00:00 UTC  overall: CRIT
  OK      Root disk                / 41.2% used, 58.3 GB free
  WARN    Database disk            /var/lib/postgresql 81.7% used, 36.5 GB free
  OK      Memory                   memory 63.0% used
  OK      Nginx                    nginx is active
  OK      PostgreSQL               postgresql is active
  OK      Tomcat                   tomcat9 is active
  OK      DHIS2 API                https://dhis2.example.org/api/system/ping returned 200 in 184 ms
  OK      TLS certificate          certificate for dhis2.example.org expires in 64 days (2027-01-28)
  CRIT    Nightly database backup  newest backup dhis2-2026-11-23.sql.gz is 30.5 h old
```

## Checks

| Type | What it checks | Default thresholds |
| --- | --- | --- |
| `disk` | Used space on a mount point | WARN 80%, CRIT 90% |
| `memory` | Used memory, based on `MemAvailable` | WARN 85%, CRIT 95% |
| `service` | A systemd unit is `active` | CRIT otherwise |
| `http` | An endpoint returns the expected status, optionally within a time limit | CRIT on wrong status or no answer, WARN if slow |
| `tls` | Days until the server certificate expires | WARN 21 days, CRIT 7 days |
| `backup` | The newest file matching a pattern is recent enough and not empty | CRIT after 26 hours |

All checks and thresholds are set in a TOML file; see [`samples/checks.toml`](samples/checks.toml) for a DHIS2 server.

## Alerts without the noise

The tool remembers the last status of every check in a state file and only alerts when a status **changes**. A disk that stays at WARN all week produces one message, not one every five minutes, and a recovery is reported once as well:

```text
dhis2-prod-01: 1 problem(s), 1 recovered
CRIT Nightly database backup: newest backup dhis2-2026-11-23.sql.gz is 30.5 h old
RECOVERED Tomcat: tomcat9 is active
```

If the webhook cannot be reached, the old state is kept, so the alert is sent on the next run instead of being lost.

## Quick start

Requires Python 3.11 or newer.

```bash
python -m healthcheck --config samples/local.toml     # runs on any Linux machine
python -m healthcheck --config samples/local.toml --json
```

The exit code follows the Nagios plugin convention (0 OK, 1 WARN, 2 CRIT, 3 UNKNOWN), so the tool can also be used from Nagios, Icinga or a CI job.

## Running it on a server

```bash
sudo useradd --system server-health
sudo cp -r . /opt/server-health-automation
sudo mkdir -p /etc/server-health && sudo cp samples/checks.toml /etc/server-health/
echo 'HEALTHCHECK_WEBHOOK_URL=https://hooks.slack.com/services/...' | sudo tee /etc/server-health/webhook.env
sudo chmod 600 /etc/server-health/webhook.env

sudo cp deploy/server-health.service deploy/server-health.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now server-health.timer
```

The systemd unit runs as an unprivileged user with a read-only file system (`ProtectSystem=strict`). A cron alternative is in [`deploy/crontab.example`](deploy/crontab.example). The webhook URL is read from an environment variable, so it never has to be written into the config file.

## Project structure

| Path | Responsibility |
| --- | --- |
| `healthcheck/checks.py` | The six checks, with every outside dependency passed in through `Environment` |
| `healthcheck/config.py` | Loads and validates the TOML file, reporting every problem at once |
| `healthcheck/runner.py` | Runs the checks; a check that crashes becomes UNKNOWN instead of stopping the run |
| `healthcheck/state.py` | Remembers the last status and finds what changed |
| `healthcheck/alert.py` | Formats the alert and posts it to the webhook |
| `healthcheck/report.py` | Text and JSON reports |
| `deploy/` | systemd service and timer, cron example |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

23 tests cover every check and threshold, configuration errors, crashing checks, change detection, alert text, webhook failures and the full command-line run. The disk, systemd, network and clock are replaced by a fake, so the tests run anywhere in under a second. GitHub Actions runs them on Python 3.11, 3.12 and 3.13.

## How this was built

I built this project with Claude, Anthropic's AI coding agent. The checks and thresholds come from what I monitored by hand and with cron scripts on production servers; the agent wrote the code and tests with me.

## Possible next steps

- PostgreSQL checks (connections, replication lag, database size)
- Windows support through `psutil`
- A daily summary message even when nothing changed

## License

[MIT](LICENSE)
