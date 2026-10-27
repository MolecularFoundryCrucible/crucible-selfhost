"""Smoke test for a running Crucible installation, through its public address.

Usage:
    python scripts/selfhost_smoke.py --api-url http://localhost:8080/api/v3 --api-key KEY

KEY is a platform administrator's API key (`python -m app.cli admin create`). The test creates a
project, a sample, a dataset, and a second user, so run it against a throwaway installation, never
against one holding real data. Uses only the Python standard library. Exits 0 when every step
passes; otherwise prints the failing step and exits 1.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from uuid import uuid4


class StepFailed(Exception):
    pass


def request(base: str, method: str, path: str, key: str | None = None, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    call = urllib.request.Request(base.rstrip("/") + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(call, timeout=30) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    try:
        return status, json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return status, raw.decode(errors="replace")


def expect(step: str, condition: bool, detail: object = "") -> None:
    if not condition:
        raise StepFailed(f"{step}: {detail}")
    print(f"ok   {step}")


def run(base: str, key: str) -> None:
    status, ready = request(base, "GET", "/health/ready")
    expect("readiness", status == 200 and ready.get("status") == "ok" and ready["database"]["schema_state"] == "current", ready)

    status, _ = request(base, "GET", "/account/profile")
    expect("a request without a key is refused", status == 401, status)

    status, me = request(base, "GET", "/account/profile", key)
    expect("the administrator's key signs in", status == 200 and me.get("platform_role") == "admin", me)

    suffix = uuid4().hex[:8]
    status, project = request(base, "POST", "/projects", key, {"project_id": f"smoke-{suffix}", "organization": "Smoke test", "project_lead": me["username"]})
    expect("create a project", status == 200 and project.get("unique_id"), project)
    project_mfid = project["unique_id"]

    status, sample = request(base, "POST", "/samples", key, {"sample_name": f"smoke sample {suffix}", "project_mfid": project_mfid})
    expect("create a sample", status == 200 and sample.get("unique_id"), sample)
    status, dataset = request(base, "POST", "/datasets", key, {"dataset_name": f"smoke dataset {suffix}", "project_mfid": project_mfid})
    expect("create a dataset", status == 200 and dataset.get("unique_id"), dataset)
    sample_mfid, dataset_mfid = sample["unique_id"], dataset["unique_id"]

    status, linked = request(base, "POST", f"/datasets/{dataset_mfid}/samples/{sample_mfid}", key)
    expect("link the sample to the dataset", status == 200, linked)
    status, read = request(base, "GET", f"/datasets/{dataset_mfid}", key)
    expect("read the dataset back", status == 200 and read.get("dataset_name") == f"smoke dataset {suffix}", read)
    status, listed = request(base, "GET", f"/datasets?mfid={dataset_mfid}", key)
    items = listed.get("items", []) if isinstance(listed, dict) else listed
    expect("find the dataset by MFID", status == 200 and [item.get("unique_id") for item in items] == [dataset_mfid], listed)

    status, published = request(base, "PUT", f"/resources/{sample_mfid}/access/public", key)
    expect("make the sample public", status == 200, published)

    username = f"smoke{suffix}"
    status, user = request(base, "POST", "/users", key, {"user_info": {"first_name": "Smoke", "last_name": "Reader", "username": username}})
    expect("create a second user", status == 200, user)
    status, issued = request(base, "POST", f"/users/{username}/apikey", key)
    expect("issue the second user a key", status == 200 and issued.get("api_key"), issued)
    reader = issued["api_key"]

    status, seen = request(base, "GET", f"/samples/{sample_mfid}", reader)
    expect("another user can read the public sample", status == 200 and seen.get("unique_id") == sample_mfid, seen)
    status, hidden = request(base, "GET", f"/datasets/{dataset_mfid}", reader)
    expect("another user cannot read the private dataset", status in (403, 404), status)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--api-key", required=True)
    args = parser.parse_args()
    try:
        run(args.api_url, args.api_key)
    except StepFailed as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
