#!/usr/bin/env python3
"""
Run ChromaDB vector database server as a CAI Application.

Installs ChromaDB via pip and starts the HTTP server, storing data persistently
in /home/cdsw/chroma_data_<app_suffix>.

Each app_suffix gets its own isolated storage directory.
"""

import os
import sys
import subprocess
from pathlib import Path


APP_SUFFIX = os.environ.get("app_suffix", "default")
CHROMA_DATA_PATH = os.environ.get("CHROMA_DATA_PATH", f"/home/cdsw/chroma_data_{APP_SUFFIX}")
CHROMA_PORT = os.environ.get("CDSW_APP_PORT", "8100")
CHROMA_HOST = "127.0.0.1"


def install_chromadb():
    """Install ChromaDB and its HTTP server dependencies.

    chromadb is often present in the CAI runtime but without fastapi/uvicorn,
    which are optional extras needed to run the server. Always install them.
    """
    try:
        import chromadb
        print(f"ChromaDB already installed: {chromadb.__version__}")
    except ImportError:
        print("Installing ChromaDB...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "chromadb", "--quiet"],
            check=True
        )
        print("ChromaDB installed.")

    # Always ensure the HTTP server dependencies are present — they are optional
    # extras not guaranteed to be installed alongside chromadb in a CAI runtime.
    print("Ensuring server dependencies (fastapi, uvicorn, opentelemetry)...")
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "fastapi",
            "uvicorn[standard]",
            "opentelemetry-api",
            "opentelemetry-sdk",
            "opentelemetry-instrumentation-fastapi",
            "--upgrade-strategy", "only-if-needed",
            "--quiet",
        ],
        check=True
    )
    print("Server dependencies ready.")


def setup_data_directory() -> str:
    """Create persistent data directory."""
    data_path = Path(CHROMA_DATA_PATH)
    data_path.mkdir(parents=True, exist_ok=True)
    print(f"Data directory: {data_path}")
    return str(data_path)


def run_chroma(data_path: str):
    """Start ChromaDB HTTP server in a dedicated thread with its own event loop.

    CAI Applications run inside a Jupyter kernel that already owns an asyncio
    event loop. uvicorn.run() cannot start a second loop in the same thread,
    so we spin up a new thread with its own isolated loop to avoid the conflict.
    """
    import asyncio
    import threading
    import chromadb
    import chromadb.server.fastapi as _fastapi
    import uvicorn

    print()
    print("=" * 60)
    print(f"  ChromaDB Vector Database Server")
    print(f"  Version : {chromadb.__version__}")
    print(f"  Host    : {CHROMA_HOST}:{CHROMA_PORT}")
    print(f"  Data    : {data_path}")
    print("=" * 60)
    print()

    settings = chromadb.config.Settings(
        is_persistent=True,
        persist_directory=data_path,
        anonymized_telemetry=False,
    )
    chroma_server = _fastapi.FastAPI(settings)
    config = uvicorn.Config(
        chroma_server.app(),
        host=CHROMA_HOST,
        port=int(CHROMA_PORT),
        log_level="info",
    )
    server = uvicorn.Server(config)

    def _serve():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.serve())

    thread = threading.Thread(target=_serve, daemon=False)
    thread.start()
    thread.join()


def main():
    print()
    print("=" * 60)
    print("  ChromaDB Vector Database - CAI Application")
    print("=" * 60)
    print()

    try:
        install_chromadb()
        data_path = setup_data_directory()
        run_chroma(data_path)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
