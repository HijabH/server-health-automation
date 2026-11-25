from __future__ import annotations

import argparse
import sys

from .alert import format_alert, send_webhook, should_alert
from .checks import Environment
from .config import ConfigError, load_config
from .models import Status, worst
from .report import json_report, text_report
from .runner import run_checks
from .state import changes, load_state, save_state


def main(argv: list[str] | None = None, env: Environment | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m healthcheck", description="Run server health checks.")
    parser.add_argument("--config", "-c", default="/etc/server-health/checks.toml")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--no-alert", action="store_true", help="do not send a webhook or update the state file")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except (ConfigError, OSError) as e:
        print(f"configuration error: {e}", file=sys.stderr)
        return Status.UNKNOWN

    env = env or Environment()
    results = run_checks(config.checks, env)
    now = env.now()
    print(json_report(config.server_name, results, now) if args.json else text_report(config.server_name, results, now))

    if not args.no_alert:
        found = should_alert(changes(load_state(config.state_file), results), config.alert_on_unknown)
        delivered = True
        if found and config.webhook_url:
            try:
                send_webhook(config.webhook_url, format_alert(config.server_name, found))
            except Exception as e:
                delivered = False
                print(f"could not send alert: {e}", file=sys.stderr)
        # Keep the old state if the alert failed, so the next run tries again.
        if delivered:
            save_state(config.state_file, results)

    return int(worst(r.status for r in results))


if __name__ == "__main__":
    sys.exit(main())
