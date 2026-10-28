# Installing Crucible with Docker Compose

This folder runs Crucible on one machine: PostgreSQL (with pgvector), the Crucible API, and Caddy as the web server in front. It suits a small group: one lab, a few workstations, an administrator who sets it up once.

What works today: the API (projects, samples, datasets and their metadata, users, access control), the Python client nano-crucible, API keys, and, optionally, the Crucible Hub web interface with ORCID sign-in (see [Adding the Hub](#adding-the-hub)). Not yet: file storage (Phase 2 adds an S3-compatible store; until then file upload and download routes answer `501 storage_not_configured`), local passwords (Phase 3), and the optional printing, ingestion, and proposal integrations, which stay off.

## Requirements

- Linux with Docker Engine 24 or newer and the Compose plugin 2.20 or newer (`docker compose version`).
- About 2 GB of free memory and a few GB of disk to start; the database grows with your data.
- A copy of this repository (images are built from it until versioned images are published).

## 1. Create the secrets

Secrets are files in `secrets/`, given to the containers as Docker Compose secrets (mounted at `/run/secrets/`, never placed in environment variables). Create them once:

```bash
cd deploy/compose
mkdir -p secrets && chmod 700 secrets
for name in POSTGRES_PASSWORD PGDB_PW CRUCIBLE_SECRET_KEY; do
  openssl rand -hex 32 > "secrets/$name"
done
chmod 644 secrets/*
```

| File | Used for |
|---|---|
| `POSTGRES_PASSWORD` | the PostgreSQL administrator: creates the database the first time, and is used for backups and the database health check; the API never uses it |
| `PGDB_PW` | the ordinary `crucible` database account the API uses |
| `CRUCIBLE_SECRET_KEY` | signing browser sessions and list cursors; changing it signs everyone out |

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

The first start builds the API image, creates the database and its extensions, creates the schema (the one-time `migrate` service, which the API waits for), and then starts the API and Caddy. `--wait` returns once everything is healthy. Check:

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

Or set `CRUCIBLE_API_URL` and `CRUCIBLE_API_KEY` in the environment. In Python, `CrucibleClient(api_url=..., api_key=...)` takes them directly.

## HTTPS with a domain name

When the server has a public domain name, Caddy obtains and renews an HTTPS certificate from Let's Encrypt by itself. Point the domain's DNS at the machine, open ports 80 and 443, and set in `.env`:

```bash
CRUCIBLE_SITE_ADDRESS=crucible.mylab.org
CRUCIBLE_HTTP_PORT=80
CRUCIBLE_HTTPS_PORT=443
CRUCIBLE_PUBLIC_URL=https://crucible.mylab.org
```

then `docker compose up -d --wait`. Certificates are kept in the `caddy-data` volume. Use the bare domain name, without `https://` or a port. With rootless Docker, ports below 1024 need `sudo sysctl net.ipv4.ip_unprivileged_port_start=80`.

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

Back up the database and the `secrets/` folder. A database backup contains every user's API key, so treat it like the secrets: keep it in a private folder outside the repository.

```bash
mkdir -p ~/crucible-backups && chmod 700 ~/crucible-backups
(umask 077; docker compose exec -T db pg_dump --username postgres --dbname crucible --format custom > ~/crucible-backups/crucible-$(date +%F).dump)
```

To restore into a running installation (this replaces its data):

```bash
docker compose stop api
docker compose exec -T db pg_restore --username postgres --dbname crucible --clean --if-exists < ~/crucible-backups/crucible-2026-10-26.dump
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

## Stopping and removing

`docker compose down` stops everything and keeps the data. With the Hub on this machine, stop the Hub project first: the shared `crucible` network cannot be removed while it is attached. `docker compose down -v` also deletes the database and certificates; there is no undo.

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

- `docker compose ps -a` shows each service; `docker compose logs api migrate db` shows what happened.
- `bind source path does not exist: .../secrets/<NAME>`: a secret file is missing; create it as in step 1.
- `Missing required settings: ...` or `... is given more than one way ...`: the API names the setting; fix `.env` or `secrets/` and run `docker compose up -d --wait` again.
- The database refuses the password after you changed `secrets/PGDB_PW`: the password is set only when the database is first created. Set the same password inside the database (`docker compose exec db psql -U postgres -c '\password crucible'`, which asks for it without showing it), then `docker compose up -d --force-recreate --wait` so every service reads the new file.
- On Fedora, RHEL, Rocky, or AlmaLinux with SELinux enforcing, `permission denied` reading `/run/secrets/...`: label the folder for containers with `chcon -Rt container_file_t secrets`.
- `crucible: /run/secrets/PGDB_PW is missing, empty, or not readable` in the `db` logs, and `db` never becoming healthy: the files in `secrets/` must exist and be readable (`chmod 644 secrets/*`). The database's first start was interrupted, so start over: `docker compose down -v`, then `docker compose up -d --build --wait`.
