# File storage

Part of the [Docker Compose installation guide](../README.md). Commands run in `deploy/compose`.

The bundle stores files in SeaweedFS, an S3-compatible store that runs alongside the API. An external S3-compatible store or Google Cloud Storage can replace it; the choice is transparent to clients.

## How files are stored

- Uploaded files go to the `crucible-files` bucket. A copy of each record's metadata (`record.json` and `metadata.json`, written on every change) goes to `crucible-records`.
- Both buckets reside in the `seaweedfs-data` Docker volume (under `/var/lib/docker/volumes/`, or `~/.local/share/docker/volumes/` with rootless Docker) unless a [data directory](#data-directory) is configured.
- File content never passes through the API. Clients obtain short-lived signed URLs from the API and transfer the bytes directly, through Caddy at `/crucible-files/`, which forwards them to SeaweedFS unchanged and strips any API key or cookie the client sends.
- The records bucket is not reachable externally. SeaweedFS runs on a dedicated internal network that only the API and Caddy join; the Hub cannot reach it.

Signed URLs include the server address (`CRUCIBLE_PUBLIC_URL`, or `http://localhost:<port>` when it is unset), and the store validates it. All clients, including the Python client and the Hub, must therefore reach the server at that same address: a client that uses another name or port (`http://labbox:8080` instead of `http://localhost:8080`) receives `SignatureDoesNotMatch` on every upload and download. Set `CRUCIBLE_PUBLIC_URL` before the server is put into use.

File uploads require nano-crucible 3.3.0 or later with the default `upload_protocol` (`auto`); older versions, and `upload_protocol` `legacy`, use upload routes that no longer exist.

## Verifying storage

```bash
docker compose exec api python -m app.cli storage check
```

The command tests storage end to end: a signed two-part upload, a part with an incorrect checksum that must be refused, a signed download, the records bucket, and deletion of the test file. Run it after any change on this page.

## Data directory

To store the data on a specific disk (a large data disk or RAID array) instead of Docker's default location, create a directory on it owned by uid 1000, the user SeaweedFS runs as, and set it in `.env` before the first start:

```bash
sudo mkdir -p /srv/crucible/files
sudo chown 1000:1000 /srv/crucible/files
echo "CRUCIBLE_FILES_DIR=/srv/crucible/files" >> .env
```

Use a local disk mounted at boot (by UUID in `/etc/fstab`), not a network share. The directory holds SeaweedFS's internal data files, not individual uploads; access files through Crucible, or back them up as described in [Operations](operations.md#backups).

To move an existing installation's files there:

```bash
docker compose stop seaweedfs
docker run --rm -v crucible_seaweedfs-data:/from:ro -v /srv/crucible/files:/to alpine:3.22 cp -a /from/. /to/
echo "CRUCIBLE_FILES_DIR=/srv/crucible/files" >> .env
docker compose up -d --wait
```

Once uploads and downloads work, `docker volume rm crucible_seaweedfs-data` removes the old copy.

## File versions and cleanup

When a file is replaced, its previous content is retained for 14 days (`CRUCIBLE_FILE_VERSION_RETENTION_DAYS` in `.env`), so a replacement can be reverted:

```bash
docker compose exec api python -m app.cli files restore <file MFID>
```

This makes the newest retained version current and retains the content it replaces, so running it again reverts the restore.

The `storage-cleanup` service runs `python -m app.cli storage cleanup` every hour. It deletes retained versions older than the retention period that no file references, and aborts uploads that were started and abandoned.

- `docker compose exec api python -m app.cli storage cleanup --dry-run` reports what a run would do.
- `CRUCIBLE_STORAGE_CLEANUP_ENABLED=false` in `.env`, followed by `docker compose up -d --wait`, disables the service; old versions and abandoned uploads then remain in the bucket.
- Keep the retention period at least as long as the age of the oldest database backup that might be restored, so the files such a backup references still exist.

SeaweedFS reclaims the disk space of deleted files later, during background compaction (which runs once about 30% of a storage unit is deleted data), and compaction itself requires free space: keep a margin on the disk and monitor it. Deleting a file or a dataset currently removes only the database records, not the stored bytes; removal of the bytes is planned for a later version.

## External S3-compatible storage

An institutional or cloud object store can replace SeaweedFS. It must accept presigned URLs with signed `x-amz-checksum-crc32c` headers and refuse a part whose bytes do not match; `storage check` tests exactly this, so run it before relying on the store.

1. Create two buckets on the store.
2. Put its key pair in `secrets/S3_ACCESS_KEY_ID` and `secrets/S3_SECRET_ACCESS_KEY`.
3. In `.env`, remove `COMPOSE_PROFILES=bundled-storage` and set:

   ```bash
   CRUCIBLE_S3_ENDPOINT_URL=https://s3.myinstitution.org
   # The address clients reach the store on, when it differs from the endpoint.
   # CRUCIBLE_S3_PUBLIC_URL=https://s3.myinstitution.org
   CRUCIBLE_S3_REGION=us-east-1
   CRUCIBLE_UPLOAD_BUCKET=mylab-crucible-files
   CRUCIBLE_RECORD_BUCKET=mylab-crucible-records
   ```

4. Run `docker compose up -d --wait`, then `storage check`.

With the Hub, browser uploads go to the store's own address, so the upload bucket requires a CORS rule that allows `PUT` and `GET` from the Hub's address with the `x-amz-checksum-crc32c` and `content-type` headers and exposes `ETag`.

If the store cannot be served under a path of this site, serve it under its own name (for example `files.mylab.org`, with its own certificate) and set `CRUCIBLE_S3_PUBLIC_URL` to that address.

## Google Cloud Storage

Use `CRUCIBLE_STORAGE_BACKEND=gcs`, not Google's S3 interface, which rejects the checksums that S3 uploads send.

In the Google Cloud project:

1. Create a files bucket and a records bucket (uniform bucket-level access, public access prevention). On the files bucket, add lifecycle rules that delete replaced content after 14 days and abandoned uploads after eight days (an upload session lasts seven):

   ```json
   {"rule": [
     {"action": {"type": "Delete"}, "condition": {"daysSinceCustomTime": 14}},
     {"action": {"type": "AbortIncompleteMultipartUpload"}, "condition": {"age": 8}}
   ]}
   ```

   `files restore` and the version cleanup apply to S3 stores only.
2. Create a service account with Storage Object Admin on both buckets and Service Account Token Creator on itself, so that it can sign URLs without a key.
3. If the Hub uploads from browsers, add a CORS rule on the files bucket for the Hub's address: `PUT` and `GET`, headers `content-type` and `x-goog-hash`, exposing `ETag`.

Assign that identity to the server, using the first option that applies:

- **On Google Cloud** (a VM, Cloud Run, GKE): attach the service account; no key is needed. With GKE Workload Identity Federation for the Kubernetes service account itself, also set `MULTIPART_UPLOAD_SIGNER` to the service account's email and grant the Kubernetes identity Token Creator on it; the server then acts as that service account for all operations.
- **Elsewhere**, such as this bundle on a lab server: Workload Identity Federation, if the identity provider supports it. Otherwise a key, where the organization permits keys: save it as `secrets/google-credentials.json` and add `compose.override.yaml` next to `compose.yaml`:

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

Then run `docker compose up -d --wait` and `storage check`. `files-backup` copies S3 stores only; protect a Google bucket with Google's tools (object versioning, soft delete, or a copy to another bucket).
