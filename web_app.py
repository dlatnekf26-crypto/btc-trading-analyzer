"""Public deployment entry point: isolated sessions and Binance BTC/USDT live defaults."""

from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parent
sys.path[:] = [str(ROOT), *[path for path in sys.path if path != str(ROOT)]]
from checkout_bootstrap import ensure_checkout  # noqa: E402 -- prepare imports before runpy.

source_version = ensure_checkout(ROOT)
runpy.run_path(
    str(ROOT / "app.py"),
    run_name="__main__",
    init_globals={"PUBLIC_DEPLOYMENT": True, "CHECKOUT_SOURCE_VERSION": source_version},
)
