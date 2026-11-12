# Operations

Part of the [Docker Compose installation guide](../README.md). Commands run in `deploy/compose`.

## Secrets

Secrets are files in `secrets/`, provided to the containers as Docker Compose secrets (mounted at `/run/secrets/`, never placed in environment variables).

| File | Purpose |
|---|---|
| `POSTGRES_PASSWORD` | PostgreSQL administrator account: creates the database on first start, and is used for backups and the database health check. The API never uses it |
| `PGDB_PW` | The unprivileged `crucible` database account used by the API |
| `CRUCIBLE_SECRET_KEY` | Signs list cursors and the short-lived cookies and codes of the sign-in pages. Changing it interrupts sign-ins in progress, not existing sessions |
| `CRUCIBLE_AUTH_PEPPER` | Mixed into every password before it is stored, so that a copy of the database alone cannot be used to guess passwords. If it is lost, all passwords become unusable |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Key pair the API uses with the file store; SeaweedFS uses the same pair. With an external store, these files hold that store's key pair |

The directory is accessible only to its owner (`700`); the files are readable by all users (`644`) because the database container reads them as its own user.

Back up the secrets: a restored database requires the same `PGDB_PW`, `CRUCIBLE_SECRET_KEY` keeps existing sessions valid, and `CRUCIBLE_AUTH_PEPPER` keeps passwords valid. Store the copy of `CRUCIBLE_AUTH_PEPPER` in a different location from the database backups: the pepper protects stored passwords only while a copy of the database does not come with it.

### Other secret sources

Crucible reads each secret from exactly one of: a file named after it in the secrets directory (`/run/secrets` by default, or `CRUCIBLE_SECRETS_DIR`), a file named by `NAME_FILE`, or the `NAME` environment variable. Providing one secret through two sources stops the server with an error that names it. Any tool that writes secrets as files therefore works without changes:

- systemd: `LoadCredential=PGDB_PW:/etc/crucible/pgdb_pw` and `CRUCIBLE_SECRETS_DIR=%d`.
- Kubernetes: a Secret mounted as a volume at `/run/secrets`, or an external manager (Vault, AWS, Azure, Google) through the Secrets Store CSI Driver or the External Secrets Operator.
- Vault Agent or a similar sidecar: write each secret to a file and point `NAME_FILE` or `CRUCIBLE_SECRETS_DIR` at it.

## Backups

Back up the database, the stored files and the `secrets/` directory.

Warning: a database backup contains users' personal data, password hashes and API key hashes. Treat it like the secrets: encrypt it, and keep it in a private directory outside the repository.

Back up the database before the files: a file uploaded in between is then only an unreferenced extra, whereas the reverse order could leave a record referencing content missing from the backup.

The commands below encrypt the database backup with [age](https://age-encryption.org). Create a key pair once with `age-keygen -o ~/crucible-backup-key.txt`, store that file separately from the backups (a password manager, a second disk), and use the public key it prints (`age1...`) as the recipient.

```bash
mkdir -p ~/crucible-backups/files && chmod 700 ~/crucible-backups
(umask 077; docker compose exec -T db pg_dump --username postgres --dbname crucible --format custom | age --recipient age1yourpublickey > ~/crucible-backups/crucible-$(date +%F).dump.age)
docker compose run --rm --user "$(id -u):$(id -g)" files-backup
```

`files-backup` (rclone) copies both buckets through the S3 interface into `~/crucible-backups/files/`, or `CRUCIBLE_BACKUP_DIR/files/`, while the store is running, so uploads continue.

- Create the `files` directory first; otherwise Docker creates it owned by root and the copy cannot write to it.
- Each run copies only files not yet in the backup and never deletes from it. Stored files are never modified in place, so this incremental copy is a complete backup.
- The copy consists of plain files: `crucible-files/<dataset>/_files/<upload id>` for uploads (their names are in the database) and `crucible-records/<id>/record.json` for the metadata copies. Back up the directory further with standard tools (restic, rsync, a tape robot).
- With rootless Docker, omit `--user`.
- The same command backs up an external S3 store. It does not copy a Google Cloud Storage bucket (see [File storage](storage.md#google-cloud-storage)).

## Restore

Restoring into a running installation replaces its database and adds the backed-up files to the store. Stop `storage-cleanup` as well as `api`: while the database is partially restored, the cleanup could treat files as unreferenced and delete them.

```bash
docker compose stop api storage-cleanup
age --decrypt --identity ~/crucible-backup-key.txt ~/crucible-backups/crucible-2026-10-26.dump.age | docker compose exec -T db pg_restore --username postgres --dbname crucible --clean --if-exists
docker compose run --rm --user "$(id -u):$(id -g)" files-backup restore
docker compose up -d --wait
```

`up` runs the `migrate` step again, which upgrades a backup from an older version before the API starts. A backup from a newer version than the code cannot be restored; upgrade the code first.

To move to a new host, copy the repository, `.env`, `secrets/` and the backup; start the services once, then restore.

## Upgrading

```bash
(umask 077; docker compose exec -T db pg_dump --username postgres --dbname crucible --format custom | age --recipient age1yourpublickey > ~/crucible-backups/before-upgrade.dump.age)
git pull
docker compose up -d --build --wait
```

The `migrate` step applies pending database migrations before the new API starts. If a migration fails, the database remains at the last completed migration, the API does not start, and `docker compose logs migrate` reports the cause; fix it and run the same command again, or restore the backup.

After each upgrade, compare `.env` with `.env.example` for new settings. An installation created before 4.0.0 requires additional steps: see [Upgrading from 3.3.1 to 4.0.0](../../../docs/upgrading/3.3-to-4.0.md#docker-compose).

## Cleanup jobs

Two services run hourly and need no attention:

| Service | Command | Removes |
|---|---|---|
| `storage-cleanup` | `python -m app.cli storage cleanup` | Replaced file content past its retention period, and abandoned uploads (see [File storage](storage.md#file-versions-and-cleanup)) |
| `auth-cleanup` | `python -m app.cli auth cleanup` | Expired sign-in transactions, codes and Hub tokens, sign-in history older than one year (`CRUCIBLE_AUTH_EVENT_RETENTION_DAYS`), and accounts left pending approval for 30 days |

Either command accepts `--dry-run` to report what it would remove: `docker compose exec api python -m app.cli auth cleanup --dry-run`.

## Stopping and removing

`docker compose down` stops all services and keeps the data. With the Hub on the same host, stop the Hub project first: the shared `crucible` network cannot be removed while the Hub is attached.

Warning: `docker compose down -v` also deletes the database, the stored files (unless they are in a `CRUCIBLE_FILES_DIR` directory, which is kept) and the certificates; this cannot be undone.
