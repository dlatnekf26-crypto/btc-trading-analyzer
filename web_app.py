"""Public deployment entry point: isolated anonymous sessions, Upbit live defaults."""

from pathlib import Path
import runpy

runpy.run_path(
    str(Path(__file__).with_name("app.py")),
    run_name="__main__",
    init_globals={"PUBLIC_DEPLOYMENT": True},
)
