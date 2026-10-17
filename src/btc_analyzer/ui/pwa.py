"""Same-origin install assets; market responses are never stored offline."""

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

PWA_JS = r"""
const disposePwa=(()=>{
  let root,doc;try{root=window.parent;doc=root.document;}catch(_){return ()=>{};}
  const control=()=>doc.getElementById('btc-pwa-install');
  let prompt=null,valid=false,disposed=false,didInstall=false;
  const standalone=()=>root.matchMedia('(display-mode: standalone)').matches || root.navigator.standalone;
  function sync(){const node=control();if(node) node.hidden=!valid || didInstall || standalone();}
  function ready(event){event.preventDefault();prompt=event;sync();}
  async function click(event){
    if(!event.target.closest?.('#btc-pwa-install button'))return;
    if(prompt){const current=prompt;prompt=null;await current.prompt();await current.userChoice;sync();}
    else {const node=control()?.querySelector('.btc-install-help');if(node) node.textContent=/iPad|iPhone|iPod/.test(root.navigator.userAgent)?'Safari 공유 버튼 → 홈 화면에 추가':'브라우저 메뉴 → 앱 설치 또는 홈 화면에 추가';}
  }
  function installed(){didInstall=true;prompt=null;sync();}
  root.addEventListener('beforeinstallprompt',ready);root.addEventListener('appinstalled',installed);
  doc.addEventListener('click',click);
  // Traditional app.py also works; only enable installation on a PWA-capable entry.
  if(root.isSecureContext && 'serviceWorker' in root.navigator)
    root.fetch('/manifest.webmanifest',{cache:'no-cache'}).then(r=>r.ok && r.headers.get('content-type')?.includes('manifest+json')?r.json():null).then(data=>{
      if(disposed || data?.id!=='/')return;valid=true;sync();
      return root.navigator.serviceWorker.register('/service-worker.js',{scope:'/'});
    }).catch(()=>{});
  function dispose(){disposed=true;root.removeEventListener('beforeinstallprompt',ready);root.removeEventListener('appinstalled',installed);doc.removeEventListener('click',click);}
  dispose.sync=sync;return dispose;
})();
"""
