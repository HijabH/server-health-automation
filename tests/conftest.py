from collections import namedtuple
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from healthcheck.checks import Environment

NOW = datetime(2026, 11, 25, 6, 0, tzinfo=timezone.utc)
Usage = namedtuple("Usage", "total used free")


class FakeSystem:
    """Stands in for the disk, systemctl, the network and the clock."""

    def __init__(self, tmp_path):
        self.disks = {"/": Usage(100 * 1024**3, 50 * 1024**3, 50 * 1024**3)}
        self.services = {"nginx": "active"}
        self.http = {}
        self.certs = {}
        self.meminfo = tmp_path / "meminfo"
        self.meminfo.write_text("MemTotal:       16000000 kB\nMemFree:         1000000 kB\nMemAvailable:    8000000 kB\n")

    def run(self, cmd, **kwargs):
        return SimpleNamespace(stdout=self.services.get(cmd[-1], "inactive") + "\n", returncode=0)

    def http_get(self, url, timeout):
        response = self.http[url]
        if isinstance(response, Exception):
            raise response
        return response

    def tls_expiry(self, host, port, timeout):
        expiry = self.certs[host]
        if isinstance(expiry, Exception):
            raise expiry
        return expiry

    def env(self):
        return Environment(disk_usage=lambda p: self.disks[p], run=self.run, meminfo_path=self.meminfo,
                           now=lambda: NOW, http_get=self.http_get, tls_expiry=self.tls_expiry)


@pytest.fixture
def system(tmp_path):
    return FakeSystem(tmp_path)
