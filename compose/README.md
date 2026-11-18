# Installation with Docker Compose

This bundle runs Crucible on a single host: the API, PostgreSQL (with pgvector), SeaweedFS for file storage, and Caddy as the reverse proxy. It is intended for small deployments, such as one lab with a few workstations.

The quick start gives a server that answers on the local host only, with password sign-in, API keys and the nano-crucible Python client. Everything else is optional and described on its own page under [Further configuration](#further-configuration). The printing, ingestion and proposal integrations are not part of the bundle.

## Requirements

- Linux with Docker Engine 28 or later and the Compose plugin 2.20 or later (`docker version`, `docker compose version`). Older Docker releases expose ports published to the local host to other hosts on the same network segment.
- About 2 GB of free memory and a few GB of disk to start; the database grows with the data.
- A user allowed to run Docker: a member of the `docker` group, or prefix each `docker` command with `sudo`.
- A copy of this repository. Images are built from it until versioned images are published.

## Quick start

### 1. Create the secrets

```bash
cd deploy/compose
mkdir -p secrets && chmod 700 secrets
for name in POSTGRES_PASSWORD PGDB_PW CRUCIBLE_SECRET_KEY CRUCIBLE_AUTH_PEPPER S3_SECRET_ACCESS_KEY; do
  openssl rand -hex 32 > "secrets/$name"
done
openssl rand -hex 16 > secrets/S3_ACCESS_KEY_ID
chmod 644 secrets/*
```

Each file holds one secret and is mounted into the containers that need it. `secrets/` and `.env` are ignored by git. [Secrets](docs/operations.md#secrets) lists what each one protects and which to back up.

### 2. Configure

```bash
cp .env.example .env
```

The defaults serve `http://localhost:8080/api/v3/` to the local host only and need no editing. `.env.example` lists every setting with its default, grouped by the pages under [Further configuration](#further-configuration).

### 3. Start the services

```bash
docker compose up -d --build --wait
curl http://localhost:8080/api/v3/health/ready
```

The first start builds the API image and creates the database, its schema and the storage buckets; `--wait` returns once every service is healthy. The response contains `"status":"ok"` and `"schema_state":"current"`. The interactive API documentation is at `http://localhost:8080/api/v3/docs`.

### 4. Create the first administrator

```bash
docker compose run --rm api python -m app.cli admin create
```

The command prompts for a name and, optionally, an email, an ORCID and a username. It prints one line of JSON with two values:

- `password_link`: a link, valid once and for 24 hours, that sets the administrator's password in a browser.
- `api_key`: an API key that authenticates as the administrator from scripts. Store it like a password.

Run the command interactively, so that neither value is written to a log.

### 5. Connect the Python client

```bash
pip install nano-crucible
crucible config set api_url http://localhost:8080/api/v3
crucible config set api_key <the key from step 4>
crucible config show
```

With nano-crucible 4.0 or later, `crucible login` signs in through the browser instead of using an API key. File uploads require nano-crucible 3.3.0 or later.

### Access from another computer

Until HTTPS is configured, the server answers only on the host itself. To open the password link or use the client from another computer, forward the port over SSH and use the same address there:

```bash
ssh -L 8080:localhost:8080 you@server
```

## Further configuration

| Page | Contents |
|---|---|
| [Network access and HTTPS](docs/network.md) | Public address, certificates, host firewall, institutional and custom reverse proxies |
| [Sign-in methods](docs/sign_in.md) | Passwords, self-registration, ORCID and other OpenID Connect providers |
| [Crucible Hub](docs/hub.md) | The web interface, on the same host or a separate one |
| [File storage](docs/storage.md) | Data directory, file versions, external S3-compatible storage, Google Cloud Storage |
| [Operations](docs/operations.md) | Secrets, backups, restore, upgrades, cleanup jobs, removal |
| [Troubleshooting](docs/troubleshooting.md) | Common errors and their causes |

The settings behind these pages are described in [Authentication configuration](../../docs/sign_in_operations.md) and [Multipart uploads](../../docs/uploads.md).
