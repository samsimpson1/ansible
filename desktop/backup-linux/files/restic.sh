#!/usr/bin/env bash

set -o pipefail
set -e

source $HOME/.restic-backup/env

r() {
    restic $@ -o sftp.command="${SFTP_COMMAND}"
}

r $@
