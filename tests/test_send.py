from __future__ import annotations

import os
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
def _clean_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no stray .env from the repo root
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
    monkeypatch.setenv("AK_KINDLE_EMAIL", "deven367@kindle.com")
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
    monkeypatch.setenv("AK_KINDLE_EMAIL", "deven367@kindle.com")
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
    with pytest.raises(SendError) as excinfo:
        send_epub(epub)
    msg = str(excinfo.value)
    for var in ("AK_SMTP_USER", "AK_SMTP_PASSWORD", "AK_KINDLE_EMAIL"):
        assert var in msg
    assert "missing: AK_SMTP_USER, AK_SMTP_PASSWORD, AK_KINDLE_EMAIL" in msg


def test_send_missing_recipient_raises(monkeypatch, epub):
    monkeypatch.setenv("AK_SMTP_USER", "me@gmail.com")
    monkeypatch.setenv("AK_SMTP_PASSWORD", "app-pass")
    with pytest.raises(SendError, match="missing: AK_KINDLE_EMAIL"):
        send_epub(epub)


def test_send_recipient_kwarg_satisfies_check(monkeypatch, epub):
    monkeypatch.setattr(send.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("AK_SMTP_USER", "me@gmail.com")
    monkeypatch.setenv("AK_SMTP_PASSWORD", "app-pass")
    recipient = send_epub(epub, recipient="reader@kindle.com")
    assert recipient == "reader@kindle.com"


def test_check_send_env_ok(monkeypatch):
    for var in send.REQUIRED_SEND_ENV:
        monkeypatch.setenv(var, "x")
    send.check_send_env()  # must not raise


def test_check_send_env_missing(monkeypatch):
    monkeypatch.setenv("AK_SMTP_USER", "me@gmail.com")
    with pytest.raises(SendError) as excinfo:
        send.check_send_env()
    assert "AK_SMTP_PASSWORD" in str(excinfo.value)
    assert "AK_KINDLE_EMAIL" in str(excinfo.value)


def test_send_oversize_raises(monkeypatch, tmp_path):
    big = tmp_path / "huge.epub"
    with open(big, "wb") as f:
        f.truncate(send.MAX_ATTACHMENT_BYTES + 1)
    monkeypatch.setenv("AK_KINDLE_EMAIL", "deven367@kindle.com")
    with pytest.raises(SendError, match="50 MB"):
        send_epub(big, smtp_user="me@gmail.com", smtp_password="app-pass")


def test_send_smtp_failure_raises(monkeypatch, epub):
    class BrokenSMTP(FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(send.smtplib, "SMTP", BrokenSMTP)
    monkeypatch.setenv("AK_KINDLE_EMAIL", "deven367@kindle.com")
    with pytest.raises(SendError) as excinfo:
        send_epub(epub, smtp_user="me@gmail.com", smtp_password="wrong")
    assert "SMTP send failed" in str(excinfo.value)
    assert "app password" in str(excinfo.value)  # hint points at the cause


def test_kindle_recipient_env(monkeypatch):
    monkeypatch.setenv("AK_KINDLE_EMAIL", "other@kindle.com")
    assert send.kindle_recipient() == "other@kindle.com"


def test_kindle_recipient_unset():
    assert send.kindle_recipient() is None


def test_load_env_file_parses(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "# comment line\n"
        "AK_SMTP_USER=me@gmail.com\n"
        'AK_SMTP_PASSWORD="app pass"\n'
        "export AK_KINDLE_EMAIL=reader@kindle.com\n"
        "MALFORMED_NO_EQUALS\n"
    )
    monkeypatch.chdir(tmp_path)
    send.load_env_file()
    assert os.environ["AK_SMTP_USER"] == "me@gmail.com"
    assert os.environ["AK_SMTP_PASSWORD"] == "app pass"
    assert os.environ["AK_KINDLE_EMAIL"] == "reader@kindle.com"


def test_load_env_file_does_not_override_shell(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("AK_SMTP_USER=from-file\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AK_SMTP_USER", "from-shell")
    send.load_env_file()
    assert os.environ["AK_SMTP_USER"] == "from-shell"


def test_load_env_file_missing_is_noop(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    send.load_env_file()  # no .env present: must not raise


def test_send_uses_env_file(monkeypatch, tmp_path, epub):
    monkeypatch.setattr(send.smtplib, "SMTP", FakeSMTP)
    (tmp_path / ".env").write_text(
        "AK_SMTP_USER=me@gmail.com\n"
        "AK_SMTP_PASSWORD=app-pass\n"
        "AK_KINDLE_EMAIL=reader@kindle.com\n"
    )
    monkeypatch.chdir(tmp_path)
    recipient = send_epub(epub)
    assert recipient == "reader@kindle.com"
    inst = FakeSMTP.instances[-1]
    assert inst.login_args == ("me@gmail.com", "app-pass")
