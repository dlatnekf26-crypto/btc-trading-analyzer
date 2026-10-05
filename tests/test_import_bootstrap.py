"""Isolated process regressions for stale imports in a long-running Cloud host."""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(program: str, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys\nfrom pathlib import Path\nroot=Path(sys.argv[1])\nsys.path.insert(0,str(root))\n"
            + program,
            str(ROOT),
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_reported_stale_candles_error_recovers_in_actual_public_app(tmp_path):
    result = subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts/check_deployment.py")],
        cwd=tmp_path,
        env={**os.environ, "BTC_CHECK_STALE_IMPORTS": "1"},
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "retained legacy candles recovered" in result.stdout


def test_legacy_package_and_orphan_children_are_all_evicted(tmp_path):
    run(
        """
from types import ModuleType
from checkout_bootstrap import ensure_checkout
legacy = ModuleType('btc_analyzer')
legacy.__file__ = str(root/'src/btc_analyzer/__init__.py')
legacy.__path__ = [str(root/'src/btc_analyzer')]
child = ModuleType('btc_analyzer.orphan')
sys.modules['btc_analyzer'] = legacy
sys.modules['btc_analyzer.orphan'] = child
ensure_checkout(root)
import btc_analyzer
from btc_analyzer.candles import candle_boundary
assert btc_analyzer is not legacy
assert 'btc_analyzer.orphan' not in sys.modules
""",
        tmp_path,
    )


def test_source_change_with_identical_size_and_mtime_reloads_actual_config(tmp_path):
    run(
        """
import os, shutil
from checkout_bootstrap import ensure_checkout
copy = Path(sys.argv[2])/'checkout'
shutil.copytree(root/'src', copy/'src')
before = ensure_checkout(copy)
from btc_analyzer.config import RiskConfig
assert RiskConfig().capital == 10000
path = copy/'src/btc_analyzer/config.py'
old_stat = path.stat()
old = path.read_text()
new = old.replace('capital: float = 10_000.0', 'capital: float = 20_000.0')
assert new != old and len(new) == len(old)
path.write_text(new)
os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
after = ensure_checkout(copy)
from btc_analyzer.config import RiskConfig as NewRiskConfig
assert after != before and NewRiskConfig is not RiskConfig
assert NewRiskConfig().capital == 20000
""",
        tmp_path,
    )


def test_loaded_foreign_copy_is_replaced_even_if_source_path_already_exists(tmp_path):
    run(
        """
import shutil
from checkout_bootstrap import ensure_checkout
copy = Path(sys.argv[2])/'foreign'
shutil.copytree(root/'src', copy/'src')
ensure_checkout(copy)
import btc_analyzer as foreign
sys.path.append(str(root/'src'))
ensure_checkout(root)
import btc_analyzer as current
assert current is not foreign
assert Path(current.__file__).resolve() == root/'src/btc_analyzer/__init__.py'
assert sys.path[0] == str(root/'src')
assert sys.path.count(str(root/'src')) == 1
""",
        tmp_path,
    )


def test_unchanged_generation_keeps_classes_and_cached_work(tmp_path):
    run(
        """
import streamlit as st
from checkout_bootstrap import ensure_checkout
signature = ensure_checkout(root)
from btc_analyzer.config import AppConfig
import btc_analyzer
counter = [0]
@st.cache_data(show_spinner=False)
def cached():
    counter[0] += 1
    return counter[0]
assert cached() == 1
for _ in range(3):
    assert ensure_checkout(root) == signature
    from btc_analyzer.config import AppConfig as SameConfig
    assert SameConfig is AppConfig and cached() == 1
btc_analyzer.__checkout_signature__ = 'previous-release'
ensure_checkout(root)
assert cached() == 2
from btc_analyzer.config import AppConfig as NewConfig
assert NewConfig is not AppConfig
assert ensure_checkout(root) == signature and cached() == 2
""",
        tmp_path,
    )


def test_watcher_eviction_cannot_resurrect_old_bytecode_or_cached_results(tmp_path):
    run(
        """
import os, shutil, streamlit as st
from checkout_bootstrap import ensure_checkout
copy = Path(sys.argv[2])/'watched'
shutil.copytree(root/'src', copy/'src')
ensure_checkout(copy)
@st.cache_data(show_spinner=False)
def capital():
    from btc_analyzer.config import RiskConfig
    return RiskConfig().capital
assert capital() == 10000
path = copy/'src/btc_analyzer/config.py'
previous = path.stat()
path.write_text(path.read_text().replace('capital: float = 10_000.0', 'capital: float = 20_000.0'))
os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
for name in list(sys.modules):
    if name == 'btc_analyzer' or name.startswith('btc_analyzer.'):
        sys.modules.pop(name)
ensure_checkout(copy)
assert capital() == 20000
""",
        tmp_path,
    )
