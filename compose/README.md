# Installation with Docker Compose

The Docker Compose bundle in this directory runs Crucible on a single host: PostgreSQL (with pgvector), the Crucible API, SeaweedFS for file storage, and Caddy as the reverse proxy. It is intended for small deployments: one lab, a few workstations, and an administrator who sets it up once.

Supported: the API (projects, samples, datasets and their metadata, users, access control), file upload, replacement and download (see [File storage](#file-storage)), authentication with a password or through an identity provider such as ORCID or an institutional login (see [Signing in](#signing-in)), the nano-crucible Python client, API keys, and optionally the Crucible Hub web interface (see [Adding the Hub](#adding-the-hub)). Not included: the optional printing, ingestion and proposal integrations, which are disabled.

By default, the server is reachable only from the local host. This is sufficient for evaluation and single-user operation. [Putting it on a network](#putting-it-on-a-network) describes access from other hosts over HTTPS.

## Requirements

- Linux with Docker Engine 28 or later and the Compose plugin 2.20 or later (`docker version`, `docker compose version`). Older Docker releases allow other hosts on the same network segment to reach ports published only to the local host.
- About 2 GB of free memory and a few GB of disk to start; the database grows with the data.
- A copy of this repository. Images are built from it until versioned images are published.

## 1. Create the secrets

Secrets are files in `secrets/`, provided to the containers as Docker Compose secrets (mounted at `/run/secrets/`, never placed in environment variables). Create them once:

```bash
cd deploy/compose
mkdir -p secrets && chmod 700 secrets
for name in POSTGRES_PASSWORD PGDB_PW CRUCIBLE_SECRET_KEY CRUCIBLE_AUTH_PEPPER S3_SECRET_ACCESS_KEY; do
  openssl rand -hex 32 > "secrets/$name"
done
openssl rand -hex 16 > secrets/S3_ACCESS_KEY_ID
chmod 644 secrets/*
```

| File | Purpose |
|---|---|
| `POSTGRES_PASSWORD` | PostgreSQL administrator account: creates the database on first start, and is used for backups and the database health check. The API never uses it |
| `PGDB_PW` | The unprivileged `crucible` database account used by the API |
| `CRUCIBLE_SECRET_KEY` | Signs list cursors and the short-lived cookies and codes of the sign-in pages. Changing it interrupts sign-ins in progress, not existing sessions |
| `CRUCIBLE_AUTH_PEPPER` | Mixed into every password before it is stored, so that a copy of the database alone cannot be used to guess passwords. If it is lost, all passwords become unusable |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Key pair the API uses with the file store; SeaweedFS uses the same pair. With an external store, these files hold that store's key pair |

The directory is accessible only to its owner (`700`); the files are readable by all users (`644`) because the database container reads them as its own user. `secrets/` and `.env` are ignored by git. Back up the secrets: a restored database requires the same `PGDB_PW`, `CRUCIBLE_SECRET_KEY` keeps existing sessions valid, and `CRUCIBLE_AUTH_PEPPER` keeps passwords valid. Store the copy of `CRUCIBLE_AUTH_PEPPER` in a different location from the database backups: the pepper protects stored passwords only while a copy of the database does not come with it.

## 2. Configure

```bash
cp .env.example .env
```

The defaults serve `http://localhost:8080/api/v3/` to the local host only: Docker listens on `127.0.0.1`, so no traffic crosses a network, and Caddy refuses plain HTTP addressed to any other name. Edit `.env` to change the port or the number of API workers. Each setting is documented in `.env.example`.

## 3. Start the services

```bash
docker compose up -d --build --wait
```

On first start, Compose builds the API image, creates the database and its extensions, creates the schema (the one-time `migrate` service, which the API waits for), starts SeaweedFS with its two buckets, and then starts the API and Caddy. `--wait` returns once all services are healthy. Verify:

```bash
curl http://localhost:8080/api/v3/health/ready
```

The response contains `"status":"ok"` and `"schema_state":"current"`. The interactive API documentation is at `http://localhost:8080/api/v3/docs`.

## 4. Create the first administrator

```bash
docker compose run --rm api python -m app.cli admin create
```

The command prompts for a name, an optional email, an optional ORCID (without one, the account is assigned a Crucible MFID) and an optional username, then asks for confirmation. It prints two values as one line of JSON:

- `password_link`: open it in a browser on the server host to set the administrator's password. It is valid once, for 24 hours.
- `api_key`: an API key that authenticates as the administrator from scripts. Treat it as a password and store it in a password manager.

Warning: run this command interactively only, never as an automated step, where the key and the link would be written to logs. For non-interactive use, pass every value and `--no-input`:

```bash
docker compose run --rm -T api python -m app.cli admin create --no-input --first-name Ada --last-name Lovelace --email ada@example.org
```

A second administrator requires `--allow-additional`, so an accidental second run has no effect.

## 5. Connect the Python client

```bash
pip install nano-crucible
crucible config set api_url http://localhost:8080/api/v3
crucible config set api_key <the key from step 4>
crucible config show
```

Alternatively, set `CRUCIBLE_API_URL` and `CRUCIBLE_API_KEY` in the environment. In Python, `CrucibleClient(api_url=..., api_key=...)` accepts them directly. With nano-crucible 4.0 or later, `crucible login` authenticates with a password in a browser instead of an API key. File uploads require nano-crucible 3.3.0 or later with the default `upload_protocol` (`auto`); older versions, and `upload_protocol` `legacy`, use upload routes that work only with Google Cloud Storage.

To test from a second host before HTTPS is configured, forward the port over SSH and use the same address there: `ssh -L 8080:localhost:8080 you@server`.

## Putting it on a network

Other hosts reach the server by a single name, over HTTPS, with a certificate that browsers and Python already trust. Choose the name once and keep it: the Hub, nano-crucible, sign-in and every upload or download link include it, and migrating to a larger server later only requires pointing the name at the new host.

In `.env`, set these together:

```bash
CRUCIBLE_SITE_ADDRESS=crucible.mylab.org
CRUCIBLE_HTTP_PORT=80
CRUCIBLE_HTTPS_PORT=443
CRUCIBLE_BIND_ADDRESS=0.0.0.0
CRUCIBLE_PUBLIC_URL=https://crucible.mylab.org
```

Then run `docker compose up -d --wait`. Use the bare name in `CRUCIBLE_SITE_ADDRESS`, without `https://` or a port. With rootless Docker, ports below 1024 require `sudo sysctl net.ipv4.ip_unprivileged_port_start=80`. Users outside the lab network should connect through the institution's VPN rather than through a server exposed to the internet, unless external collaborators need access.

### Certificates

Caddy requires a certificate for that name. Use the first option that applies:

1. **Institutional certificate.** Most universities and national laboratories manage their own DNS and run a certificate service; request a name and a certificate for it from IT. If the service supports ACME (the protocol used by Let's Encrypt, which many do), Caddy renews the certificate automatically. Put the settings provided by IT in `local/global-acme.caddy`:

   ```
   acme_ca https://acme.myinstitution.edu/directory
   acme_eab {
   	key_id YOUR_KEY_ID
   	mac_key YOUR_MAC_KEY
   }
   ```

   If IT provides certificate files instead, save them as `local/cert.pem` and `local/key.pem`, write `local/site-tls.caddy` as follows, and renew the files manually before they expire:

   ```
   tls /etc/caddy/local/cert.pem /etc/caddy/local/key.pem
   ```

2. **Server reachable from the internet.** With the name's DNS record pointing at the server and ports 80 and 443 open, Caddy obtains and renews a Let's Encrypt certificate with no further configuration.

3. **Own domain, server not reachable from the internet.** Let's Encrypt can validate the name through its DNS records instead. This requires a Caddy image built with the DNS provider's module ([caddy-dns](https://github.com/caddy-dns), using Caddy's official builder image), a provider token limited to that one zone, and `acme_dns` with that token in `local/global-acme.caddy`. The bundle does not ship such an image, and this option has not been tested with it yet. Some routers refuse public names that resolve to local addresses; if the name does not resolve inside the lab, add it to the lab's DNS.

Files in `local/` are read only by Caddy, are not tracked in git, and may contain credentials: restrict the directory in the same way as `secrets/` (`chmod 700 local`). Caddy's internal certificate authority (`CRUCIBLE_SITE_ADDRESS=localhost`) is for single-host evaluation only, since every other device would need its root certificate installed.

### Behind an institutional reverse proxy

When an institutional reverse proxy or load balancer already terminates HTTPS and forwards to this host, keep Caddy on plain HTTP, listen on an address the proxy can reach, and name the host it forwards for:

```bash
CRUCIBLE_BIND_ADDRESS=10.0.0.5
CRUCIBLE_HTTP_HOSTS=crucible.mylab.org
CRUCIBLE_PUBLIC_URL=https://crucible.mylab.org
```

Caddy ignores forwarding headers from another proxy until that proxy is declared trusted. Add its address to `local/global-proxy.caddy`:

```
servers {
	trusted_proxies static 10.0.0.1/32
}
```

The proxy must pass `Host`, set `X-Forwarded-For` to the client address and `X-Forwarded-Proto` to `https`, and be the only host that can reach this port. Without the trusted address, all users appear to connect from the proxy, and the sign-in attempt limits treat them as a single client. [Using your own reverse proxy](#using-your-own-reverse-proxy) lists the requirements for replacing Caddy entirely.

## Signing in

**Passwords** are enabled and intended for small deployments. An administrator creates each user (`POST /users`, or the Hub's Users page) and sends them a one-time link to set their password: `POST /users/{user_ref}/password-link`, or on the server `docker compose run --rm api python -m app.cli admin password-link USER`. Passwords require at least 15 characters; repeated guessing is slowed and then locked per account.

- **Self-registration:** `CRUCIBLE_AUTH_PASSWORD_REGISTRATION=approval` adds a page at `/api/v3/oauth/register`. Each request waits for administrator approval: `docker compose run --rm api python -m app.cli admin pending`, then `admin approve USER` or `admin reject USER` (or the Hub's Users page).
- **Locked-out administrator:** `admin password-link USER` works for any account, so a new link restores access.
- **Incident response:** `docker compose run --rm api python -m app.cli auth revoke-passwords --commit` removes every password and ends the sessions created with them, and `auth end-sessions --all --commit` ends all sessions; then issue new links. API keys are separate: revoke them with `DELETE /users/{user_ref}/apikey`.

**An identity provider** (ORCID, or an institutional login through any OpenID Connect service such as Keycloak, Authentik or Entra ID) suits larger groups: no passwords are managed locally, and users who leave lose access at the source. Identity providers require HTTPS. For ORCID, add `compose.orcid.yaml` (see [Adding the Hub](#adding-the-hub)). For other providers, or several at once, list them in `CRUCIBLE_AUTH_PROVIDERS` as in `auth-providers.example.json` and [the provider list](../../docs/sign_in_operations.md#the-provider-list); each entry specifies whether new users are refused, wait for approval, or are admitted immediately. When passwords and a provider are both enabled, the sign-in page offers the choice. Once a provider is configured, set `CRUCIBLE_AUTH_PASSWORD_ENABLED=false` unless some users still need passwords.

## File storage

Uploaded files are stored in SeaweedFS, an S3-compatible store included in the bundle, in the `crucible-files` bucket; a copy of each record's metadata (`record.json` and `metadata.json`, written on every change) is stored in `crucible-records`. Both reside in the `seaweedfs-data` Docker volume (under `/var/lib/docker/volumes/`, or `~/.local/share/docker/volumes/` with rootless Docker) unless a directory is configured as described below. File content never passes through the API: clients obtain short-lived signed URLs from the API and upload or download the bytes directly, through Caddy at `/crucible-files/`, which forwards them to SeaweedFS unchanged and strips any API key or cookie the client sends. The records bucket is not reachable externally. SeaweedFS runs on a dedicated internal network that only the API and Caddy join; the Hub cannot reach it.

Signed URLs include the server address (`CRUCIBLE_PUBLIC_URL`, or `http://localhost:<port>` when it is unset), and the store validates it: all clients, including the Python client and the Hub, must reach the server at that same address. A client that uses another name or port (`http://labbox:8080` instead of `http://localhost:8080`) receives `SignatureDoesNotMatch` errors on every upload and download. Set `CRUCIBLE_PUBLIC_URL` before the server is put into use.

To verify storage end to end (a signed two-part upload, a part with an incorrect checksum that must be refused, a signed download, the records bucket, and deletion of the test file):

```bash
docker compose exec api python -m app.cli storage check
```

### Custom storage directory

To store the data on a specific disk (a large data disk or RAID array) instead of Docker's default location, create a directory on it owned by uid 1000, the user SeaweedFS runs as, and set it in `.env` before the first start:

```bash
sudo mkdir -p /srv/crucible/files
sudo chown 1000:1000 /srv/crucible/files
echo "CRUCIBLE_FILES_DIR=/srv/crucible/files" >> .env
```

Use a local disk mounted at boot (by UUID in `/etc/fstab`), not a network share. The directory holds SeaweedFS's internal data files, not individual uploads; access files through Crucible or back them up as described below. To move an existing installation's files there:

```bash
docker compose stop seaweedfs
docker run --rm -v crucible_seaweedfs-data:/from:ro -v /srv/crucible/files:/to alpine:3.22 cp -a /from/. /to/
echo "CRUCIBLE_FILES_DIR=/srv/crucible/files" >> .env
docker compose up -d --wait
```

Once uploads and downloads work, `docker volume rm crucible_seaweedfs-data` removes the old copy.

### File versions, restore and cleanup

When a file is replaced, its previous content is retained for 14 days (`CRUCIBLE_FILE_VERSION_RETENTION_DAYS` in `.env`), so a replacement can be reverted:

```bash
docker compose exec api python -m app.cli files restore <file MFID>
```

This makes the newest retained version current and retains the content it replaces, so running it again reverts the restore. The `storage-cleanup` service runs `python -m app.cli storage cleanup` every hour: it deletes retained versions older than the grace period that no file references, and aborts uploads that were started and abandoned. To disable it, set `CRUCIBLE_STORAGE_CLEANUP_ENABLED=false` in `.env` and run `docker compose up -d --wait`; old versions and abandoned uploads then remain in the bucket. `docker compose exec api python -m app.cli storage cleanup --dry-run` reports what it would do, also while cleanup is disabled. Keep the grace period at least as long as the age of the oldest database backup that might be restored, so the files such a backup references still exist.

SeaweedFS reclaims the disk space of deleted files later, during background compaction (which runs once about 30% of a storage unit is deleted data), and compaction itself requires free space: keep a margin on the disk and monitor it. Deleting a file or a dataset currently removes only the database records, not the stored bytes; removal of the bytes is planned for a later version.

### Authentication record cleanup

The `auth-cleanup` service runs `python -m app.cli auth cleanup` every hour: it deletes expired sign-in transactions, codes and Hub tokens, sign-in history older than one year, and accounts left pending approval for 30 days. Set `CRUCIBLE_AUTH_EVENT_RETENTION_DAYS` in `.env` to change the history retention. `docker compose exec api python -m app.cli auth cleanup --dry-run` reports what it would remove.

### External S3-compatible storage

An institutional or cloud object store can replace SeaweedFS. It must accept presigned URLs with signed `x-amz-checksum-crc32c` headers and refuse a part whose bytes do not match; `storage check` tests exactly this, so run it before relying on the store. Create two buckets on it, put its key pair in `secrets/S3_ACCESS_KEY_ID` and `secrets/S3_SECRET_ACCESS_KEY`, and in `.env` remove `COMPOSE_PROFILES=bundled-storage` and set:

```bash
CRUCIBLE_S3_ENDPOINT_URL=https://s3.myinstitution.org
# The address clients reach the store on, when it differs from the endpoint.
# CRUCIBLE_S3_PUBLIC_URL=https://s3.myinstitution.org
CRUCIBLE_S3_REGION=us-east-1
CRUCIBLE_UPLOAD_BUCKET=mylab-crucible-files
CRUCIBLE_RECORD_BUCKET=mylab-crucible-records
```

Then run `docker compose up -d --wait` and `docker compose exec api python -m app.cli storage check`. Browser uploads from the Hub then go to the store's own address, so the upload bucket requires a CORS rule that allows `PUT` and `GET` from the Hub's address with the `x-amz-checksum-crc32c` and `content-type` headers and exposes `ETag`.

If the store cannot be served under a path of this site, serve it under its own name (for example `files.mylab.org`, with its own certificate) and set `CRUCIBLE_S3_PUBLIC_URL` to that address.

### Google Cloud Storage

The backend is transparent to clients. Use `CRUCIBLE_STORAGE_BACKEND=gcs`, not Google's S3 interface, which rejects the checksums that S3 uploads send. In the Google Cloud project:

1. Create a files bucket and a records bucket (uniform bucket-level access, public access prevention). On the files bucket, add lifecycle rules that delete replaced content after 14 days and abandoned uploads after eight days (an upload session lasts seven): `{"rule": [{"action": {"type": "Delete"}, "condition": {"daysSinceCustomTime": 14}}, {"action": {"type": "AbortIncompleteMultipartUpload"}, "condition": {"age": 8}}]}`. `files restore` and the version cleanup apply to S3 stores only.
2. Create a service account with Storage Object Admin on both buckets and Service Account Token Creator on itself, so that it can sign URLs without a key.
3. If the Hub uploads from browsers, add a CORS rule on the files bucket for the Hub's address: `PUT` and `GET`, headers `content-type` and `x-goog-hash`, exposing `ETag`.

Assign that identity to the server, using the first option that applies:

- On Google Cloud (a VM, Cloud Run, GKE): attach the service account; no key is needed. With GKE Workload Identity Federation for the Kubernetes service account itself, also set `MULTIPART_UPLOAD_SIGNER` to the service account's email and grant the Kubernetes identity Token Creator on it; the server then acts as that service account for all operations.
- Elsewhere, such as this bundle on a lab server: Workload Identity Federation, if the identity provider supports it. Otherwise a key, where the organization permits keys: save it as `secrets/google-credentials.json` and add `compose.override.yaml` next to `compose.yaml`:

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

Then run `docker compose up -d --wait` and `docker compose exec api python -m app.cli storage check`. `files-backup` copies S3 stores only; protect a Google bucket with Google's tools (object versioning, soft delete, or a copy to another bucket).

## Adding the Hub

The Crucible Hub is the web interface. Users sign in to it through the API, with a password or an identity provider such as ORCID. It is optional: without it, the API, API keys and the Python client work unchanged. The Hub is a separate Compose project, from the [crucible-hub repository](https://github.com/MolecularFoundryCrucible/crucible-hub/tree/v1.7.1/deploy/compose) at release `v1.7.1`, with its own small database for sign-in sessions. The Hub publishes a prebuilt image, `ghcr.io/molecularfoundrycrucible/crucible-hub:1.7.1` (amd64 and arm64), so no build is required; its `gov.lbl.crucible.api.min-version` label names the oldest compatible Crucible API version (3.2.0). It runs on the same host or on a separate one; in both cases the bundle's Caddy serves it at `/hub/`, so users access a single address.

### Prerequisites

- **HTTPS**, configured as in [Putting it on a network](#putting-it-on-a-network): sign-in sets secure cookies, so this Hub release does not work over plain HTTP.

### 1. Enable Hub sign-in in the API

Create the secret shared by the API and the Hub:

```bash
openssl rand -hex 32 > secrets/HUB_AUTH_CLIENT_SECRET
chmod 644 secrets/*
```

In `.env`:

```bash
COMPOSE_FILE=compose.yaml:compose.hub.yaml
# Public address: no /api/v3, no trailing slash; include the port if it is not 443.
CRUCIBLE_PUBLIC_URL=https://crucible.mylab.org
```

`compose.hub.yaml` adds the Hub to the client applications allowed to sign users in, alongside the nano-crucible command-line interface. Users then sign in to the Hub with their password.

**ORCID.** To offer ORCID as well, register Public API credentials at [ORCID developer tools](https://orcid.org/developer-tools) (free; requires a verified email), with the redirect URI `https://<your address>/api/v3/oauth/callback/orcid`, including the port when it is not 443. ORCID accepts only HTTPS and requires an exact match of the address. For evaluation, use the [ORCID sandbox](https://sandbox.orcid.org) and its separate accounts. Then:

```bash
printf '%s' 'your-orcid-client-secret' > secrets/ORCID_CLIENT_SECRET
chmod 644 secrets/*
```

```bash
COMPOSE_FILE=compose.yaml:compose.hub.yaml:compose.orcid.yaml
ORCID_CLIENT_ID=APP-XXXXXXXXXXXXXXXX
# For the ORCID sandbox:
# ORCID_ISSUER=https://sandbox.orcid.org
```

The sign-in page then offers both methods. For other providers, or several, see [the provider list](../../docs/sign_in_operations.md#the-provider-list) and `auth-providers.example.json`.

Then run `docker compose up -d --wait`. Until the Hub is running, `/hub/` returns `502`.

### 2a. Hub on the same host

```bash
git clone --branch v1.7.1 https://github.com/MolecularFoundryCrucible/crucible-hub.git
cd crucible-hub/deploy/compose
```

Follow its `README.md`: copy the bundle's `secrets/HUB_AUTH_CLIENT_SECRET` to its `secrets/hub_auth_client_secret`, create its other secrets, copy `example.env` to `.env`, and set `HUB_IMAGE=ghcr.io/molecularfoundrycrucible/crucible-hub:1.7.1`, `HUB_PUBLIC_ORIGIN=https://crucible.mylab.org`, and `HUB_AUTH_PUBLIC_API_URL=https://crucible.mylab.org/api/v3`. Its defaults join the bundle's `crucible` network and call the API at `http://api:8000`. Start it after the bundle, which creates the network, with `docker compose pull hub hub-setup` followed by `docker compose up -d --wait`. `https://crucible.mylab.org/hub/health` then returns `{"status":"ok","sessions":"ok"}`.

### 2b. Hub on a separate host

On the second host, clone the same release and create the Hub's secrets as in 2a (copying `HUB_AUTH_CLIENT_SECRET` from the API host). In its `.env`, comment out the same-machine block and use the separate-machine block: `COMPOSE_FILE=compose.yaml:compose.published.yaml`, `HUB_BIND_ADDRESS` set to the address on which the API host reaches it, and `CRUCIBLE_API_BASE_URL=https://crucible.mylab.org/api/v3`; set `HUB_IMAGE`, `HUB_PUBLIC_ORIGIN`, and `HUB_AUTH_PUBLIC_API_URL` as in 2a. Start it with `docker compose pull hub hub-setup` and `docker compose up -d --wait`. Then, in the bundle's `.env` on the API host, set `CRUCIBLE_HUB_UPSTREAM=<that address>:3000` (an address and port, without `http://`) and run `docker compose up -d --wait`.

Warning: Caddy connects to the Hub over plain HTTP, and that connection carries sign-in cookies, so it must be encrypted. Place both hosts on a WireGuard or Tailscale network, use the Hub's address on that network, and allow only the API host to reach the Hub's port. A shared LAN alone is not sufficient.

### Internal traffic

HTTPS terminates at Caddy. Behind it, Caddy, the API and the Hub communicate over plain HTTP, and those connections carry API keys, sign-in tokens and cookies, and, when the Hub exchanges a sign-in, the shared client secret. On a single host this is the usual setup and is safe as configured here: the database is on an internal network that only the API joins (the Hub cannot reach it), every container drops the Linux capabilities that would allow it to intercept other containers' traffic and cannot gain new privileges, and nothing else should be attached to the `crucible` network. This is not a zero-trust architecture, in which every connection is encrypted and authenticated (NIST SP 800-207). Any connection that leaves the host requires encryption: the Hub refuses plain HTTP to the API except to a container name or a private address, and the connection to a Hub on a separate host must use an encrypted private network as described above. To encrypt traffic within the host as well, Caddy can issue internal certificates (`tls internal`) for an additional HTTPS address in front of the API, the Hub can call that address, and the Hub can be given Caddy's root certificate through `NODE_EXTRA_CA_CERTS`; this requires no code change but is not configured here.

### Removing the Hub

Stop the Hub project (`docker compose down` in its directory; add `-v` to delete its session database), remove `COMPOSE_FILE` (and `CRUCIBLE_HUB_UPSTREAM`, if set) from the bundle's `.env`, and run `docker compose up -d --wait`. The API's data is unaffected; `/hub/` returns `404`.

## Backups

Back up the database, the stored files and the `secrets/` directory. Warning: a database backup contains every user's API key. Treat it like the secrets: encrypt it, and keep it in a private directory outside the repository. Back up the database before the files: a file uploaded in between is then only an unreferenced extra, whereas the reverse order could leave a record referencing content missing from the backup.

The commands below encrypt the database backup with [age](https://age-encryption.org). Create a key pair once with `age-keygen -o ~/crucible-backup-key.txt`, store that file separately from the backups (a password manager, a second disk), and use the public key it prints (`age1...`) as the recipient. Without the key file, the backup reveals nothing.

```bash
mkdir -p ~/crucible-backups/files && chmod 700 ~/crucible-backups
(umask 077; docker compose exec -T db pg_dump --username postgres --dbname crucible --format custom | age --recipient age1yourpublickey > ~/crucible-backups/crucible-$(date +%F).dump.age)
docker compose run --rm --user "$(id -u):$(id -g)" files-backup
```

`files-backup` (rclone) copies both buckets through the S3 interface into `~/crucible-backups/files/` (or `CRUCIBLE_BACKUP_DIR/files/`; create that `files` directory first, otherwise Docker creates it owned by root and the copy cannot write to it) while the store is running, so uploads continue. Each run copies only files not yet in the backup and never deletes from it. Stored files are never modified in place, so this incremental copy is a complete backup. The copy consists of plain files: `crucible-files/<dataset>/_files/<upload id>` for uploads (their names are in the database) and `crucible-records/<id>/record.json` for the metadata copies. Back up the directory further with standard tools (restic, rsync, a tape robot). With rootless Docker, omit `--user`. The same command backs up an external S3 store when one is used instead of SeaweedFS.

To restore into a running installation (this replaces its database and adds the backed-up files to the store), stop `storage-cleanup` as well as `api`: while the database is partially restored, the cleanup could treat files as unreferenced and delete them.

```bash
docker compose stop api storage-cleanup
age --decrypt --identity ~/crucible-backup-key.txt ~/crucible-backups/crucible-2026-10-26.dump.age | docker compose exec -T db pg_restore --username postgres --dbname crucible --clean --if-exists
docker compose run --rm --user "$(id -u):$(id -g)" files-backup restore
docker compose up -d --wait
```

`up` runs the `migrate` step again, which upgrades a backup from an older version before the API starts. A backup from a newer version than the code cannot be restored; upgrade the code first.

To migrate to a new host, copy the repository, `.env`, `secrets/` and the backup; start once (step 3), then restore.

## Upgrading

```bash
(umask 077; docker compose exec -T db pg_dump --username postgres --dbname crucible --format custom | age --recipient age1yourpublickey > ~/crucible-backups/before-upgrade.dump.age)
git pull
docker compose up -d --build --wait
```

The `migrate` step applies pending database migrations before the new API starts. If a migration fails, the database remains at the last completed migration, the API does not start, and `docker compose logs migrate` reports the cause; fix it and run the same command again, or restore the backup.

An installation created before 4.0.0 requires additional steps: see [Upgrading from 3.3.1 to 4.0.0](../../docs/upgrading/3.3-to-4.0.md#docker-compose).

After each upgrade, compare `.env` with `.env.example` for other new settings.

## Stopping and removing

`docker compose down` stops all services and keeps the data. With the Hub on the same host, stop the Hub project first: the shared `crucible` network cannot be removed while the Hub is attached. Warning: `docker compose down -v` also deletes the database, the stored files (unless they are in a `CRUCIBLE_FILES_DIR` directory, which is kept) and the certificates; this cannot be undone.

## Alternative secret sources

Crucible reads each secret from exactly one of: a file named after it in the secrets directory (`/run/secrets` by default, or `CRUCIBLE_SECRETS_DIR`), a file named by `NAME_FILE`, or the `NAME` environment variable. Providing one secret through two sources stops the server with an error that names it. Any tool that writes secrets as files therefore works without changes:

- systemd: `LoadCredential=PGDB_PW:/etc/crucible/pgdb_pw` and `CRUCIBLE_SECRETS_DIR=%d`.
- Kubernetes: a Secret mounted as a volume at `/run/secrets`, or an external manager (Vault, AWS, Azure, Google) through the Secrets Store CSI Driver or the External Secrets Operator.
- Vault Agent or a similar sidecar: write each secret to a file and point `NAME_FILE` or `CRUCIBLE_SECRETS_DIR` at it.

## Using your own reverse proxy

Caddy can be replaced by any reverse proxy that meets these requirements:

- `/api/v3/` routes to the API (`api:8000` inside Compose, or the API container's port) with the `/api/v3` prefix removed; the API serves its documentation under that prefix (`API_PATH=api/v3`).
- Pass `Host`, `X-Forwarded-For` (set to the client address, not appended to the value the client sent), and `X-Forwarded-Proto`. The API trusts forwarding headers from any address (`FORWARDED_ALLOW_IPS="*"`), so it must be reachable only through the proxy.
- Allow request bodies of 10 MB, 20 MB for thumbnails (the API's own limits), and read timeouts of at least 60 seconds.
- Limit the sign-in routes, `/api/v3/oauth/` and `/api/v3/auth/hub/`, to 8 KB bodies and a 20 second timeout, as Caddy does here.
- `/crucible-files/` routes to SeaweedFS (`seaweedfs:8333`) with the path and `Host` unchanged, since the store validates the signed URL against both. Remove the `Authorization` and `Cookie` request headers, allow request bodies of 64 MB (one upload part) and read timeouts of a few minutes, and do not compress responses. Add `Content-Security-Policy: sandbox; default-src 'none'`, `X-Content-Type-Options: nosniff`, and `Cross-Origin-Resource-Policy: same-site` to the responses, so that a downloaded file never runs as a page of the site and other sites cannot embed it ([web.dev, "Securely hosting user data"](https://web.dev/articles/securely-hosting-user-data)); current Chrome and Firefox still display PDFs and images in the browser with these headers. Do not route the records bucket.
- With the Hub: `/hub/` routes to the Hub (`hub:3000`) with the prefix kept. `X-Forwarded-For` must again be set, not appended: the Hub limits sign-in attempts per client address and trusts one proxy (`HUB_TRUSTED_PROXY_HOPS=1`).

Example nginx configuration, for nginx running as a service in the same Compose project (remove the `proxy` service and publish nginx instead):

```nginx
server {
    listen 80;
    server_name crucible.mylab.org;
    client_max_body_size 20m;

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

- `/hub/` returns `502`: the Hub is not running, or `CRUCIBLE_HUB_UPSTREAM` does not point at it. On a single host, run `docker compose ps` in the Hub's directory; the Hub must have joined the `crucible` network.
- `network crucible declared as external, but could not be found` when starting the Hub: start the bundle first; it creates the network.

- `docker compose ps -a` lists each service; `docker compose logs api migrate db seaweedfs` shows their logs.
- Uploads and download links fail with `503` ("Storage is temporarily unavailable") after an upgrade, and `docker compose ps` shows no `seaweedfs`: `.env` lacks `COMPOSE_PROFILES=bundled-storage` (see [Upgrading from 3.3.1 to 4.0.0](../../docs/upgrading/3.3-to-4.0.md#docker-compose)).
- `seaweedfs` is unhealthy and its log reports `permission denied` under `/data`: the directory in `CRUCIBLE_FILES_DIR` is not owned by uid 1000 (Docker creates a missing directory owned by root). Run `sudo chown -R 1000:1000` on it, then `docker compose up -d --wait`.
- `SignatureDoesNotMatch` on uploads or downloads: the client reached the server at an address other than `CRUCIBLE_PUBLIC_URL` (see [File storage](#file-storage)), or an upstream proxy changed the path or `Host`.
- `bind source path does not exist: .../secrets/<NAME>`: a secret file is missing; create it as in step 1.
- `Missing required settings: ...` or `... is given more than one way ...`: the API names the setting; correct `.env` or `secrets/` and run `docker compose up -d --wait` again.
- The database rejects the password after `secrets/PGDB_PW` was changed: the password is set only when the database is first created. Set the same password inside the database (`docker compose exec db psql -U postgres -c '\password crucible'`, which prompts for it without echoing it), then run `docker compose up -d --force-recreate --wait` so every service reads the new file.
- On Fedora, RHEL, Rocky or AlmaLinux with SELinux enforcing, `permission denied` when reading `/run/secrets/...`: label the directory for containers with `chcon -Rt container_file_t secrets`.
- `crucible: /run/secrets/PGDB_PW is missing, empty, or not readable` in the `db` logs, and `db` never becomes healthy: the files in `secrets/` must exist and be readable (`chmod 644 secrets/*`). The database's first start was interrupted, so start over: `docker compose down -v`, then `docker compose up -d --build --wait`.
