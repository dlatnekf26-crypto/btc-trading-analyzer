"""Install metadata and routes cannot leak arbitrary checkout files."""

import asyncio
import json
from types import SimpleNamespace

from btc_analyzer.ui.pwa import ASSET_ROOT, InstallMetadata, asset, manifest, worker


def test_manifest_has_same_origin_start_scope_and_real_maskable_icons():
    response = asyncio.run(manifest(None))
    data = json.loads(response.body)
    assert response.media_type == "application/manifest+json"
    assert data["start_url"] == "/?source=pwa" and data["scope"] == data["id"] == "/"
    assert data["display"] == "standalone"
    for icon in data["icons"]:
        assert (ASSET_ROOT / icon["src"].split("/")[-1]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        assert "maskable" in icon["purpose"]


def test_worker_uses_correct_mime_and_root_scope():
    response = asyncio.run(worker(None))
    assert response.media_type == "application/javascript"
    assert response.headers["service-worker-allowed"] == "/"
    assert response.headers["cache-control"] == "no-cache"
    assert response.path.is_file()


def test_asset_route_only_serves_explicit_public_files():
    for name in ("../app.py", "requirements.lock", "offline.html/../app.py", ".env", "secret.png"):
        response = asyncio.run(asset(SimpleNamespace(path_params={"name": name})))
        assert response.status_code == 404
    for name in ("icon-192.png", "icon-512.png", "offline.html"):
        response = asyncio.run(asset(SimpleNamespace(path_params={"name": name})))
        assert response.status_code == 200 and response.path.is_file()


def test_root_html_metadata_handles_streamed_body_and_keeps_other_responses():
    async def check(path, mime):
        messages = []

        async def app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", mime), (b"content-length", b"41"), (b"etag", b"old")],
                }
            )
            await send({"type": "http.response.body", "body": b"<html><head>", "more_body": True})
            await send({"type": "http.response.body", "body": b"</head><body>hello</body></html>"})

        async def send(message):
            messages.append(message)

        await InstallMetadata(app)({"type": "http", "path": path}, None, send)
        return messages

    messages = asyncio.run(check("/", b"text/html"))
    body = b"".join(m.get("body", b"") for m in messages)
    headers = dict(messages[0]["headers"])
    assert body.count(b'rel="manifest"') == 1 and b"hello" in body
    assert int(headers[b"content-length"]) == len(body) and b"etag" not in headers
    for path, mime in (("/other", b"text/html"), ("/", b"application/json")):
        original = asyncio.run(check(path, mime))
        assert len(original) == 3 and b"manifest" not in b"".join(m.get("body", b"") for m in original)
