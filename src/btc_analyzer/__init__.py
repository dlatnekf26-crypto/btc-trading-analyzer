"""BTC research application. No live order execution capability."""

import hashlib as _hashlib
from pathlib import Path as _Path


def _source_signature() -> str:
    """Record the source generation when the package is actually imported."""
    package = _Path(__file__).resolve().parent
    digest = _hashlib.sha256()
    for path in sorted(package.rglob("*.py")):
        digest.update(path.relative_to(package).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


__checkout_signature__ = _source_signature()
