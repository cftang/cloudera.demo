#!/usr/bin/env python3
"""
Deploy UC2 Quality Prediction Service as a CAI Application.

Run as a CAI Job. Creates or updates the application via CDSW API v2.

Required environment variables (auto-set in CAI Workbench):
  CDSW_APIV2_KEY, CDSW_DOMAIN, CDSW_PROJECT_ID

Optional:
  app_suffix   — deploy side-by-side with a custom name suffix
  APP_SCRIPT   — override startup script path
"""

import os
import sys

import requests
import urllib3

BASE_APP_NAME = "UC2 Quality Prediction Service"
PROJECT_ROOT = "/home/cdsw"
DEFAULT_APP_SCRIPT = f"{PROJECT_ROOT}/iot_uc2_model/run_app.py"
RUNTIME_IMAGE = (
    "docker.repository.cloudera.com/cloudera/cdsw/"
    "ml-runtime-pbj-jupyterlab-python3.10-standard:2026.04.1-b7"
)


def get_app_name() -> str:
    suffix = os.environ.get("app_suffix", "").strip()
    return f"{BASE_APP_NAME} - {suffix}" if suffix else BASE_APP_NAME


def get_subdomain(project_id: str) -> str:
    suffix = os.environ.get("app_suffix", "").strip()
    base = f"uc2-quality-{project_id.lower()}"
    return f"uc2-quality-{suffix.lower()}-{project_id.lower()}" if suffix else base


def main() -> None:
    print("=" * 60)
    print("  Deploy UC2 Quality Prediction Service as CAI Application")
    print("=" * 60)

    api_key = os.environ.get("CDSW_APIV2_KEY")
    domain = os.environ.get("CDSW_DOMAIN")
    project_id = os.environ.get("CDSW_PROJECT_ID")

    if not all([api_key, domain, project_id]):
        print("Error: CDSW_APIV2_KEY, CDSW_DOMAIN, CDSW_PROJECT_ID are required (auto-set in CAI)")
        sys.exit(1)

    if not domain.startswith(("http://", "https://")):
        domain = f"https://{domain}"

    app_script = os.environ.get("APP_SCRIPT", DEFAULT_APP_SCRIPT)
    app_name = get_app_name()
    subdomain = get_subdomain(project_id)

    print(f"  Domain     : {domain}")
    print(f"  Project ID : {project_id}")
    print(f"  App Name   : {app_name}")
    print(f"  Subdomain  : {subdomain}")
    print()

    client = requests.Session()
    client.headers.update({"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    client.trust_env = False
    client.verify = False
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    apps_url = f"{domain}/api/v2/projects/{project_id}/applications"
    app_config = {
        "name": app_name,
        "description": "UC2 Predictive Quality Management — defect rate prediction REST endpoint for Agent Studio",
        "subdomain": subdomain,
        "script": app_script,
        "kernel": "python3",
        "cpu": 2,
        "memory": 4,
        "bypass_authentication": True,
        "runtime_identifier": RUNTIME_IMAGE,
        "environment": {
            "app_suffix": os.environ.get("app_suffix", ""),
            "APP_DIR": os.path.dirname(app_script),
        },
    }

    try:
        resp = client.get(apps_url)
        resp.raise_for_status()
        existing = next(
            (a for a in resp.json().get("applications", []) if a.get("name") == app_name),
            None,
        )

        if existing:
            app_id = existing["id"]
            print(f"Updating existing application: {app_id}")
            client.patch(f"{apps_url}/{app_id}", json=app_config).raise_for_status()
            client.post(f"{apps_url}/{app_id}/restart").raise_for_status()
            print("Application updated and restarted.")
        else:
            print("Creating new application...")
            resp = client.post(apps_url, json=app_config)
            resp.raise_for_status()
            app_id = resp.json().get("id")
            print(f"Application created: {app_id}")

        print()
        print("=" * 60)
        print("  Deployment Complete!")
        print("=" * 60)
        print(f"  App URL : {domain}/{subdomain}")
        print()
        print("  Test the endpoint:")
        print(f'  curl -X POST {domain}/{subdomain}/predict \\')
        print('       -H "Content-Type: application/json" \\')
        print('       -d \'{"machine_id":"CNC-01","process_type":"cnc",')
        print('             "vibration_rms":2.1,"temperature":52.3,"sound_db":82.0}\'')

    except requests.HTTPError as e:
        print(f"HTTP Error {e.response.status_code}: {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
