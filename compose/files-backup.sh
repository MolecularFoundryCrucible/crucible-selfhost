#!/bin/sh
# Run by the files-backup service (README.md, "Backups"): copies every bucket to /backup/<bucket>,
# or back into the store. Copies never delete, so a backup keeps files the store no longer has.
read -r RCLONE_CONFIG_STORE_ACCESS_KEY_ID < /run/secrets/S3_ACCESS_KEY_ID
read -r RCLONE_CONFIG_STORE_SECRET_ACCESS_KEY < /run/secrets/S3_SECRET_ACCESS_KEY
export RCLONE_CONFIG_STORE_ACCESS_KEY_ID RCLONE_CONFIG_STORE_SECRET_ACCESS_KEY

case "$1" in
  backup | restore) ;;
  *) echo "usage: files-backup backup | restore" >&2; exit 2 ;;
esac
for bucket in $BUCKETS; do
  if [ "$1" = backup ]; then
    # An empty bucket still gets its folder, so a later restore finds it.
    mkdir -p "/backup/$bucket" || exit 1
    rclone copy --stats-one-line --stats 30s "store:$bucket" "/backup/$bucket" || exit 1
  elif [ -d "/backup/$bucket" ]; then
    rclone copy --stats-one-line --stats 30s "/backup/$bucket" "store:$bucket" || exit 1
  else
    echo "no backup of $bucket in this folder; skipped"
    continue
  fi
  echo "$1 of $bucket done"
done
