# Troubleshooting

Part of the [Docker Compose installation guide](../README.md). Commands run in `deploy/compose`.

`docker compose ps -a` lists each service; `docker compose logs api migrate db seaweedfs` shows their logs.

## Startup

| Symptom | Cause and fix |
|---|---|
| `bind source path does not exist: .../secrets/<NAME>` | A secret file is missing; create it as in the quick start |
| `Missing required settings: ...` or `... is given more than one way ...` | The API names the setting; correct `.env` or `secrets/` and run `docker compose up -d --wait` again |
| `crucible: /run/secrets/PGDB_PW is missing, empty, or not readable` in the `db` logs, and `db` never becomes healthy | The files in `secrets/` must exist and be readable (`chmod 644 secrets/*`). The database's first start was interrupted, so start over: `docker compose down -v`, then `docker compose up -d --build --wait` |
| `permission denied` when reading `/run/secrets/...` on Fedora, RHEL, Rocky or AlmaLinux with SELinux enforcing | Label the directory for containers: `chcon -Rt container_file_t secrets` |
| The database rejects the password after `secrets/PGDB_PW` was changed | The password is set only when the database is first created. Set the same password inside the database (`docker compose exec db psql -U postgres -c '\password crucible'`, which prompts without echoing), then run `docker compose up -d --force-recreate --wait` so every service reads the new file |

## Network

| Symptom | Cause and fix |
|---|---|
| Clients fail with `tlsv1 alert internal error`; `docker compose logs proxy` shows `Timeout during connect (likely firewall problem)` | Caddy has no certificate: Let's Encrypt cannot reach ports 80 and 443 from the internet. Use another [certificate option](network.md#certificates) |
| `421` with "Crucible serves plain HTTP only on localhost" | The server was addressed by another name over plain HTTP. Use `http://localhost:<port>` (through an SSH port forward from another computer), or configure [HTTPS](network.md) |

## File storage

| Symptom | Cause and fix |
|---|---|
| `SignatureDoesNotMatch` on uploads or downloads | The client reached the server at an address other than `CRUCIBLE_PUBLIC_URL` (see [File storage](storage.md#how-files-are-stored)), or an upstream proxy changed the path or `Host` |
| `seaweedfs` is unhealthy and its log reports `permission denied` under `/data` | The directory in `CRUCIBLE_FILES_DIR` is not owned by uid 1000 (Docker creates a missing directory owned by root). Run `sudo chown -R 1000:1000` on it, then `docker compose up -d --wait` |
| Uploads and download links fail with `503` ("Storage is temporarily unavailable") after an upgrade, and `docker compose ps` shows no `seaweedfs` | `.env` lacks `COMPOSE_PROFILES=bundled-storage` (see [Upgrading from 3.3.1 to 4.0.0](../../../docs/upgrading/3.3-to-4.0.md#docker-compose)) |

## Hub

| Symptom | Cause and fix |
|---|---|
| `/hub/` returns `502` | The Hub is not running, or `CRUCIBLE_HUB_UPSTREAM` does not point at it. On a single host, run `docker compose ps` in the Hub's directory; the Hub must have joined the `crucible` network |
| `network crucible declared as external, but could not be found` when starting the Hub | Start the bundle first; it creates the network |
