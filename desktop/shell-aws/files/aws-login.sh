#!/usr/bin/env zsh
# shellcheck shell=bash

TS="$(date +%s)"

GOVUK_ENVIRONMENT="${1}"
ROLE_NAME="${2}"

PROFILE_NAME="${GOVUK_ENVIRONMENT}-${ROLE_NAME}"

ACCOUNT_ID="$(aws sts get-caller-identity --profile default 2> /dev/null | jq -r '.Account')"

if [ ! "${ACCOUNT_ID}" = "622626885786" ]; then
  # use a private window so `aws login` doesn't cause a gds-users console session to be created in the regular browser
  if ! BROWSER="firefox --private-window %s" aws login; then
    echo "aws login failed"
    exit 1
  fi
fi

ROLE_ARN=$(aws configure get role_arn --profile "${PROFILE_NAME}")

SESSION_NAME="${GOVUK_ENVIRONMENT}-${ROLE_NAME}-${TS}"

if ! ROLE="$(aws sts assume-role --role-arn "${ROLE_ARN}" --role-session-name "${SESSION_NAME}")"; then
  echo "role assume failed"
  exit 1
fi

export AWS_ACCESS_KEY_ID
AWS_ACCESS_KEY_ID="$(echo "${ROLE}" | jq -r '.Credentials.AccessKeyId')"

export AWS_SECRET_ACCESS_KEY
AWS_SECRET_ACCESS_KEY="$(echo "${ROLE}" | jq -r '.Credentials.SecretAccessKey')"

export AWS_SESSION_TOKEN
AWS_SESSION_TOKEN="$(echo "${ROLE}" | jq -r '.Credentials.SessionToken')"

export AWS_DEFAULT_REGION
AWS_DEFAULT_REGION="eu-west-1"

# these are for starship to display in the command line
export AWSUME_PROFILE
AWSUME_PROFILE="${PROFILE_NAME}"

export AWSUME_EXPIRATION
AWSUME_EXPIRATION="$(echo "${ROLE}" | jq -r '.Credentials.Expiration')"
