"""Mail providers behind one interface, chosen by configuration (FR-N9)."""

import base64
import logging
import smtplib
import ssl
import time
import uuid
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr
from typing import Protocol

import httpx

from app.config import Settings, get_settings

log = logging.getLogger(__name__)


@dataclass
class OutgoingMail:
    to: str
    subject: str
    text: str
    html: str
    # The district's sender name, when an admin has set one (FR-AD1).
    sender_name: str | None = None


class MailProvider(Protocol):
    def send(self, mail: OutgoingMail) -> str:
        """Send one message and return the provider's message ID."""
        ...


def build_mime(mail: OutgoingMail, settings: Settings) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((mail.sender_name or settings.mail_sender_name, settings.mail_sender))
    message["To"] = mail.to
    message["Subject"] = mail.subject
    message.set_content(mail.text)
    message.add_alternative(mail.html, subtype="html")
    return message


@dataclass
class ConsoleProvider:
    """Development and test provider. Keeps sent mail in memory."""

    outbox: list[OutgoingMail] = field(default_factory=list)

    def send(self, mail: OutgoingMail) -> str:
        self.outbox.append(mail)
        log.info("mail to %s: %s", mail.to, mail.subject)
        return f"console-{uuid.uuid4()}"


class SmtpProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, mail: OutgoingMail) -> str:
        s = self.settings
        message = build_mime(mail, s)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30) as smtp:
            if s.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if s.smtp_username:
                smtp.login(s.smtp_username, s.smtp_password)
            smtp.send_message(message)
        return message.get("Message-ID") or f"smtp-{uuid.uuid4()}"


class GmailApiProvider:
    """Gmail API over OAuth2 with a long-lived refresh token.

    Works with a free Gmail account or a Google Workspace account.
    """

    TOKEN_URL = "https://oauth2.googleapis.com/token"
    SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=30)
        self._access_token: str | None = None
        self._expires_at = 0.0

    def _token(self) -> str:
        if self._access_token and time.time() < self._expires_at - 60:
            return self._access_token
        s = self.settings
        response = self.client.post(
            self.TOKEN_URL,
            data={
                "client_id": s.gmail_client_id,
                "client_secret": s.gmail_client_secret,
                "refresh_token": s.gmail_refresh_token,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        body = response.json()
        self._access_token = body["access_token"]
        self._expires_at = time.time() + int(body.get("expires_in", 3600))
        return self._access_token

    def send(self, mail: OutgoingMail) -> str:
        raw = base64.urlsafe_b64encode(build_mime(mail, self.settings).as_bytes()).decode()
        response = self.client.post(
            self.SEND_URL,
            headers={"Authorization": f"Bearer {self._token()}"},
            json={"raw": raw},
        )
        response.raise_for_status()
        return response.json()["id"]


_provider: MailProvider | None = None


def get_provider() -> MailProvider:
    global _provider
    if _provider is None:
        settings = get_settings()
        match settings.mail_provider:
            case "gmail":
                _provider = GmailApiProvider(settings)
            case "smtp":
                _provider = SmtpProvider(settings)
            case _:
                _provider = ConsoleProvider()
    return _provider


def set_provider(provider: MailProvider | None) -> None:
    global _provider
    _provider = provider
