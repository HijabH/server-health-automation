from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Status(IntEnum):
    # Values follow the Nagios plugin convention, so they double as exit codes.
    OK = 0
    WARN = 1
    CRIT = 2
    UNKNOWN = 3


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    message: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status.name, "message": self.message, "data": self.data}


def worst(statuses) -> Status:
    # UNKNOWN means the check could not run; it is less urgent than a confirmed CRIT.
    order = [Status.OK, Status.UNKNOWN, Status.WARN, Status.CRIT]
    return max(statuses, key=order.index, default=Status.OK)
