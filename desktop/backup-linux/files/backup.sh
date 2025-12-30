#!/usr/bin/env bash

set -o pipefail
set -e
set -x

RESTIC="/home/sam/.restic-backup/restic.sh"

# copy Steam user data out of .local
mkdir -p /home/sam/.steam-user-data
rsync -avz --delete /home/sam/.local/share/Steam/userdata /home/sam/.steam-user-data

if ! $RESTIC cat config; then
    echo "repository doesn't exist. creating"
    $RESTIC init
else
    echo "repository already exists"
fi

$RESTIC backup --exclude-file $HOME/.restic-backup/excludes.txt "/home/sam"

$RESTIC forget -H 24 -d 7 -w 8 -m 12 -y 2

STATS=$($RESTIC stats --json --mode raw-data)
SIZE_BYTES=$(jq -r '.total_size' <<< "${STATS}")
SNAPSHOT_COUNT=$(jq -r '.snapshots_count' <<< "${STATS}")

LAST_SNAPSHOT=$($RESTIC snapshots --json --latest 1 | jq -r '.[0].time' | date +"%s" -f -)

cat <<EOF | curl --data-binary @- https://prometheus-push.int.simpson.id/metrics/job/backup-restic-desktop
# HELP backup_restic_last_snapshot Unix time of the latest snapshot in repository
# TYPE backup_restic_last_snapshot gauge
backup_restic_last_snapshot{repository="desktop"} ${LAST_SNAPSHOT}
# HELP backup_size_bytes Size of the backup repository in bytes
# TYPE backup_size_bytes gauge
backup_size_bytes{repository="desktop",kind="restic"} ${SIZE_BYTES}
# HELP backup_restic_snapshot_count Number of snapshots in repository
# TYPE backup_restic_snapshot_count gauge
backup_restic_snapshot_count{repository="desktop"} ${SNAPSHOT_COUNT}
# HELP backup_last_run_timestamp Timestamp of the last successful run
# TYPE backup_last_run_timestamp gauge
backup_last_run_timestamp{repository="desktop",kind="restic"} $(date +%s)
EOF
