"""Security event log (`app.security`).

Only identifiers that are safe to keep: event name, outcome, user id, client IP and a short
machine-readable reason. Never emails, phone numbers, passwords, tokens, cookies or headers.
"""

import logging
import uuid
from typing import Literal

security_logger = logging.getLogger("app.security")

type Outcome = Literal["success", "failure", "blocked"]


def log_auth_event(
    event: str,
    outcome: Outcome,
    *,
    user_id: uuid.UUID | None = None,
    ip: str | None = None,
    reason: str | None = None,
) -> None:
    level = logging.INFO if outcome == "success" else logging.WARNING
    security_logger.log(
        level,
        event,
        extra={
            "security_event": event,
            "outcome": outcome,
            "user_id": str(user_id) if user_id else None,
            "client_ip": ip,
            "reason": reason,
        },
    )
