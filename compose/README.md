# Installing Crucible with Docker Compose

This folder runs Crucible on one machine: PostgreSQL (with pgvector), the Crucible API, SeaweedFS for files, and Caddy as the web server in front. It suits a small group: one lab, a few workstations, an administrator who sets it up once.

What works today: the API (projects, samples, datasets and their metadata, users, access control), file upload, replacement, and download (see [File storage](#file-storage)), the Python client nano-crucible, API keys, and, optionally, the Crucible Hub web interface with ORCID sign-in (see [Adding the Hub](#adding-the-hub)). Not yet: local passwords (Phase 3), and the optional printing, ingestion, and proposal integrations, which stay off.

## Requirements

- Linux with Docker Engine 24 or newer and the Compose plugin 2.20 or newer (`docker compose version`).
- About 2 GB of free memory and a few GB of disk to start; the database grows with your data.
- A copy of this repository (images are built from it until versioned images are published).

## 1. Create the secrets

Secrets are files in `secrets/`, given to the containers as Docker Compose secrets (mounted at `/run/secrets/`, never placed in environment variables). Create them once:

```bash
cd deploy/compose
mkdir -p secrets && chmod 700 secrets
for name in POSTGRES_PASSWORD PGDB_PW CRUCIBLE_SECRET_KEY S3_SECRET_ACCESS_KEY; do
  openssl rand -hex 32 > "secrets/$name"
done
openssl rand -hex 16 > secrets/S3_ACCESS_KEY_ID
chmod 644 secrets/*
```

| File | Used for |
|---|---|
| `POSTGRES_PASSWORD` | the PostgreSQL administrator: creates the database the first time, and is used for backups and the database health check; the API never uses it |
| `PGDB_PW` | the ordinary `crucible` database account the API uses |
| `CRUCIBLE_SECRET_KEY` | signing browser sessions and list cursors; changing it signs everyone out |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | the key pair the API uses with the file store; SeaweedFS takes the same pair. With your own store instead, put that store's key pair here |

The folder is private to you (`700`); the files are readable (`644`) because the database container reads them as its own user. `secrets/` and `.env` are git-ignored. Keep a copy of the secrets with your backups: a restored database needs the same `PGDB_PW`, and `CRUCIBLE_SECRET_KEY` keeps existing sessions valid.

## 2. Configure

```bash
cp .env.example .env
```

The defaults serve plain HTTP on port 8080 at `http://localhost:8080/api/v3/`. Edit `.env` to change the port, the number of API workers, or the address others use to reach the server (`CRUCIBLE_PUBLIC_URL`). Every setting is explained in `.env.example`.

## 3. Start

```bash
docker compose up -d --build --wait
```

The first start builds the API image, creates the database and its extensions, creates the schema (the one-time `migrate` service, which the API waits for), starts SeaweedFS with its two buckets, and then starts the API and Caddy. `--wait` returns once everything is healthy. Check:

```bash
curl http://localhost:8080/api/v3/health/ready
```

It should report `"status":"ok"` and `"schema_state":"current"`. The interactive API documentation is at `http://localhost:8080/api/v3/docs`.

## 4. Create the first administrator

```bash
docker compose run --rm api python -m app.cli admin create
```

It asks for a name, an optional email, an optional ORCID (without one the account gets a Crucible MFID), and an optional username, then asks for confirmation. It prints an API key: this key signs in as the administrator, so treat it as a password and store it in a password manager. Run this by hand only; never as an automatic step, where the key would end up in logs.

To script it instead, pass every value and `--no-input`:

```bash
docker compose run --rm -T api python -m app.cli admin create --no-input --first-name Ada --last-name Lovelace --email ada@example.org
```

A second administrator needs `--allow-additional`, so an accidental second run does nothing.

## 5. Connect the Python client

```bash
pip install nano-crucible
crucible config set api_url http://<server>:8080/api/v3
crucible config set api_key <the key from step 4>
crucible config show
```

Or set `CRUCIBLE_API_URL` and `CRUCIBLE_API_KEY` in the environment. In Python, `CrucibleClient(api_url=..., api_key=...)` takes them directly. Uploading files needs nano-crucible 3.3.0 or newer with its default `upload_protocol` (`auto`); older versions, and `upload_protocol` `legacy`, use upload routes that work only with Google Cloud Storage.

## HTTPS with a domain name

When the server has a public domain name, Caddy obtains and renews an HTTPS certificate from Let's Encrypt by itself. Point the domain's DNS at the machine, open ports 80 and 443, and set in `.env`:

```bash
CRUCIBLE_SITE_ADDRESS=crucible.mylab.org
CRUCIBLE_HTTP_PORT=80
CRUCIBLE_HTTPS_PORT=443
CRUCIBLE_PUBLIC_URL=https://crucible.mylab.org
```

then `docker compose up -d --wait`. Certificates are kept in the `caddy-data` volume. Use the bare domain name, without `https://` or a port. With rootless Docker, ports below 1024 need `sudo sysctl net.ipv4.ip_unprivileged_port_start=80`.

## File storage

Uploaded files go to SeaweedFS, an S3-compatible store that runs in this bundle, in the `crucible-files` bucket; a copy of each record's metadata (`record.json` and `metadata.json`, written on every change) goes to `crucible-records`. Both live in the `seaweedfs-data` Docker volume (under `/var/lib/docker/volumes/`, or `~/.local/share/docker/volumes/` with rootless Docker) unless you choose a folder, below. Files never pass through the API: clients get short-lived signed URLs from the API and send or fetch the bytes directly, through Caddy at `/crucible-files/`, which forwards them to SeaweedFS unchanged and drops any API key or cookie the client sends along. The records bucket is not reachable from outside. SeaweedFS is on its own internal network that only the API and Caddy join; the Hub cannot reach it.

Signed URLs carry the server's address (`CRUCIBLE_PUBLIC_URL`, or `http://localhost:<port>` when it is unset), and the store checks it: everyone, the Python client and the Hub included, must reach the server by that same address. A client that uses another name or port (`http://labbox:8080` against `http://localhost:8080`) gets `SignatureDoesNotMatch` errors on every upload and download, so set `CRUCIBLE_PUBLIC_URL` before people start using the server.

To check storage end to end (a signed upload in two parts, a part with the wrong checksum that must be refused, a signed download, the records bucket, and deleting the test file):

```bash
docker compose exec api python -m app.cli storage check
```

### Keeping the files on a disk of your choice

To keep the store's data on a particular disk (a large data disk or RAID array) instead of Docker's own folder, create a folder on it owned by uid 1000, the user SeaweedFS runs as, and name it in `.env` before the first start:

```bash
sudo mkdir -p /srv/crucible/files
sudo chown 1000:1000 /srv/crucible/files
echo "CRUCIBLE_FILES_DIR=/srv/crucible/files" >> .env
```

Use a local disk, mounted at boot (by UUID in `/etc/fstab`), not a network share. The folder holds SeaweedFS's own data files, not your uploads one by one; reach the files through Crucible or back them up as below. To move an existing installation's files there:

```bash
docker compose stop seaweedfs
docker run --rm -v crucible_seaweedfs-data:/from:ro -v /srv/crucible/files:/to alpine:3.22 cp -a /from/. /to/
echo "CRUCIBLE_FILES_DIR=/srv/crucible/files" >> .env
docker compose up -d --wait
```

Once uploads and downloads work, `docker volume rm crucible_seaweedfs-data` frees the old copy.

### Replaced files, restoring, and cleanup

When a file is replaced, its previous content is kept for 14 days (`CRUCIBLE_FILE_VERSION_RETENTION_DAYS` in `.env`), so a replace can be undone:

```bash
docker compose exec api python -m app.cli files restore <file MFID>
```

This makes the newest kept version current again and keeps the content it replaces, so running it again undoes the restore. The `storage-cleanup` service runs `python -m app.cli storage cleanup` every hour: it deletes kept versions older than the grace period that no file uses, and aborts uploads that were started and abandoned. To turn it off, set `CRUCIBLE_STORAGE_CLEANUP_ENABLED=false` in `.env` and run `docker compose up -d --wait`; old versions and abandoned uploads then stay in the bucket. `docker compose exec api python -m app.cli storage cleanup --dry-run` shows what it would do, also while it is off. Keep the grace period at least as long as the oldest database backup you might restore, so the files such a backup points at still exist.

SeaweedFS frees the disk space of deleted files later, when its background compaction runs (once about 30% of a storage unit is deleted data), and compaction itself needs some free space: keep a margin on the disk and watch it. Deleting a file or a dataset still removes only the database records, not the stored bytes; that comes in a later version.

### Using another S3-compatible store

An institution's object store (or a cloud one) can replace SeaweedFS. It must accept presigned URLs with signed `x-amz-checksum-crc32c` headers and refuse a part whose bytes do not match; `storage check` tests exactly that, so run it before relying on the store. Create two buckets on it, put its key pair in `secrets/S3_ACCESS_KEY_ID` and `secrets/S3_SECRET_ACCESS_KEY`, and in `.env` remove `COMPOSE_PROFILES=bundled-storage` and set:

```bash
CRUCIBLE_S3_ENDPOINT_URL=https://s3.myinstitution.org
# The address clients reach the store on, when it differs from the endpoint.
# CRUCIBLE_S3_PUBLIC_URL=https://s3.myinstitution.org
CRUCIBLE_S3_REGION=us-east-1
CRUCIBLE_UPLOAD_BUCKET=mylab-crucible-files
CRUCIBLE_RECORD_BUCKET=mylab-crucible-records
```

then `docker compose up -d --wait` and `docker compose exec api python -m app.cli storage check`. Browser uploads from the Hub then go to the store's own address, so the upload bucket needs a CORS rule allowing `PUT` and `GET` from the Hub's address with the `x-amz-checksum-crc32c` and `content-type` headers, exposing `ETag`.

If the store cannot be served under a path of this site, run it under its own name (for example `files.mylab.org`, with its own certificate) and set `CRUCIBLE_S3_PUBLIC_URL` to that address.

### Using a Google Cloud Storage bucket

Clients see no difference. Use `CRUCIBLE_STORAGE_BACKEND=gcs`, not Google's S3 interface, which refuses the checksums S3 uploads send. In the Google Cloud project:

1. Create a files bucket and a records bucket (uniform bucket-level access, public access prevention). On the files bucket, add lifecycle rules that delete replaced content after 14 days and abandoned uploads after one: `{"rule": [{"action": {"type": "Delete"}, "condition": {"daysSinceCustomTime": 14}}, {"action": {"type": "AbortIncompleteMultipartUpload"}, "condition": {"age": 1}}]}`. `files restore` and the version cleanup apply to S3 stores only.
2. Create a service account with Storage Object Admin on both buckets and Service Account Token Creator on itself, so it can sign URLs without a key.
3. If the Hub uploads from browsers, add a CORS rule on the files bucket for the Hub's address: `PUT` and `GET`, headers `content-type` and `x-goog-hash`, exposing `ETag`.

Give the server that identity, using the first option that applies:

- On Google Cloud (a VM, Cloud Run, GKE): attach the service account; no key. With GKE Workload Identity Federation for the Kubernetes account itself, also set `MULTIPART_UPLOAD_SIGNER` to the service account's email and grant the Kubernetes identity Token Creator on it; the server then acts as that service account for everything.
- Elsewhere, such as this bundle on a lab server: Workload Identity Federation if your identity provider supports it. Otherwise a key, where your organization allows keys: save it as `secrets/google-credentials.json` and add `compose.override.yaml` next to `compose.yaml`:

```yaml
x-google: &google
  environment:
    GOOGLE_APPLICATION_CREDENTIALS: /run/secrets/google-credentials.json
  secrets: [google-credentials.json]

services:
  api: *google
  storage-cleanup: *google

secrets:
  google-credentials.json:
    file: ./secrets/google-credentials.json
```

In `.env`, remove `COMPOSE_PROFILES=bundled-storage` and set:

```bash
CRUCIBLE_STORAGE_BACKEND=gcs
CRUCIBLE_UPLOAD_BUCKET=mylab-crucible-files
CRUCIBLE_RECORD_BUCKET=mylab-crucible-records
```

then run `docker compose up -d --wait` and `docker compose exec api python -m app.cli storage check`. `files-backup` copies S3 stores only; protect a Google bucket with Google's tools (object versioning, soft delete, or a copy to another bucket).

## Adding the Hub

The Crucible Hub is the web interface, where people sign in with ORCID. It is optional: without it the API, API keys, and the Python client work as before. The Hub is its own Compose project, from the [crucible-hub repository](https://github.com/MolecularFoundryCrucible/crucible-hub/tree/v1.7.1/deploy/compose) at release `v1.7.1`, with its own small database for sign-in sessions. The Hub publishes a ready-made image, `ghcr.io/molecularfoundrycrucible/crucible-hub:1.7.1` (amd64 and arm64), so nothing needs to be built; its `gov.lbl.crucible.api.min-version` label names the oldest Crucible API it works with (3.2.0). It runs on this machine or on a second one; this bundle's Caddy serves it at `/hub/` either way, so people use one address.

### What you need

- **HTTPS.** Sign-in sets secure cookies and ORCID calls the server back, so plain HTTP does not work. Choose one:
  - A public domain name: [HTTPS with a domain name](#https-with-a-domain-name) above.
  - A name in your lab's DNS that the internet cannot reach: Caddy can still get a Let's Encrypt certificate through a DNS challenge, but needs a Caddy build with your DNS provider's module ([caddy-dns](https://github.com/caddy-dns)); this bundle does not ship one.
  - A certificate from your institution: mount the files into the `proxy` service and add `tls /certs/cert.pem /certs/key.pem` under the site address in `Caddyfile`.
  - A trial on one computer: `CRUCIBLE_SITE_ADDRESS=localhost` makes Caddy use its own certificate authority. Browsers warn until you trust its root certificate (`docker compose exec proxy cat /data/caddy/pki/authorities/local/root.crt > caddy-root.crt`, then add it to the system or browser). With the default ports the address is `https://localhost:8443`: use that, port included, wherever this guide writes `https://crucible.mylab.org`. Only for evaluation: every user's machine would need the certificate.
- **An ORCID application.** Register Public API credentials at [ORCID developer tools](https://orcid.org/developer-tools) (free, needs a verified email). The redirect URI is the API's, not the Hub's: `https://<your address>/api/v3/auth/hub/callback`, including the port when it is not 443. ORCID accepts only HTTPS redirect URIs and matches them exactly. For a trial, use the [ORCID sandbox](https://sandbox.orcid.org) and its separate accounts.

### 1. Turn on Hub sign-in in the API

Create the two secrets (the first is shared with the Hub; the second comes from ORCID):

```bash
openssl rand -hex 32 > secrets/HUB_AUTH_CLIENT_SECRET
printf '%s' 'your-orcid-client-secret' > secrets/ORCID_CLIENT_SECRET
chmod 644 secrets/*
```

In `.env`:

```bash
COMPOSE_FILE=compose.yaml:compose.hub.yaml
# The address people use: no /api/v3, no trailing slash, and the port if it is not 443.
CRUCIBLE_PUBLIC_URL=https://crucible.mylab.org
ORCID_CLIENT_ID=APP-XXXXXXXXXXXXXXXX
# For the ORCID sandbox:
# ORCID_ISSUER=https://sandbox.orcid.org
```

`compose.hub.yaml` writes these into the API's explicit provider list, `CRUCIBLE_AUTH_PROVIDERS`. To change or add providers, see [the provider list](../../docs/hub_auth_operations.md#the-provider-list) and `auth-providers.example.json`.

Then `docker compose up -d --wait`. Until the Hub runs, `/hub/` answers `502`.

### 2a. The Hub on this machine

```bash
git clone --branch v1.7.1 https://github.com/MolecularFoundryCrucible/crucible-hub.git
cd crucible-hub/deploy/compose
```

Follow its `README.md`: copy this bundle's `secrets/HUB_AUTH_CLIENT_SECRET` to its `secrets/hub_auth_client_secret`, create its other secrets, copy `example.env` to `.env`, and set `HUB_IMAGE=ghcr.io/molecularfoundrycrucible/crucible-hub:1.7.1`, `HUB_PUBLIC_ORIGIN=https://crucible.mylab.org`, and `HUB_AUTH_PUBLIC_API_URL=https://crucible.mylab.org/api/v3`. The defaults there join this bundle's `crucible` network and call the API at `http://api:8000`. Start it after this bundle, which creates the network, with `docker compose pull hub hub-setup` and then `docker compose up -d --wait`. `https://crucible.mylab.org/hub/health` then answers `{"status":"ok","sessions":"ok"}`.

### 2b. The Hub on a second machine

On the second machine, clone the same release and create the Hub's secrets as in 2a (copying `HUB_AUTH_CLIENT_SECRET` from this machine). In its `.env`, comment out the same-machine block and use the separate-machine one: `COMPOSE_FILE=compose.yaml:compose.published.yaml`, `HUB_BIND_ADDRESS` set to the address this machine reaches it on, and `CRUCIBLE_API_BASE_URL=https://crucible.mylab.org/api/v3`; set `HUB_IMAGE`, `HUB_PUBLIC_ORIGIN`, and `HUB_AUTH_PUBLIC_API_URL` as in 2a. Start it with `docker compose pull hub hub-setup` and `docker compose up -d --wait`. Then, in this bundle's `.env`, set `CRUCIBLE_HUB_UPSTREAM=<that address>:3000` (an address and port, without `http://`) and run `docker compose up -d --wait`.

Caddy talks to the Hub in plain HTTP, and that link carries sign-in cookies, so it must be encrypted: put both machines on a WireGuard or Tailscale network and use the Hub's address there, and let only this machine reach the Hub's port. A shared LAN alone is not enough.

### Traffic inside the installation

HTTPS ends at Caddy; behind it, Caddy, the API, and the Hub talk plain HTTP, and those connections carry API keys, sign-in tokens and cookies, and, when the Hub exchanges a sign-in, the shared client secret. On one machine this is the usual setup and is safe as configured here: the database is on an internal network that only the API joins (the Hub cannot reach it), every container drops the Linux capabilities that would let it intercept its neighbours' traffic and cannot gain new privileges, and nothing else should be attached to the `crucible` network. It is not "zero trust", where every connection is encrypted and authenticated (NIST SP 800-207). Any connection that leaves the machine needs encryption: the Hub refuses plain HTTP to the API except to a container name or a private address, and the link to a Hub on a second machine must be an encrypted private network as above. Labs that want encryption inside the machine too can have Caddy issue internal certificates (`tls internal`) for an extra HTTPS address in front of the API, have the Hub call that address, and give the Hub Caddy's root certificate through `NODE_EXTRA_CA_CERTS`; this needs no code change but is not set up here.

### Removing the Hub

Stop the Hub project (`docker compose down` in its folder; add `-v` to delete its session database), remove `COMPOSE_FILE` (and `CRUCIBLE_HUB_UPSTREAM`, if you set it) from this bundle's `.env`, and run `docker compose up -d --wait`. The API's data is untouched; `/hub/` answers `404`.

## Backups

Back up the database, the stored files, and the `secrets/` folder. A database backup contains every user's API key, so treat it like the secrets: keep it in a private folder outside the repository. Back up the database first and the files second: a file uploaded in between is then only an unused extra, while the other order could leave a record pointing at bytes the backup lacks.

```bash
mkdir -p ~/crucible-backups/files && chmod 700 ~/crucible-backups
(umask 077; docker compose exec -T db pg_dump --username postgres --dbname crucible --format custom > ~/crucible-backups/crucible-$(date +%F).dump)
docker compose run --rm --user "$(id -u):$(id -g)" files-backup
```

`files-backup` (rclone) copies both buckets through the S3 interface into `~/crucible-backups/files/` (or `CRUCIBLE_BACKUP_DIR/files/`; create that `files` folder yourself first, or Docker creates it owned by root and the copy cannot write to it), with the store running, so uploads continue. Each run copies only files not yet in the backup, and never deletes from it. Stored files are never changed in place, so this incremental copy is all a backup needs. The copy is plain files: `crucible-files/<dataset>/_files/<upload id>` for uploads (their names are in the database) and `crucible-records/<id>/record.json` for the metadata copies. Back the folder up further with your usual tools (restic, rsync, a tape robot). With rootless Docker, leave out `--user`. The same command backs up your own S3 store when you use one instead of SeaweedFS.

To restore into a running installation (this replaces its database, and adds the backed-up files to the store). Stop `storage-cleanup` as well as `api`: while the database is half restored, the cleanup could take files as unused and delete them.

```bash
docker compose stop api storage-cleanup
docker compose exec -T db pg_restore --username postgres --dbname crucible --clean --if-exists < ~/crucible-backups/crucible-2026-10-26.dump
docker compose run --rm --user "$(id -u):$(id -g)" files-backup restore
docker compose up -d --wait
```

`up` runs the `migrate` step again, which brings a backup from an older version up to date before the API starts. A backup from a newer version than the code cannot be restored; upgrade the code first.

To move to a new machine, copy the repository, `.env`, `secrets/`, and the backup; start once (step 3), then restore.

## Upgrading

```bash
(umask 077; docker compose exec -T db pg_dump --username postgres --dbname crucible --format custom > ~/crucible-backups/before-upgrade.dump)
git pull
docker compose up -d --build --wait
```

The `migrate` step applies any database changes before the new API starts. If one fails, the database stays at the last change that completed, the API does not start, and `docker compose logs migrate` says why; fix the cause and run the same command again, or restore the backup.

From a version without file storage, create the two storage secrets and add the storage profile before `docker compose up`:

```bash
openssl rand -hex 16 > secrets/S3_ACCESS_KEY_ID
openssl rand -hex 32 > secrets/S3_SECRET_ACCESS_KEY
chmod 644 secrets/*
echo "COMPOSE_PROFILES=bundled-storage" >> .env
```

Compare your `.env` with `.env.example` after each upgrade for other new settings.

## Stopping and removing

`docker compose down` stops everything and keeps the data. With the Hub on this machine, stop the Hub project first: the shared `crucible` network cannot be removed while it is attached. `docker compose down -v` also deletes the database, the stored files (unless they are in a `CRUCIBLE_FILES_DIR` folder, which stays), and the certificates; there is no undo.

## Using a different way to provide secrets

Crucible reads each secret from exactly one of: a file named after it in the secrets directory (`/run/secrets` by default, or `CRUCIBLE_SECRETS_DIR`), a file named by `NAME_FILE`, or the `NAME` environment variable. Giving one secret two ways stops the server with a message naming it. So any tool that writes secrets as files works without changes:

- systemd: `LoadCredential=PGDB_PW:/etc/crucible/pgdb_pw` and `CRUCIBLE_SECRETS_DIR=%d`.
- Kubernetes: a Secret mounted as a volume at `/run/secrets`, or an external manager (Vault, AWS, Azure, Google) through the Secrets Store CSI Driver or the External Secrets Operator.
- Vault Agent or a similar sidecar: write each secret to a file and point `NAME_FILE` or `CRUCIBLE_SECRETS_DIR` at it.

## Using your own reverse proxy

Caddy can be replaced by any reverse proxy. The rules:

- `/api/v3/` goes to the API (`api:8000` inside Compose, or the API container's port) with the `/api/v3` prefix removed; the API serves its documentation under that prefix (`API_PATH=api/v3`).
- Pass `Host`, `X-Forwarded-For` (set to the client address, not appended to what the client sent), and `X-Forwarded-Proto`. The API trusts forwarding headers from any address (`FORWARDED_ALLOW_IPS="*"`), so it must not be reachable except through the proxy.
- Allow request bodies of a few megabytes and read timeouts of at least 60 seconds for large metadata requests.
- `/crucible-files/` goes to SeaweedFS (`seaweedfs:8333`) with the path and `Host` unchanged, since the store checks the signed URL against both. Remove the `Authorization` and `Cookie` request headers, allow request bodies of 64 MB (one upload part) and read timeouts of a few minutes, and do not compress the responses. Add `Content-Security-Policy: sandbox; default-src 'none'`, `X-Content-Type-Options: nosniff`, and `Cross-Origin-Resource-Policy: same-site` to them, so a downloaded file never runs as a page of the site and other sites cannot embed it ([web.dev, "Securely hosting user data"](https://web.dev/articles/securely-hosting-user-data)); current Chrome and Firefox still show PDFs and images in the browser with these headers. Do not route the records bucket.
- With the Hub: `/hub/` goes to the Hub (`hub:3000`) with the prefix kept. `X-Forwarded-For` must again be set, not appended: the Hub limits sign-in attempts per client address and trusts one proxy (`HUB_TRUSTED_PROXY_HOPS=1`). Caddy also caps `/api/v3/auth/hub/` requests at 8 KB and waits at most 20 seconds for the API there.

An nginx example, for nginx running as a service in the same compose project (remove the `proxy` service and publish nginx instead):

```nginx
server {
    listen 80;
    server_name crucible.mylab.org;
    client_max_body_size 16m;

    location = /api/v3 { return 301 /api/v3/; }

    location /api/v3/ {
        proxy_pass http://api:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_read_timeout 60s;
    }

    location /crucible-files/ {
        proxy_pass http://seaweedfs:8333;
        proxy_set_header Host $http_host;
        proxy_set_header Authorization "";
        proxy_set_header Cookie "";
        proxy_request_buffering off;
        client_max_body_size 80m;
        proxy_read_timeout 300s;
        add_header Content-Security-Policy "sandbox; default-src 'none'" always;
        add_header X-Content-Type-Options nosniff always;
        add_header Cross-Origin-Resource-Policy same-site always;
    }

    # Only with the Hub.
    location /hub/ {
        proxy_pass http://hub:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Troubleshooting

- `/hub/` answers `502`: the Hub is not running, or `CRUCIBLE_HUB_UPSTREAM` does not point at it. On one machine, check `docker compose ps` in the Hub's folder; it must have joined the `crucible` network.
- `network crucible declared as external, but could not be found` when starting the Hub: start this bundle first; it creates the network.

- `docker compose ps -a` shows each service; `docker compose logs api migrate db seaweedfs` shows what happened.
- Uploads and download links fail with `503` ("Storage is temporarily unavailable") after an upgrade, and `docker compose ps` shows no `seaweedfs`: `.env` lacks `COMPOSE_PROFILES=bundled-storage` (see [Upgrading](#upgrading)).
- `seaweedfs` is unhealthy and its log says `permission denied` under `/data`: the folder in `CRUCIBLE_FILES_DIR` does not belong to uid 1000 (Docker creates a missing folder owned by root). Run `sudo chown -R 1000:1000` on it and `docker compose up -d --wait`.
- `SignatureDoesNotMatch` on uploads or downloads: the client reached the server by another address than `CRUCIBLE_PUBLIC_URL` (see [File storage](#file-storage)), or a proxy in front changed the path or `Host`.
- `bind source path does not exist: .../secrets/<NAME>`: a secret file is missing; create it as in step 1.
- `Missing required settings: ...` or `... is given more than one way ...`: the API names the setting; fix `.env` or `secrets/` and run `docker compose up -d --wait` again.
- The database refuses the password after you changed `secrets/PGDB_PW`: the password is set only when the database is first created. Set the same password inside the database (`docker compose exec db psql -U postgres -c '\password crucible'`, which asks for it without showing it), then `docker compose up -d --force-recreate --wait` so every service reads the new file.
- On Fedora, RHEL, Rocky, or AlmaLinux with SELinux enforcing, `permission denied` reading `/run/secrets/...`: label the folder for containers with `chcon -Rt container_file_t secrets`.
- `crucible: /run/secrets/PGDB_PW is missing, empty, or not readable` in the `db` logs, and `db` never becoming healthy: the files in `secrets/` must exist and be readable (`chmod 644 secrets/*`). The database's first start was interrupted, so start over: `docker compose down -v`, then `docker compose up -d --build --wait`.
