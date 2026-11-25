"""Outgoing email and SMS.

Backends:
- `smtp` (email): STARTTLS or implicit TLS only; credentials from settings; runs in a worker
  thread with a timeout so a slow mail server never blocks the event loop.
- `dev_outbox`: writes each message to a file under DEV_OUTBOX_DIR (git-ignored) so links and
  codes can be used locally. Refused in production by settings validation.
- `disabled`: nothing can be sent. Callers must say so to the user (never claim it was sent).

No SMS provider is wired yet: India requires DLT-registered templates, so the provider choice
(MSG91, Twilio, ...) is a business decision (tech-debt M1). The `SmsSender` interface is ready.
"""

import asyncio
import logging
import re
import smtplib
import ssl
import time
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from pathlib import Path
from typing import Protocol

from app.core.config import Settings

logger = logging.getLogger(__name__)


class DeliveryUnavailableError(Exception):
    """The channel is not configured, or delivery failed. Safe to show a generic message."""


@dataclass(frozen=True, slots=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str


class EmailSender(Protocol):
    available: bool

    async def send(self, message: OutgoingEmail) -> None: ...


class SmsSender(Protocol):
    available: bool

    async def send(self, phone: str, text: str) -> None: ...


# --------------------------------------------------------------------------- #
# Disabled
# --------------------------------------------------------------------------- #
class DisabledEmailSender:
    available = False

    async def send(self, message: OutgoingEmail) -> None:
        raise DeliveryUnavailableError("email is not configured")


class DisabledSmsSender:
    available = False

    async def send(self, phone: str, text: str) -> None:
        raise DeliveryUnavailableError("sms is not configured")


# --------------------------------------------------------------------------- #
# Development outbox
# --------------------------------------------------------------------------- #
def _write_outbox(directory: Path, kind: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}-{uuid.uuid4().hex[:8]}.txt"
    path.write_text(body, encoding="utf-8")
    return path


class DevOutboxEmailSender:
    available = True

    def __init__(self, directory: Path) -> None:
        self._dir = directory

    async def send(self, message: OutgoingEmail) -> None:
        body = f"To: {message.to}\nSubject: {message.subject}\n\n{message.text}\n"
        path = await asyncio.to_thread(_write_outbox, self._dir, "email", body)
        # The file name only: the content holds a secret link.
        logger.info("email_written_to_dev_outbox", extra={"file": path.name})


class DevOutboxSmsSender:
    available = True

    def __init__(self, directory: Path) -> None:
        self._dir = directory

    async def send(self, phone: str, text: str) -> None:
        path = await asyncio.to_thread(_write_outbox, self._dir, "sms", f"To: {phone}\n\n{text}\n")
        logger.info("sms_written_to_dev_outbox", extra={"file": path.name})


# --------------------------------------------------------------------------- #
# SMTP
# --------------------------------------------------------------------------- #
_HEADER_SAFE = re.compile(r"[\r\n]")


class SmtpEmailSender:
    available = True

    def __init__(self, settings: Settings) -> None:
        if not settings.smtp_host:
            raise ValueError("SMTP_HOST is required")
        self._host = settings.smtp_host
        self._port = settings.smtp_port
        self._username = settings.smtp_username
        self._password = settings.smtp_password
        self._security = settings.smtp_security
        self._timeout = settings.smtp_timeout_seconds
        self._from = settings.email_from

    def _build(self, message: OutgoingEmail) -> EmailMessage:
        if _HEADER_SAFE.search(message.to + message.subject) or "@" not in parseaddr(message.to)[1]:
            raise DeliveryUnavailableError("refusing unsafe headers")  # header injection guard
        msg = EmailMessage()
        msg["From"] = self._from
        msg["To"] = message.to
        msg["Subject"] = message.subject
        msg["Date"] = formatdate(localtime=False)
        msg["Message-ID"] = make_msgid(domain=parseaddr(self._from)[1].split("@")[-1] or None)
        msg.set_content(message.text)
        return msg

    def _send_blocking(self, msg: EmailMessage) -> None:
        context = ssl.create_default_context()  # verifies the server certificate and hostname
        smtp: smtplib.SMTP
        if self._security == "ssl":
            smtp = smtplib.SMTP_SSL(self._host, self._port, timeout=self._timeout, context=context)
        else:
            smtp = smtplib.SMTP(self._host, self._port, timeout=self._timeout)
        with smtp:
            if self._security == "starttls":
                smtp.starttls(context=context)
            if self._username and self._password:
                smtp.login(self._username, self._password.get_secret_value())
            smtp.send_message(msg)

    async def send(self, message: OutgoingEmail) -> None:
        msg = self._build(message)
        try:
            async with asyncio.timeout(self._timeout + 5):
                await asyncio.to_thread(self._send_blocking, msg)
        except Exception as exc:
            # Type only: SMTP errors can echo addresses or server details.
            logger.warning("email_send_failed", extra={"error_type": type(exc).__name__})
            raise DeliveryUnavailableError("email delivery failed") from None


# --------------------------------------------------------------------------- #
# Factories
# --------------------------------------------------------------------------- #
def build_email_sender(settings: Settings) -> EmailSender:
    match settings.resolved_email_backend:
        case "smtp":
            return SmtpEmailSender(settings)
        case "dev_outbox":
            return DevOutboxEmailSender(Path(settings.dev_outbox_dir))
        case _:
            return DisabledEmailSender()


def build_sms_sender(settings: Settings) -> SmsSender:
    if settings.resolved_sms_backend == "dev_outbox":
        return DevOutboxSmsSender(Path(settings.dev_outbox_dir))
    return DisabledSmsSender()
