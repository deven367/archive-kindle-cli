from __future__ import annotations

import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image

from archive_kindle_cli.extract import ImageRef
from archive_kindle_cli.images import ImageFetchError, download_images, _normalize


def _png_bytes(size=(40, 30), mode="RGB", fmt="PNG") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, (200, 30, 30)).save(buf, fmt)
    return buf.getvalue()


def _webp_bytes(size=(40, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 200, 10)).save(buf, "WEBP")
    return buf.getvalue()


def _ref(url_or_path: str, idx: int = 0) -> ImageRef:
    return ImageRef(src=url_or_path, alt="", placeholder=f"images/{idx:04d}")


def test_normalize_png_passthrough():
    data = _png_bytes()
    out, mime = _normalize(data)
    assert mime == "image/png"
    assert out == data


def test_normalize_webp_to_jpeg():
    out, mime = _normalize(_webp_bytes())
    assert mime == "image/jpeg"
    with Image.open(io.BytesIO(out)) as im:
        assert im.format == "JPEG"


def test_normalize_rgba_png_to_jpeg():
    out, mime = _normalize(_png_bytes(mode="RGBA"))
    assert mime == "image/jpeg"


def test_normalize_corrupt_raises():
    import pytest

    with pytest.raises(ImageFetchError):
        _normalize(b"this is not an image at all")


def test_local_file_fallback(tmp_path, cache_dir):
    (tmp_path / "files").mkdir()
    img = tmp_path / "files" / "photo.webp"
    img.write_bytes(_webp_bytes(size=(800, 600)))
    refs = [_ref("./files/photo.webp")]
    assets, cover = download_images(
        refs, cache_dir=cache_dir, local_base=tmp_path
    )
    assert len(assets) == 1
    asset = assets["images/0000"]
    assert asset.filename == "images/img_0000.jpg"
    assert asset.mime == "image/jpeg"
    assert asset.width == 800
    assert cover is not None


def test_local_file_missing_skipped(tmp_path, cache_dir):
    refs = [_ref("./files/nope.webp")]
    assets, cover = download_images(refs, cache_dir=cache_dir, local_base=tmp_path)
    assert assets == {}
    assert cover is None


def test_dedupe_by_content(tmp_path, cache_dir):
    (tmp_path / "files").mkdir()
    img = tmp_path / "files" / "a.webp"
    img.write_bytes(_webp_bytes(size=(800, 600)))
    refs = [_ref("./files/a.webp", 0), _ref("./files/a.webp", 1)]
    assets, _ = download_images(refs, cache_dir=cache_dir, local_base=tmp_path)
    assert len(assets) == 2
    filenames = {a.filename for a in assets.values()}
    assert len(filenames) == 1  # one physical file, both placeholders mapped


def test_logo_sized_image_filtered(tmp_path, cache_dir):
    (tmp_path / "files").mkdir()
    img = tmp_path / "files" / "logo.webp"
    img.write_bytes(_webp_bytes(size=(460, 140)))
    assets, cover = download_images(
        [_ref("./files/logo.webp")], cache_dir=cache_dir, local_base=tmp_path
    )
    assert assets == {}
    assert cover is None


def test_no_images_flag(cache_dir):
    assets, cover = download_images([], cache_dir=cache_dir, no_images=True)
    assert assets == {} and cover is None


def test_max_images_cap(tmp_path, cache_dir):
    (tmp_path / "files").mkdir()
    for i in range(3):
        p = tmp_path / "files" / f"img{i}.webp"
        p.write_bytes(_webp_bytes(size=(800, 600)))
    refs = [_ref(f"./files/img{i}.webp", i) for i in range(3)]
    assets, _ = download_images(
        refs, cache_dir=cache_dir, local_base=tmp_path, max_images=2
    )
    assert len(assets) == 2


def test_http_download(cache_dir):
    body = _webp_bytes(size=(800, 600))

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "image/webp")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):  # noqa: A003
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        assets, cover = download_images(
            [_ref(f"http://127.0.0.1:{port}/pic.webp")],
            cache_dir=cache_dir,
            referer="https://example.com/",
        )
        assert len(assets) == 1
        assert assets["images/0000"].mime == "image/jpeg"
        assert cover is not None
    finally:
        server.shutdown()


def test_http_404_skipped(cache_dir):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):  # noqa: A003
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    try:
        assets, _ = download_images(
            [_ref(f"http://127.0.0.1:{port}/missing.jpg")], cache_dir=cache_dir
        )
        assert assets == {}
    finally:
        server.shutdown()
