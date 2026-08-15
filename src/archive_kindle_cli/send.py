"""Send an EPUB to a Kindle via the Send to Kindle email address (SMTP).

Amazon has no public Personal Documents API; SMTP is the stable, documented
path. The sender account must be approved under Amazon -> Content & Devices
-> Preferences -> Personal Document Settings, and the recipient is the
user's @kindle.com address.

Config comes from environment variables (no CLI flags beyond --send):

    AK_SMTP_USER      sender email address (e.g. a Gmail account) — required
    AK_SMTP_PASSWORD  app password for that account (Gmail/Outlook require one) — required
    AK_SMTP_HOST      SMTP server (default smtp.gmail.com)
    AK_SMTP_PORT      port (default 587; 465 selects implicit TLS)
    AK_KINDLE_EMAIL   recipient @kindle.com address — required

The variables may also live in a `.env` file in the working directory
(KEY=VALUE lines, `#` comments and an optional `export` prefix supported);
already-set shell variables always win.

Stdlib only (smtplib + email); zero new dependencies.
"""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024  # Amazon personal-document size limit

# All three are required for --send. The CLI checks them up front so a missing
# variable fails fast with a one-line fix instead of surfacing as a cryptic
# SMTP error. There is deliberately no default recipient: a hardcoded
# @kindle.com address would silently mail to someone else's Kindle.
REQUIRED_SEND_ENV = (
    "AK_SMTP_USER",
    "AK_SMTP_PASSWORD",
    "AK_KINDLE_EMAIL",
)

_ENV_DESCRIPTIONS = {
    "AK_SMTP_USER": "sender email address (e.g. a Gmail/Outlook account)",
    "AK_SMTP_PASSWORD": "app password for that account (enable 2FA, then generate "
    "one — your login password won't work)",
    "AK_KINDLE_EMAIL": "your Kindle's @kindle.com address (amazon.com -> Content "
    "& Devices -> Devices)",
}


class SendError(ValueError):
    """The EPUB could not be emailed (config, size, or SMTP failure)."""


def _missing_env_message(missing: list[str]) -> str:
    lines = [
        "emailing to your Kindle requires 3 environment variables; missing: "
        + ", ".join(missing),
    ]
    lines += [f"  {name}  {_ENV_DESCRIPTIONS[name]}" for name in REQUIRED_SEND_ENV]
    lines.append(
        "set the missing ones in your shell and retry — see README "
        "'Send to Kindle' for details"
    )
    return "\n".join(lines)


def check_send_env() -> None:
    """Raise SendError naming every env var required by --send that is unset."""
    load_env_file()
    missing = [name for name in REQUIRED_SEND_ENV if not os.environ.get(name)]
    if missing:
        raise SendError(_missing_env_message(missing))


def kindle_recipient() -> str | None:
    """The configured @kindle.com address, or None if AK_KINDLE_EMAIL is unset."""
    return os.environ.get("AK_KINDLE_EMAIL")


def load_env_file(path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ (no override).

    Deliberately tiny and stdlib-only (the project ships zero runtime deps):
    blank lines and ``#`` comments are skipped, an optional ``export`` prefix
    is accepted, values may be single/double-quoted, and variables already set
    in the environment win — matching python-dotenv's default behavior.
    """
    env_file = Path(".env") if path is None else path
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


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
    load_env_file()
    recipient = recipient or kindle_recipient()
    host = smtp_host or os.environ.get("AK_SMTP_HOST", DEFAULT_SMTP_HOST)
    port = smtp_port if smtp_port is not None else int(
        os.environ.get("AK_SMTP_PORT", str(DEFAULT_SMTP_PORT))
    )
    user = smtp_user or os.environ.get("AK_SMTP_USER")
    password = smtp_password or os.environ.get("AK_SMTP_PASSWORD")

    # Pre-flight: SMTP failures are cryptic; a missing variable is a one-line
    # fix. Check all three required pieces (sender, app password, recipient)
    # before opening any connection.
    missing = [
        name
        for name, value in (
            ("AK_SMTP_USER", user),
            ("AK_SMTP_PASSWORD", password),
            ("AK_KINDLE_EMAIL", recipient),
        )
        if not value
    ]
    if missing:
        raise SendError(_missing_env_message(missing))

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
    except smtplib.SMTPAuthenticationError as exc:
        raise SendError(
            "SMTP send failed: login rejected "
            f"({exc.smtp_code}: {exc.smtp_error.decode(errors='replace')!r}) — "
            "check AK_SMTP_USER/AK_SMTP_PASSWORD; Gmail/Outlook require an app "
            "password (2FA), not your login password — see README 'Send to Kindle'"
        ) from exc
    except (OSError, smtplib.SMTPException) as exc:
        raise SendError(f"SMTP send failed: {exc}") from exc

    return recipient
