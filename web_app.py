"""Public deployment entry point: isolated sessions and Binance BTC/USDT live defaults."""

from pathlib import Path
import runpy
import sys
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

ROOT = Path(__file__).resolve().parent
sys.path[:] = [str(ROOT), *[path for path in sys.path if path != str(ROOT)]]
from checkout_bootstrap import ensure_checkout  # noqa: E402 -- prepare imports before runpy.

source_version = ensure_checkout(ROOT)
if get_script_run_ctx(suppress_warning=True) is not None:
    # Preserve AppTest and retained-script recovery without starting another runtime.
    runpy.run_path(
        str(ROOT / "app.py"),
        run_name="__main__",
        init_globals={"PUBLIC_DEPLOYMENT": True, "CHECKOUT_SOURCE_VERSION": source_version},
    )
else:
    from starlette.middleware import Middleware
    from starlette.middleware.gzip import GZipMiddleware
    from btc_analyzer.ui.pwa import InstallMetadata, routes

    app = st.App(
        ROOT / "app.py",
        routes=routes(),
        middleware=[
            Middleware(GZipMiddleware, minimum_size=1024, compresslevel=5),
            Middleware(InstallMetadata),
        ],
    )
    if __name__ == "__main__":
        app.run()
