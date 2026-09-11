#!/usr/bin/env python3
"""
Create/update CML jobs for the ARTC IoT Use Cases lab.

Upload this directory to /home/cdsw/cai_integration/ in your CML project.
Reads jobs_config.yaml from the same directory and creates or updates
four CML Jobs (two per use case) via the CML API v2.

Usage:
    python cai_integration/create_jobs.py --project-id <project_id>

Required env vars (auto-set inside CAI Workbench):
    CDSW_DOMAIN      — e.g. cai.your-cluster.example.com  (no https://)
    CDSW_APIV2_KEY   — CML API v2 key

Optional overrides:
    CML_HOST           — explicit host URL (takes precedence over CDSW_DOMAIN)
    CML_API_KEY        — explicit API key (takes precedence over CDSW_APIV2_KEY)
    RUNTIME_IDENTIFIER — override the runtime image for all jobs
"""

import argparse
import os
import sys
import yaml
import requests
from pathlib import Path
from typing import Dict, Optional, Any


class JobManager:

    def __init__(self) -> None:
        domain = os.environ.get("CDSW_DOMAIN", "")
        host_env = os.environ.get("CML_HOST", "")
        raw_host = host_env or (f"https://{domain}" if domain else "")
        self.cml_host = raw_host.rstrip("/")
        self.api_key = (os.environ.get("CML_API_KEY") or os.environ.get("CDSW_APIV2_KEY", "")).strip()

        if not self.cml_host or not self.api_key:
            print("Error: Missing required environment variables.")
            print("  Required: CDSW_DOMAIN + CDSW_APIV2_KEY  (auto-set in CAI Workbench)")
            print("  Override: CML_HOST + CML_API_KEY")
            sys.exit(1)

        self.api_url = f"{self.cml_host}/api/v2"
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _request(self, method: str, endpoint: str,
                 data: dict | None = None, params: dict | None = None
                 ) -> Optional[dict]:
        url = f"{self.api_url}/{endpoint.lstrip('/')}"
        try:
            resp = requests.request(
                method=method, url=url, headers=self.headers,
                json=data, params=params, timeout=30, verify=False,
            )
            if 200 <= resp.status_code < 300:
                return resp.json() if resp.text else {}
            print(f"  API error ({resp.status_code}): {resp.text[:300]}")
            return None
        except Exception as exc:
            print(f"  Request error: {exc}")
            return None

    def _load_config(self) -> Dict[str, Any]:
        config_path = Path(__file__).parent / "jobs_config.yaml"
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f)
            print(f"Loaded jobs config: {config_path}")
            return config
        except Exception as exc:
            print(f"Failed to load jobs config: {exc}")
            return {}

    def _runtime_identifier(self, project_id: str) -> Optional[str]:
        rid = os.environ.get("RUNTIME_IDENTIFIER")
        if rid:
            print(f"Runtime (env override): {rid[:80]}...")
            return rid

        result = self._request("GET", f"projects/{project_id}")
        if result:
            default_rt = (
                result.get("default_runtime_identifier")
                or result.get("runtime_identifier")
            )
            if default_rt:
                print(f"Runtime (project default): {default_rt[:80]}...")
                return default_rt

        runtimes = self._request("GET", "runtimes", params={
            "search_filter": '{"kernel":"Python 3.10","edition":"Standard"}',
            "page_size": 5,
        })
        if runtimes:
            items = runtimes.get("runtimes", [])
            if items:
                rid = items[0].get("runtime_identifier", "")
                print(f"Runtime (auto-selected): {rid[:80]}...")
                return rid

        # Hard-coded fallback — override with RUNTIME_IDENTIFIER env var if this image
        # is not available in your environment.
        fallback = (
            "docker.repository.cloudera.com/cloudera/cdsw/"
            "ml-runtime-pbj-jupyterlab-python3.10-standard:2026.04.1-b7"
        )
        print(f"Runtime (hardcoded fallback): {fallback}")
        print("  Override by setting: export RUNTIME_IDENTIFIER=<your-runtime-id>")
        return fallback

    def _list_jobs(self, project_id: str) -> Dict[str, str]:
        result = self._request("GET", f"projects/{project_id}/jobs")
        if result:
            jobs = {j.get("name", ""): j.get("id", "") for j in result.get("jobs", [])}
            print(f"  Found {len(jobs)} existing job(s)")
            return jobs
        return {}

    def _create_job(self, project_id: str, cfg: dict,
                    parent_job_id: str | None, runtime: str | None) -> Optional[str]:
        print(f"  Creating: {cfg['name']}")
        body: dict = {
            "name":    cfg["name"],
            "script":  cfg["script"],
            "cpu":     cfg.get("cpu", 2),
            "memory":  cfg.get("memory", 8),
            "timeout": cfg.get("timeout", 1200),
        }
        if runtime:
            body["runtime_identifier"] = runtime
        if parent_job_id:
            body["parent_job_id"] = parent_job_id
        env = cfg.get("environment", {})
        if env:
            body["environment"] = {k: str(v) for k, v in env.items()}

        result = self._request("POST", f"projects/{project_id}/jobs", data=body)
        if result:
            jid = result.get("id")
            print(f"    → created job_id={jid}")
            return jid
        print("    → FAILED to create")
        return None

    def _update_job(self, project_id: str, job_id: str, cfg: dict,
                    parent_job_id: str | None, runtime: str | None) -> bool:
        print(f"  Updating: {cfg['name']} (id={job_id})")
        body: dict = {
            "name":    cfg["name"],
            "script":  cfg["script"],
            "cpu":     cfg.get("cpu", 2),
            "memory":  cfg.get("memory", 8),
            "timeout": cfg.get("timeout", 1200),
        }
        if runtime:
            body["runtime_identifier"] = runtime
        if parent_job_id:
            body["parent_job_id"] = parent_job_id
        env = cfg.get("environment", {})
        if env:
            body["environment"] = {k: str(v) for k, v in env.items()}

        result = self._request("PATCH", f"projects/{project_id}/jobs/{job_id}", data=body)
        if result is not None:
            print(f"    → updated")
            return True
        print("    → FAILED to update")
        return False

    def run(self, project_id: str) -> bool:
        print("=" * 70)
        print("  ARTC IoT Lab — Create CML Jobs")
        print("=" * 70)
        print(f"  Project ID : {project_id}")
        print(f"  CML host   : {self.cml_host}")
        print()

        config = self._load_config()
        if not config:
            return False

        runtime   = self._runtime_identifier(project_id)
        existing  = self._list_jobs(project_id)
        jobs_cfg  = config.get("jobs", {})
        job_ids: Dict[str, str] = {}
        failed: list[str] = []

        print()
        print("Creating / Updating jobs")
        print("-" * 70)

        for key, cfg in jobs_cfg.items():
            name = cfg["name"]
            parent_id = None
            parent_key = cfg.get("parent_job_key")
            if parent_key and parent_key in job_ids:
                parent_id = job_ids[parent_key]

            if name in existing:
                ok = self._update_job(project_id, existing[name], cfg, parent_id, runtime)
                if ok:
                    job_ids[key] = existing[name]
                else:
                    failed.append(name)
            else:
                jid = self._create_job(project_id, cfg, parent_id, runtime)
                if jid:
                    job_ids[key] = jid
                else:
                    failed.append(name)

        print()
        print("=" * 70)
        if failed:
            print(f"FAILED: {len(failed)} of {len(jobs_cfg)} job(s):")
            for n in failed:
                print(f"  ✗  {n}")
            return False

        print(f"Done — {len(job_ids)} job(s) created/updated:")
        for key, jid in job_ids.items():
            cfg = jobs_cfg[key]
            parent = cfg.get("parent_job_key") or "—"
            print(f"  ✓  {cfg['name']:<45} id={jid}  parent={parent}")
        print()
        print("Run order:")
        print("  1. 'UC1 — Setup Env & Train RUL Model'      → trains rul_model.pkl")
        print("  2. 'UC1 — Deploy RUL Prediction App'         → starts CAI Application")
        print("  3. 'UC2 — Setup Env & Train Quality Models' → trains quality_*.pkl")
        print("  4. 'UC2 — Deploy Quality Prediction App'     → starts CAI Application")
        print()
        print("  Jobs 2 and 4 auto-trigger after their parent jobs succeed.")
        print("=" * 70)
        return True


def main() -> None:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    parser = argparse.ArgumentParser(
        description="Create or update CML jobs for the ARTC IoT Use Cases lab"
    )
    parser.add_argument("--project-id", required=True, help="CML project ID")
    args = parser.parse_args()

    try:
        manager = JobManager()
        sys.exit(0 if manager.run(args.project_id) else 1)
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
    except Exception as exc:
        print(f"\nUnexpected error: {exc}")
        import traceback; traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
