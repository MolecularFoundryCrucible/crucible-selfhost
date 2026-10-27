"""Smoke test for a running Crucible installation, through its public address.

Usage:
    CRUCIBLE_API_URL=http://localhost:8080/api/v3 CRUCIBLE_API_KEY=KEY python scripts/selfhost_smoke.py

or with --api-url and --api-key. KEY is a platform administrator's API key
(`python -m app.cli admin create`). The test creates a project, a sample, a dataset, and a second
user, so run it against a throwaway installation, never against one holding real data. Uses only
the Python standard library. Exits 0 when every step passes; otherwise prints the failing step and
exits 1.
"""
import argparse
import json
import os
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
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        raise StepFailed(f"{method} {path}: cannot reach the server ({error})") from None
    try:
        return status, json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return status, raw.decode(errors="replace")


def field(body: object, *keys: str) -> object:
    for key in keys:
        if not isinstance(body, dict):
            return None
        body = body.get(key)
    return body


def expect(step: str, condition: bool, detail: object = "") -> None:
    if not condition:
        raise StepFailed(f"{step}: {detail}")
    print(f"ok   {step}", flush=True)


def run(base: str, key: str) -> None:
    status, ready = request(base, "GET", "/health/ready")
    expect("readiness", status == 200 and field(ready, "status") == "ok" and field(ready, "database", "schema_state") == "current", ready)

    status, _ = request(base, "GET", "/account/profile")
    expect("a request without a key is refused", status == 401, status)

    status, me = request(base, "GET", "/account/profile", key)
    expect("the administrator's key signs in", status == 200 and field(me, "platform_role") == "admin", me)

    suffix = uuid4().hex[:8]
    status, project = request(base, "POST", "/projects", key, {"project_id": f"smoke-{suffix}", "organization": "Smoke test", "project_lead": field(me, "username")})
    expect("create a project", status == 200 and field(project, "unique_id"), project)
    project_mfid = field(project, "unique_id")

    status, sample = request(base, "POST", "/samples", key, {"sample_name": f"smoke sample {suffix}", "project_mfid": project_mfid})
    expect("create a sample", status == 200 and field(sample, "unique_id"), sample)
    status, dataset = request(base, "POST", "/datasets", key, {"dataset_name": f"smoke dataset {suffix}", "project_mfid": project_mfid})
    expect("create a dataset", status == 200 and field(dataset, "unique_id"), dataset)
    sample_mfid, dataset_mfid = field(sample, "unique_id"), field(dataset, "unique_id")

    status, linked = request(base, "POST", f"/datasets/{dataset_mfid}/samples/{sample_mfid}", key)
    expect("link the sample to the dataset", status == 200, linked)
    status, read = request(base, "GET", f"/datasets/{dataset_mfid}", key)
    expect("read the dataset back", status == 200 and field(read, "dataset_name") == f"smoke dataset {suffix}", read)
    status, listed = request(base, "GET", f"/datasets?mfid={dataset_mfid}", key)
    items = field(listed, "items") if isinstance(listed, dict) else listed
    expect("find the dataset by MFID", status == 200 and isinstance(items, list) and [field(item, "unique_id") for item in items] == [dataset_mfid], listed)

    username = f"smoke{suffix}"
    status, user = request(base, "POST", "/users", key, {"user_info": {"first_name": "Smoke", "last_name": "Reader", "username": username}})
    expect("create a second user", status == 200, user)
    status, issued = request(base, "POST", f"/users/{username}/apikey/regenerate", key)
    expect("issue the second user a key", status == 200 and field(issued, "api_key"), issued)
    reader = field(issued, "api_key")

    status, _ = request(base, "GET", f"/samples/{sample_mfid}", reader)
    expect("another user cannot read the sample while it is private", status in (403, 404), status)
    status, published = request(base, "PUT", f"/resources/{sample_mfid}/access/public", key)
    expect("make the sample public", status == 200, published)
    status, seen = request(base, "GET", f"/samples/{sample_mfid}", reader)
    expect("another user can read the public sample", status == 200 and field(seen, "unique_id") == sample_mfid, seen)
    status, _ = request(base, "GET", f"/datasets/{dataset_mfid}", reader)
    expect("another user cannot read the private dataset", status in (403, 404), status)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api-url", default=os.getenv("CRUCIBLE_API_URL"))
    parser.add_argument("--api-key", default=os.getenv("CRUCIBLE_API_KEY"), help="Prefer the CRUCIBLE_API_KEY environment variable, which keeps the key off the command line")
    args = parser.parse_args()
    if not args.api_url or not args.api_key:
        parser.error("give the API URL and an administrator's key (--api-url and --api-key, or CRUCIBLE_API_URL and CRUCIBLE_API_KEY)")
    try:
        run(args.api_url, args.api_key)
    except StepFailed as error:
        print(f"FAIL {error}", file=sys.stderr, flush=True)
        return 1
    print("smoke test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
