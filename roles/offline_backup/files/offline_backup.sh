#!/usr/bin/env bash
set -euo pipefail

# Color output functions
echo_error() {
    local message="$1"
    local code="${2:-1}"
    echo -e "\033[31m[ERROR]\033[0m $message" >&2
    exit "$code"
}

echo_info() {
    local message="$1"
    echo -e "\033[34m[INFO]\033[0m $message"
}

# Send Discord notification
discord() {
    local message="$1"
    local webhook_url="$2"

    if [[ -z "$webhook_url" ]]; then
        echo_error "Discord webhook URL is not set" 1
    fi

    local payload
    payload=$(printf '{"username": "Offline Backups", "content": "%s"}' "$message")

    if ! curl -s -H "Content-Type: application/json" -X POST -d "$payload" "$webhook_url" > /dev/null; then
        echo_error "Failed to send Discord notification" 1
    fi
}

# Mount drive by UUID
mount_drive() {
    local device="$1"
    local path="$2"

    echo_info "Mounting $device to $path"

    if ! mount "/dev/disk/by-uuid/$device" "$path"; then
        echo_error "Failed to mount $device to $path" 1
    fi
}

# Unmount drive and sync
unmount_drive() {
    local path="$1"

    echo_info "Unmounting $path"

    if ! umount "$path"; then
        echo_error "Failed to unmount $path" 1
    fi

    if ! sync; then
        echo_error "Failed to sync after unmounting $path" 1
    fi
}

# Perform rsync backup
do_rsync() {
    local path="$1"
    local backup_host="$2"
    local backup_port="$3"
    local backup_user="$4"
    local backup_password_path="$5"

    mkdir -p "$path/backup"

    echo_info "Starting rsync from $backup_user@$backup_host to $path"

    if ! sshpass -f "$backup_password_path" \
        rsync -avz --delete \
        -e "ssh -p$backup_port -o StrictHostKeyChecking=no" \
        "$backup_user@$backup_host:./" "$path"; then
        echo_error "rsync from $backup_user@$backup_host:$path failed" 1
    fi
}

# Main function
main() {
    if [[ $# -ne 1 ]]; then
        echo_error "Usage: offline_backup.sh <config_file>" 1
    fi

    local config="$1"

    # shellcheck source=/dev/null
    source "$config"

    # Variables from sourced config file
    # shellcheck disable=SC2153
    local device="$DEVICE_UUID"
    # shellcheck disable=SC2153
    local mount_path="$MOUNT_PATH"
    local backup_host="$BACKUP_TARGET"
    # shellcheck disable=SC2153
    local backup_port="$BACKUP_PORT"
    local backup_user="$BACKUP_USERNAME"
    # shellcheck disable=SC2153
    local backup_password_path="$BACKUP_PASSWORD_PATH"
    # shellcheck disable=SC2153
    local discord_webhook_url="$DISCORD_WEBHOOK_URL"

    discord "Starting offline backup" "$discord_webhook_url"

    if ! mount_drive "$device" "$mount_path"; then
        discord "Failed to mount backup drive" "$discord_webhook_url"
        echo_error "Failed to mount backup drive" 1
    fi

    if ! do_rsync "$mount_path/backup" "$backup_host" "$backup_port" "$backup_user" "$backup_password_path"; then
        discord "Offline backup failed during rsync" "$discord_webhook_url"
        unmount_drive "$mount_path" || true
        echo_error "Offline backup failed during rsync" 1
    fi

    if ! unmount_drive "$mount_path"; then
        discord "Failed to unmount backup drive" "$discord_webhook_url"
        echo_error "Failed to unmount backup drive" 1
    fi

    discord "Offline backup complete" "$discord_webhook_url"
}

main "$@"
