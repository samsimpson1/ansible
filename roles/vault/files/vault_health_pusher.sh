#!/usr/bin/env bash

DATA=$(curl "https://vault.int.simpson.id/v1/sys/health" -s)

SEALED=$(echo $DATA | jq -r '.sealed')

if [ "$SEALED" == "true" ]; then
  SEALED_VALUE=1
else
  SEALED_VALUE=0
fi

cat <<EOF | curl --data-binary @- https://prometheus-push.int.simpson.id/metrics/job/vault-health
# HELP vault_sealed_bool Whether Vault is sealed (1) or unsealed (0)
# TYPE vault_sealed_bool gauge
vault_sealed_bool $SEALED_VALUE
EOF