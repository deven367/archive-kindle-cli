from __future__ import annotations

import smtplib

import pytest

from archive_kindle_cli import send
from archive_kindle_cli.send import SendError, send_epub


class FakeSMTP:
    """Records the SMTP conversation; no real network."""

    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.starttls_called = False
        self.login_args = None
        self.messages = []
        FakeSMTP.instances.append(self)

    def ehlo(self):
        pass

    def starttls(self):
        self.starttls_called = True

    def login(self, user, password):
        self.login_args = (user, password)

    def send_message(self, msg):
        self.messages.append(msg)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSMTPSSL(FakeSMTP):
    pass


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "AK_SMTP_USER",
        "AK_SMTP_PASSWORD",
        "AK_SMTP_HOST",
        "AK_SMTP_PORT",
        "AK_KINDLE_EMAIL",
    ):
        monkeypatch.delenv(var, raising=False)
    FakeSMTP.instances.clear()


@pytest.fixture
def epub(tmp_path):
    p = tmp_path / "article.epub"
    p.write_bytes(b"PK\x03\x04" + b"\x00" * 1000)
    return p


def test_send_success_starttls(monkeypatch, epub):
    monkeypatch.setattr(send.smtplib, "SMTP", FakeSMTP)
    recipient = send_epub(
        epub, smtp_user="me@gmail.com", smtp_password="app-pass"
    )
    assert recipient == "deven367@kindle.com"  # default recipient
    inst = FakeSMTP.instances[-1]
    assert inst.port == 587
    assert inst.starttls_called
    assert inst.login_args == ("me@gmail.com", "app-pass")

    msg = inst.messages[0]
    assert msg["To"] == "deven367@kindle.com"
    assert msg["From"] == "me@gmail.com"
    assert msg["Subject"] == "article"
    attachment = msg.get_payload()[0]
    assert attachment.get_filename() == "article.epub"
    assert attachment.get_content_type() == "application/epub+zip"
    assert attachment.get_payload(decode=True) == epub.read_bytes()


def test_send_port_465_uses_implicit_tls(monkeypatch, epub):
    monkeypatch.setattr(send.smtplib, "SMTP_SSL", FakeSMTPSSL)
    send_epub(
        epub,
        smtp_port=465,
        smtp_user="me@outlook.com",
        smtp_password="app-pass",
    )
    inst = FakeSMTPSSL.instances[-1]
    assert inst.port == 465
    assert not inst.starttls_called  # implicit TLS, no STARTTLS


def test_send_custom_recipient_and_env(monkeypatch, epub):
    monkeypatch.setattr(send.smtplib, "SMTP_SSL", FakeSMTPSSL)
    monkeypatch.setenv("AK_KINDLE_EMAIL", "reader@kindle.com")
    monkeypatch.setenv("AK_SMTP_HOST", "smtp.mail.me.com")
    monkeypatch.setenv("AK_SMTP_PORT", "465")
    recipient = send_epub(
        epub, smtp_user="me@icloud.com", smtp_password="app-pass"
    )
    assert recipient == "reader@kindle.com"
    inst = FakeSMTPSSL.instances[-1]
    assert inst.host == "smtp.mail.me.com"
    assert inst.port == 465


def test_send_missing_config_raises(epub):
    with pytest.raises(SendError, match="AK_SMTP_USER and AK_SMTP_PASSWORD"):
        send_epub(epub)


def test_send_oversize_raises(tmp_path):
    big = tmp_path / "huge.epub"
    with open(big, "wb") as f:
        f.truncate(send.MAX_ATTACHMENT_BYTES + 1)
    with pytest.raises(SendError, match="50 MB"):
        send_epub(big, smtp_user="me@gmail.com", smtp_password="app-pass")


def test_send_smtp_failure_raises(monkeypatch, epub):
    class BrokenSMTP(FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(send.smtplib, "SMTP", BrokenSMTP)
    with pytest.raises(SendError, match="SMTP send failed"):
        send_epub(epub, smtp_user="me@gmail.com", smtp_password="wrong")


def test_kindle_recipient_env(monkeypatch):
    monkeypatch.setenv("AK_KINDLE_EMAIL", "other@kindle.com")
    assert send.kindle_recipient() == "other@kindle.com"


def test_kindle_recipient_default():
    assert send.kindle_recipient() == "deven367@kindle.com"
