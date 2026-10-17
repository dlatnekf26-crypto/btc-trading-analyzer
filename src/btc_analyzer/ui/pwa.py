"""Same-origin install assets; market responses are never stored offline."""

from btc_analyzer.ui.browser_assets import browser_asset

from pathlib import Path

from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

ASSET_ROOT = Path(__file__).resolve().parents[3] / "pwa"
HEAD = b"""<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/app-assets/icon-192.png">
<meta name="theme-color" content="#ffffff">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Crypto Signal">
<meta name="apple-mobile-web-app-status-bar-style" content="default">"""


class InstallMetadata:
    """Add install metadata to the actual top-level document, before first paint."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/":
            return await self.app(scope, receive, send)
        start, chunks = None, []

        async def inject(message):
            nonlocal start
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                if message["status"] == 200 and b"text/html" in headers.get(b"content-type", b""):
                    start = message
                    return
            elif message["type"] == "http.response.body" and start is not None:
                chunks.append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                body = b"".join(chunks).replace(b"</head>", HEAD + b"</head>", 1)
                headers = [(k, v) for k, v in start["headers"] if k not in (b"content-length", b"etag")]
                start["headers"] = [*headers, (b"content-length", str(len(body)).encode())]
                await send(start)
                await send({"type": "http.response.body", "body": body})
                return
            await send(message)

        await self.app(scope, receive, inject)


async def manifest(_request):
    return JSONResponse(
        {
            "id": "/",
            "name": "Crypto Signal Lab",
            "short_name": "Crypto Signal",
            "lang": "ko",
            "description": "실시간 코인 차트와 근거를 함께 보는 시장 분석",
            "start_url": "/?source=pwa",
            "scope": "/",
            "display": "standalone",
            "background_color": "#ffffff",
            "theme_color": "#ffffff",
            "icons": [
                {
                    "src": f"/app-assets/icon-{size}.png",
                    "sizes": f"{size}x{size}",
                    "type": "image/png",
                    "purpose": "any maskable",
                }
                for size in (192, 512)
            ],
        },
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


async def worker(_request):
    return FileResponse(
        ASSET_ROOT / "service-worker.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


async def asset(request):
    name = request.path_params["name"]
    if name not in {"icon-192.png", "icon-512.png", "offline.html"}:
        return Response(status_code=404)
    return FileResponse(ASSET_ROOT / name, headers={"Cache-Control": "public, max-age=3600"})


def routes():
    return [
        Route("/manifest.webmanifest", manifest),
        Route("/service-worker.js", worker),
        Route("/app-assets/{name}", asset),
    ]


INSTALL_CONTROL = """<div class="btc-install" id="btc-pwa-install" hidden>
<button type="button">앱으로 설치 <span aria-hidden="true">↗</span></button>
<span class="btc-install-help" role="status"></span></div>"""

PWA_JS = browser_asset("install.js")
