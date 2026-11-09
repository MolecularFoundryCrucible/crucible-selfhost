"""Smoke test for a running Crucible installation, through its public address.

Usage:
    CRUCIBLE_API_URL=http://localhost:8080/api/v3 CRUCIBLE_API_KEY=KEY python scripts/selfhost_smoke.py

or with --api-url and --api-key. KEY is a platform administrator's API key
(`python -m app.cli admin create`). The test creates a project, a sample, a dataset with an uploaded
and then replaced file, a second user and a service account, so run it against a throwaway installation, never against
one holding real data. Uses only the Python standard library. Exits 0 when every step passes;
otherwise prints the failing step and exits 1.
"""
import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from uuid import uuid4

# CRC32C (Castagnoli), which the standard library lacks; enough for the small test file.
_CRC32C_TABLE = []
for _byte in range(256):
    _value = _byte
    for _ in range(8):
        _value = (_value >> 1) ^ 0x82F63B78 if _value & 1 else _value >> 1
    _CRC32C_TABLE.append(_value)


class StepFailed(Exception):
    pass


def crc32c(data: bytes) -> str:
    value = 0xFFFFFFFF
    for byte in data:
        value = _CRC32C_TABLE[(value ^ byte) & 0xFF] ^ (value >> 8)
    return base64.b64encode((value ^ 0xFFFFFFFF).to_bytes(4, "big")).decode()


def fetch(method: str, url: str, data: bytes | None = None, headers: dict | None = None) -> tuple[int, bytes, dict]:
    call = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(call, timeout=60) as response:
            return response.status, response.read(), {name.lower(): value for name, value in response.headers.items()}
    except urllib.error.HTTPError as error:
        return error.code, error.read(), {name.lower(): value for name, value in error.headers.items()}
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        raise StepFailed(f"{method} {url.split('?')[0]}: cannot reach the server ({error})") from None


def request(base: str, method: str, path: str, key: str | None = None, body: dict | None = None, headers: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {**({"Content-Type": "application/json"} if data is not None else {}), **(headers or {})}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    status, raw, _ = fetch(method, base.rstrip("/") + path, data, headers)
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


def upload(base: str, key: str, dataset_mfid: str, data: bytes, step: str, start: str, start_body: dict) -> dict:
    """Upload data the way clients do: signed part URLs straight to the store, with the headers the
    API returns, then completion through the API."""
    digest = hashlib.sha256(data).hexdigest()
    status, started = request(base, "POST", start, key, {**start_body, "size": len(data), "sha256_hash": digest}, {"Idempotency-Key": uuid4().hex})
    expect(f"{step}: start", status == 200 and field(started, "state") == "uploading" and field(started, "part_count") == 1, started)
    upload_id = field(started, "upload_id")
    status, signed = request(base, "POST", f"/datasets/{dataset_mfid}/upload/multipart/{upload_id}/parts", key, {"parts": [{"part_number": 1, "crc32c": crc32c(data)}]})
    parts = field(signed, "parts")
    expect(f"{step}: sign the part", status == 200 and isinstance(parts, list) and len(parts) == 1, signed)
    part = parts[0]
    headers = {name: value for name, value in part["headers"].items() if name.lower() != "content-length"}
    status, body, _ = fetch("PUT", part["url"], data, headers)
    expect(f"{step}: send the part to its signed URL", status == 200, body[:300])
    status, file = request(base, "POST", f"/datasets/{dataset_mfid}/upload/multipart/complete", key, {"upload_id": upload_id, "sha256_hash": digest, "crc32c": crc32c(data)})
    expect(f"{step}: complete", status == 200 and field(file, "size") == len(data), file)
    return file


def download(base: str, key: str, file_mfid: str, data: bytes, step: str) -> None:
    status, link = request(base, "GET", f"/files/{file_mfid}/download_link", key)
    expect(f"{step}: get a download link", status == 200 and field(link, "url"), link)
    # Released clients send their API key along; the store must still accept the signed URL.
    status, body, headers = fetch("GET", field(link, "url"), headers={"Authorization": f"Bearer {key}"})
    expect(f"{step}: download through the link, with the API key sent along", status == 200 and body == data, f"HTTP {status}, {body[:300]!r}")
    expect(f"{step}: the download names the file", 'filename="smoke.txt"' in headers.get("content-disposition", ""), headers)


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
    first = f"smoke file {suffix}\n".encode()
    file = upload(base, key, dataset_mfid, first, "upload a file", f"/datasets/{dataset_mfid}/upload/multipart/initiate", {"filename": "smoke.txt"})
    download(base, key, field(file, "mfid"), first, "the uploaded file")
    second = f"replaced smoke file {suffix}\n".encode() * 3
    replaced = upload(base, key, dataset_mfid, second, "replace the file", f"/files/{field(file, 'mfid')}/upload/multipart/initiate", {})
    expect("the replacement keeps the file record", field(replaced, "mfid") == field(file, "mfid"), replaced)
    download(base, key, field(file, "mfid"), second, "the replaced file")

    status, read = request(base, "GET", f"/datasets/{dataset_mfid}", key)
    expect("read the dataset back", status == 200 and field(read, "dataset_name") == f"smoke dataset {suffix}", read)
    status, listed = request(base, "GET", f"/datasets?mfid={dataset_mfid}", key)
    items = field(listed, "items") if isinstance(listed, dict) else listed
    expect("find the dataset by MFID", status == 200 and isinstance(items, list) and [field(item, "unique_id") for item in items] == [dataset_mfid], listed)

    username = f"smoke{suffix}"
    status, user = request(base, "POST", "/users", key, {"user_info": {"first_name": "Smoke", "last_name": "Person", "username": username}})
    expect("create a second user", status == 200, user)
    reader_name = f"smoke-reader{suffix}"
    status, created = request(base, "POST", "/service_accounts", key, {"username": reader_name})
    expect("create a service account to read as another identity", status == 200 and field(created, "api_key"), created)
    reader = field(created, "api_key")
    status, demoted = request(base, "PATCH", f"/service_accounts/{reader_name}", key, {"platform_role": "none"})
    expect("give it no platform role, so it sees only what is shared", status == 200, demoted)

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
