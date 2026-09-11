#!/usr/bin/env python3
"""
ARTC IoT Use Cases — Environment Setup + Model Training Job.

Runs as a CML Job (Job 1 of 2 per use case). Installs Python dependencies
for the selected use case, then trains the model(s) and writes the .pkl
artefacts so the downstream deploy job can start the CAI Application.

Upload this file to /home/cdsw/cai_integration/setup_iot_env.py

Use case is selected via the UC_ID environment variable:
  UC_ID=uc1  →  install UC1 deps, run iot_uc1_model/train_rul_model.py
  UC_ID=uc2  →  install UC2 deps, run iot_uc2_model/train_quality_model.py

Usage (as CML Job, script = cai_integration/setup_iot_env.py):
  Set env var UC_ID=uc1 or UC_ID=uc2 before running.

Usage (local):
  UC_ID=uc1 python setup_iot_env.py
  UC_ID=uc2 python setup_iot_env.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    """Locate project root (/home/cdsw) — works in CML and locally."""
    try:
        # When run as cai_integration/setup_iot_env.py, parent = cai_integration/, parent.parent = /home/cdsw
        return Path(__file__).resolve().parent.parent
    except NameError:
        for cand in ("/home/cdsw", os.getcwd()):
            if (Path(cand) / ".git").is_dir():
                return Path(cand).resolve()
        return Path("/home/cdsw")


REPO_ROOT = _repo_root()
# Scripts are uploaded to project root — iot_uc1_model/ and iot_uc2_model/ sit directly under /home/cdsw/
LAB_DIR = REPO_ROOT

UC_CONFIG = {
    "uc1": {
        "label": "UC1 — Predictive Maintenance (RUL)",
        "model_dir": LAB_DIR / "iot_uc1_model",
        "train_script": LAB_DIR / "iot_uc1_model" / "train_rul_model.py",
        "requirements": LAB_DIR / "iot_uc1_model" / "requirements.txt",
        "artefacts": ["rul_model.pkl", "feature_list.json"],
    },
    "uc2": {
        "label": "UC2 — Predictive Quality (defect rate + risk level)",
        "model_dir": LAB_DIR / "iot_uc2_model",
        "train_script": LAB_DIR / "iot_uc2_model" / "train_quality_model.py",
        "requirements": LAB_DIR / "iot_uc2_model" / "requirements.txt",
        "artefacts": ["quality_regressor.pkl", "quality_classifier.pkl",
                      "feature_list.json", "risk_encoder.json"],
    },
}


def run_command(cmd: str, cwd: str | None = None) -> bool:
    print(f"  $ {cmd}")
    try:
        result = subprocess.run(
            cmd, shell=True, cwd=cwd, check=True,
            capture_output=True, text=True,
        )
        if result.stdout.strip():
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"  ERROR: exit code {e.returncode}")
        if e.stdout.strip():
            print(e.stdout)
        if e.stderr.strip():
            print(e.stderr)
        return False


def install_deps(requirements: Path) -> bool:
    print(f"\n[1/2] Installing dependencies from {requirements.name} ...")
    if not requirements.is_file():
        print(f"  WARNING: {requirements} not found — skipping pip install")
        return True
    cmd = (
        f"{sys.executable} -m pip install -q "
        f"--upgrade-strategy only-if-needed "
        f"-r {requirements}"
    )
    ok = run_command(cmd)
    if ok:
        print("  Dependencies installed.")
    return ok


def train_model(train_script: Path, model_dir: Path, artefacts: list[str]) -> bool:
    print(f"\n[2/2] Training model — {train_script.name} ...")
    if not train_script.is_file():
        print(f"  ERROR: training script not found: {train_script}")
        return False

    ok = run_command(f"{sys.executable} {train_script}", cwd=str(model_dir))
    if not ok:
        return False

    print("\n  Artefact check:")
    all_present = True
    for name in artefacts:
        path = model_dir / name
        if path.is_file():
            size_kb = path.stat().st_size // 1024
            print(f"    ✓  {name}  ({size_kb} KB)")
        else:
            print(f"    ✗  {name}  MISSING")
            all_present = False

    return all_present


def main() -> None:
    uc_id = os.environ.get("UC_ID", "").lower().strip()
    if uc_id not in UC_CONFIG:
        print(f"ERROR: UC_ID must be 'uc1' or 'uc2' (got: '{uc_id}')")
        print("  Set the UC_ID environment variable before running this job.")
        raise SystemExit(1)

    cfg = UC_CONFIG[uc_id]

    print("=" * 60)
    print(f"  ARTC IoT Lab — Setup & Train")
    print(f"  {cfg['label']}")
    print("=" * 60)
    print(f"  Repo root   : {REPO_ROOT}")
    print(f"  Model dir   : {cfg['model_dir']}")
    print(f"  Train script: {cfg['train_script'].name}")
    print()

    steps = [
        ("dep install", lambda: install_deps(cfg["requirements"])),
        ("model train", lambda: train_model(
            cfg["train_script"], cfg["model_dir"], cfg["artefacts"]
        )),
    ]

    failed = []
    for label, fn in steps:
        if not fn():
            failed.append(label)

    print("\n" + "=" * 60)
    if failed:
        raise RuntimeError(
            f"Setup completed with failures: {', '.join(failed)}. "
            "Check logs above for details."
        )
    print(f"  {cfg['label']} — setup & training complete.")
    print(f"  Model artefacts written to: {cfg['model_dir']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
