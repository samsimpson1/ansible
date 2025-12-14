#!/usr/bin/env bash

set -euo pipefail

VAULT_PW_FILE="/tmp/ansible-vault-$(id -u)"

if [ ! -s "${VAULT_PW_FILE}" ]; then
  touch "${VAULT_PW_FILE}"
  chmod 600 "${VAULT_PW_FILE}"
  op read "op://Infrastructure/ansible-vault/password" > "${VAULT_PW_FILE}"
fi

cat "${VAULT_PW_FILE}"