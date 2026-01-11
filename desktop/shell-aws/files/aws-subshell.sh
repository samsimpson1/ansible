#!/usr/bin/env zsh
# shellcheck shell=bash

govuk_awsume() {
  ENV_NAME="${1}"
  ROLE_NAME="${2}"
  ROLE="${ENV_NAME}-${ROLE_NAME}"

  ASSUME_DURATION="28800"
  if [ "${ROLE_NAME}" = "platformengineer" ]; then
    ASSUME_DURATION="3600"
  fi

  . awsume --role-duration "${ASSUME_DURATION}" "${ROLE}"
  if [ "${ENV_NAME}" != "test" ]; then
    kubectx "${1}"
    kubens apps
  fi
}

declare -A GOVUK_ENV_EMOJIS
declare -A GOVUK_ENV_COLOURS

GOVUK_ENV_EMOJIS=(
  ["production"]="⚠️ "
  ["staging"]="✅"
  ["integration"]="🛠️ "
  ["test"]="🧰"
)

GOVUK_ENV_COLOURS=(
  ["production"]="red"
  ["staging"]="yellow"
  ["integration"]="green"
  ["test"]="blue"
)

GOVUK_ENVIRONMENT="${1}"
AWS_ROLE_NAME="${2}"

govuk_awsume "${GOVUK_ENVIRONMENT}" "${AWS_ROLE_NAME}"

CURRENT_DATE=$(date "+%Y-%m-%d %H:%M:%S")

EMOJI="${GOVUK_ENV_EMOJIS[${GOVUK_ENVIRONMENT}]}"
COLOUR="${GOVUK_ENV_COLOURS[${GOVUK_ENVIRONMENT}]}"

export RPROMPT="%F{${COLOUR}}${GOVUK_ENVIRONMENT} %F{magenta}${AWS_ROLE_NAME}"

mkdir -p "${HOME}/aws-sessions"

cat <<EOF

AWS Session
-----------

Environment: ${EMOJI} ${GOVUK_ENVIRONMENT} ${EMOJI}
Role: ${AWS_ROLE_NAME}
ARN: $(aws sts get-caller-identity --query Arn --output text)

EOF

if [ "${3}" = "--" ]; then
  shift 3
  "$@"
  exit 0
fi

asciinema rec -q \
  -t "AWS Session ${GOVUK_ENVIRONMENT} ${AWS_ROLE_NAME} - ${CURRENT_DATE}" \
  -c zsh \
  "${HOME}/aws-sessions/${GOVUK_ENVIRONMENT}-${AWS_ROLE_NAME}-${CURRENT_DATE}.cast"
