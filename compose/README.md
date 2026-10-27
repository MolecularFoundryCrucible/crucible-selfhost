# Installing Crucible with Docker Compose

This folder runs Crucible on one machine: PostgreSQL (with pgvector), the Crucible API, and Caddy as the web server in front. It suits a small group: one lab, a few workstations, an administrator who sets it up once.

What works today: the API (projects, samples, datasets and their metadata, users, access control), the Python client nano-crucible, and API keys. Not yet: file storage (Phase 2 adds an S3-compatible store; until then file upload and download routes answer `501 storage_not_configured`), browser sign-in through the Crucible Hub (a later step of this bundle), local passwords (Phase 3), and the optional printing, ingestion, and proposal integrations, which stay off.

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

`docker compose down` stops everything and keeps the data. `docker compose down -v` also deletes the database and certificates; there is no undo.

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
}
```

## Troubleshooting

- `docker compose ps -a` shows each service; `docker compose logs api migrate db` shows what happened.
- `bind source path does not exist: .../secrets/<NAME>`: a secret file is missing; create it as in step 1.
- `Missing required settings: ...` or `... is given more than one way ...`: the API names the setting; fix `.env` or `secrets/` and run `docker compose up -d --wait` again.
- The database refuses the password after you changed `secrets/PGDB_PW`: the password is set only when the database is first created. Set the same password inside the database (`docker compose exec db psql -U postgres -c '\password crucible'`, which asks for it without showing it), then `docker compose up -d --force-recreate --wait` so every service reads the new file.
- On Fedora, RHEL, Rocky, or AlmaLinux with SELinux enforcing, `permission denied` reading `/run/secrets/...`: label the folder for containers with `chcon -Rt container_file_t secrets`.
- `crucible: /run/secrets/PGDB_PW is missing, empty, or not readable` in the `db` logs, and `db` never becoming healthy: the files in `secrets/` must exist and be readable (`chmod 644 secrets/*`). The database's first start was interrupted, so start over: `docker compose down -v`, then `docker compose up -d --build --wait`.
