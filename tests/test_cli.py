from __future__ import annotations

import zipfile

from typer.testing import CliRunner

from archive_kindle_cli import __version__
from archive_kindle_cli.cli import app
from archive_kindle_cli.fetch import CaptchaBlocked, FetchError

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_module_main_entry():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "archive_kindle_cli", "version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == __version__


def test_convert_file_mode(tmp_path, article_html):
    src = tmp_path / "page.html"
    src.write_text(article_html)
    out = tmp_path / "out.epub"
    result = runner.invoke(
        app,
        [
            "convert",
            "--file",
            str(src),
            "--no-images",
            "-o",
            str(out),
            "https://example.com/politics/test-article",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert zipfile.is_zipfile(out)
    assert str(out) in result.stdout


def test_convert_fetch_success(monkeypatch, tmp_path, article_html):
    monkeypatch.setattr("archive_kindle_cli.cli.fetch_snapshot", lambda *a, **k: article_html)
    out = tmp_path / "out.epub"
    result = runner.invoke(
        app,
        ["convert", "--no-images", "-o", str(out), "--cache-dir", str(tmp_path / "c"),
         "https://archive.ph/Pxjvq"],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()


def test_convert_captcha_exit_2(monkeypatch):
    def blocked(*a, **k):
        raise CaptchaBlocked("challenge")

    monkeypatch.setattr("archive_kindle_cli.cli.fetch_snapshot", blocked)
    result = runner.invoke(
        app, ["convert", "https://archive.ph/Pxjvq", "--cache-dir", "/tmp/x"]
    )
    assert result.exit_code == 2
    assert "challenge" in result.output


def test_convert_bad_url_exit_1(monkeypatch):
    def bad(*a, **k):
        raise FetchError("not an archive.today snapshot URL")

    monkeypatch.setattr("archive_kindle_cli.cli.fetch_snapshot", bad)
    result = runner.invoke(
        app, ["convert", "https://example.com/x", "--cache-dir", "/tmp/x"]
    )
    assert result.exit_code == 1
    assert "error" in result.output.lower()


def test_convert_no_content_exit_1(monkeypatch):
    monkeypatch.setattr(
        "archive_kindle_cli.cli.fetch_snapshot",
        lambda *a, **k: "<html><body></body></html>",
    )
    result = runner.invoke(
        app, ["convert", "https://archive.ph/Pxjvq", "--cache-dir", "/tmp/x"]
    )
    assert result.exit_code == 1


def test_convert_empty_html_file_exit_1(tmp_path):
    src = tmp_path / "empty.html"
    src.write_text("<html></html>")
    result = runner.invoke(app, ["convert", "--file", str(src), "x"])
    assert result.exit_code == 1


def test_convert_send_success(monkeypatch, tmp_path, article_html):
    src = tmp_path / "page.html"
    src.write_text(article_html)
    out = tmp_path / "out.epub"
    sent = []

    def fake_send(path, **kwargs):
        sent.append(path)
        return "deven367@kindle.com"

    monkeypatch.setattr("archive_kindle_cli.cli.send_epub", fake_send)
    monkeypatch.setenv("AK_SMTP_USER", "me@gmail.com")
    monkeypatch.setenv("AK_SMTP_PASSWORD", "app-pass")
    monkeypatch.setenv("AK_KINDLE_EMAIL", "deven367@kindle.com")
    result = runner.invoke(
        app,
        [
            "convert",
            "--file", str(src),
            "--no-images",
            "-o", str(out),
            "--send",
            "https://example.com/politics/test-article",
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert sent == [out]
    assert "deven367@kindle.com" in result.output


def test_convert_send_failure_keeps_epub(monkeypatch, tmp_path, article_html):
    from archive_kindle_cli.send import SendError

    src = tmp_path / "page.html"
    src.write_text(article_html)
    out = tmp_path / "out.epub"

    def fail_send(path, **kwargs):
        raise SendError("SMTP send failed: connection refused")

    monkeypatch.setattr("archive_kindle_cli.cli.send_epub", fail_send)
    monkeypatch.setenv("AK_SMTP_USER", "me@gmail.com")
    monkeypatch.setenv("AK_SMTP_PASSWORD", "app-pass")
    monkeypatch.setenv("AK_KINDLE_EMAIL", "deven367@kindle.com")
    result = runner.invoke(
        app,
        [
            "convert",
            "--file", str(src),
            "--no-images",
            "-o", str(out),
            "--send",
            "https://example.com/politics/test-article",
        ],
    )
    assert result.exit_code == 1
    assert "connection refused" in result.output
    assert out.exists()  # EPUB is still saved locally


def test_convert_send_missing_env_fails_before_fetch(monkeypatch, tmp_path):
    monkeypatch.delenv("AK_SMTP_USER", raising=False)
    monkeypatch.delenv("AK_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("AK_KINDLE_EMAIL", raising=False)
    # isolate from any .env in the working directory (the loader reads CWD)
    monkeypatch.chdir(tmp_path)

    def boom(*a, **k):
        raise AssertionError("fetch must not run when send env is missing")

    monkeypatch.setattr("archive_kindle_cli.cli.fetch_snapshot", boom)
    result = runner.invoke(
        app,
        ["convert", "--send", "https://archive.ph/Pxjvq", "--cache-dir", "/tmp/x"],
    )
    assert result.exit_code == 1
    assert "AK_SMTP_USER" in result.output
    assert "AK_SMTP_PASSWORD" in result.output
    assert "AK_KINDLE_EMAIL" in result.output


def test_convert_send_config_from_env_file(monkeypatch, tmp_path, article_html):
    src = tmp_path / "page.html"
    src.write_text(article_html)
    out = tmp_path / "out.epub"
    (tmp_path / ".env").write_text(
        "AK_SMTP_USER=me@gmail.com\n"
        "AK_SMTP_PASSWORD=app-pass\n"
        "AK_KINDLE_EMAIL=deven367@kindle.com\n"
    )
    monkeypatch.chdir(tmp_path)
    sent = []

    def fake_send(path, **kwargs):
        sent.append(path)
        return "deven367@kindle.com"

    monkeypatch.setattr("archive_kindle_cli.cli.send_epub", fake_send)
    result = runner.invoke(
        app,
        [
            "convert",
            "--file", str(src),
            "--no-images",
            "-o", str(out),
            "--send",
            "https://example.com/politics/test-article",
        ],
    )
    assert result.exit_code == 0, result.output
    assert sent == [out]
