"""Send an EPUB to a Kindle via the Send to Kindle email address (SMTP).

Amazon has no public Personal Documents API; SMTP is the stable, documented
path. The sender account must be approved under Amazon -> Content & Devices
-> Preferences -> Personal Document Settings, and the recipient is the
user's @kindle.com address.

Config comes from environment variables (no CLI flags beyond --send):

    AK_SMTP_USER      sender email address (e.g. a Gmail account)
    AK_SMTP_PASSWORD  app password for that account (Gmail/Outlook require one)
    AK_SMTP_HOST      SMTP server (default smtp.gmail.com)
    AK_SMTP_PORT      port (default 587; 465 selects implicit TLS)
    AK_KINDLE_EMAIL   recipient @kindle.com address (default deven367@kindle.com)

Stdlib only (smtplib + email); zero new dependencies.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

KINDLE_EMAIL_DEFAULT = "deven367@kindle.com"
DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024  # Amazon personal-document size limit


class SendError(ValueError):
    """The EPUB could not be emailed (config, size, or SMTP failure)."""


def kindle_recipient() -> str:
    """The configured @kindle.com address."""
    return os.environ.get("AK_KINDLE_EMAIL", KINDLE_EMAIL_DEFAULT)


def send_epub(
    epub_path: Path,
    *,
    recipient: str | None = None,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    smtp_user: str | None = None,
    smtp_password: str | None = None,
) -> str:
    """Email ``epub_path`` to the Kindle address. Returns the recipient.

    Raises SendError on missing config, an oversize attachment, or SMTP
    failure. The EPUB itself is never touched: callers keep the local file
    regardless of the outcome.
    """
    recipient = recipient or kindle_recipient()
    host = smtp_host or os.environ.get("AK_SMTP_HOST", DEFAULT_SMTP_HOST)
    port = smtp_port if smtp_port is not None else int(
        os.environ.get("AK_SMTP_PORT", str(DEFAULT_SMTP_PORT))
    )
    user = smtp_user or os.environ.get("AK_SMTP_USER")
    password = smtp_password or os.environ.get("AK_SMTP_PASSWORD")

    if not user or not password:
        raise SendError(
            "emailing needs AK_SMTP_USER and AK_SMTP_PASSWORD in the environment "
            "(sender account + app password); see README"
        )

    size = epub_path.stat().st_size
    if size > MAX_ATTACHMENT_BYTES:
        raise SendError(
            f"{epub_path.name} is {size / 1024 / 1024:.1f} MB; "
            f"Amazon's personal-document limit is {MAX_ATTACHMENT_BYTES // 1024 // 1024} MB"
        )

    msg = EmailMessage()
    msg["Subject"] = epub_path.stem
    msg["From"] = user
    msg["To"] = recipient
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.add_attachment(
        epub_path.read_bytes(),
        maintype="application",
        subtype="epub+zip",
        filename=epub_path.name,
    )

    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=60)
        else:
            server = smtplib.SMTP(host, port, timeout=60)
        with server:
            server.ehlo()
            if port != 465:
                server.starttls()
                server.ehlo()
            server.login(user, password)
            server.send_message(msg)
    except (OSError, smtplib.SMTPException) as exc:
        raise SendError(f"SMTP send failed: {exc}") from exc

    return recipient
