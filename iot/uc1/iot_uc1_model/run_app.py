#!/usr/bin/env python3
"""
CAI Application entry point — UC1 RUL Prediction Service.

Upload this directory to /home/cdsw/iot_uc1_model/ in your CML project.
The CAI Application startup script should be: iot_uc1_model/run_app.py

Usage (local smoke test):
    python run_app.py
"""

import asyncio
import os
import subprocess
import sys
import threading
from pathlib import Path

PROJECT_ROOT = "/home/cdsw"
DEFAULT_APP_DIR = f"{PROJECT_ROOT}/iot_uc1_model"


def _resolve_app_dir() -> str:
    try:
        candidate = Path(__file__).parent
        if (candidate / "app.py").exists():
            return str(candidate)
    except NameError:
        pass
    for candidate in (
        os.environ.get("APP_DIR"),
        DEFAULT_APP_DIR,
    ):
        if candidate and Path(candidate, "app.py").exists():
            return str(candidate)
    raise RuntimeError("Could not locate app.py. Set APP_DIR or run from iot_uc1_model/.")


def _pip_install(app_dir: str) -> None:
    req = Path(app_dir) / "requirements.txt"
    cmd = [sys.executable, "-m", "pip", "install", "-q", "--upgrade-strategy", "only-if-needed"]
    if req.exists():
        cmd += ["-r", str(req)]
    else:
        cmd += ["fastapi", "uvicorn[standard]", "scikit-learn", "joblib", "numpy", "pandas", "requests", "pydantic"]
    subprocess.run(cmd, check=False)


def run_server() -> None:
    app_dir = _resolve_app_dir()
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)

    print("Installing dependencies...")
    _pip_install(app_dir)
    print("Dependencies ready.")

    from app import app  # noqa: E402
    import uvicorn

    host = os.environ.get("CDSW_APP_HOST", "127.0.0.1")
    port = int(os.environ.get("CDSW_APP_PORT", 8080))

    print("=" * 60)
    print("  UC1 — RUL Prediction Service")
    print("=" * 60)
    print(f"  App dir : {app_dir}")
    print(f"  Host    : {host}:{port}")
    print("-" * 60)
    print("  POST /predict  — predict remaining useful life")
    print("  GET  /health   — liveness check")
    print("=" * 60)
    print()
    print("  Run train_rul_model.py first to generate rul_model.pkl")

    config = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)

    def _serve() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())

    thread = threading.Thread(target=_serve, daemon=False)
    thread.start()
    thread.join()


if __name__ == "__main__":
    run_server()
