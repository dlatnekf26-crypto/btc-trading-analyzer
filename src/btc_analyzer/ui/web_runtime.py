"""Anonymous web sessions use private temporary storage and bounded research jobs."""

from collections.abc import Mapping, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore
from typing import Iterator


@dataclass(frozen=True)
class RuntimePaths:
    public: bool
    database: Path
    market_cache: Path


def runtime_paths(state: MutableMapping, environ: Mapping[str, str]) -> RuntimePaths:
    """Keep all private tables out of the shared public candle cache.

    The temporary directory owner lives in server-side Streamlit session state.
    Its finalizer removes files after the session is released. Neither URL query
    parameters nor browser-supplied identifiers select another user's directory.
    """
    if environ.get("BTC_APP_MODE", "local").lower() != "public":
        database = Path(environ.get("BTC_DB_PATH", "data/analyzer.sqlite3"))
        return RuntimePaths(False, database, database)
    root = Path(environ.get("BTC_WEB_DATA_DIR", "data/web"))
    sessions = root / "sessions"
    sessions.mkdir(parents=True, exist_ok=True, mode=0o700)
    owner = state.get("_btc_private_storage")
    if not isinstance(owner, TemporaryDirectory):
        owner = TemporaryDirectory(prefix="session-", dir=sessions)
        state["_btc_private_storage"] = owner
    return RuntimePaths(True, Path(owner.name) / "analyzer.sqlite3", root / "market-cache.sqlite3")


class ResearchBusy(RuntimeError):
    """Another visitor is already using the server's research worker."""


class ResearchGate:
    """Bound concurrent expensive work without sharing personal results."""

    def __init__(self) -> None:
        self._semaphore = BoundedSemaphore(1)

    @contextmanager
    def job(self) -> Iterator[None]:
        if not self._semaphore.acquire(blocking=False):
            raise ResearchBusy("서버에서 다른 계산을 처리하고 있습니다. 잠시 후 다시 실행하세요.")
        try:
            yield
        finally:
            self._semaphore.release()
