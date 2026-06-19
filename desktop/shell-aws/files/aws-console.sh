#!/usr/bin/env bash

# Usage:
#   aws-console.sh [destination]
#
#   destination   Service path (default: "console") or a full https:// URL.
#
# Examples:
#   aws-console.sh          # open the console home
#   aws-console.sh ec2      # open the EC2 console

set -euo pipefail

AMAZON_DOMAIN="aws.amazon.com"

# Percent-encode a string for use in a query parameter.
urlencode() {
    jq -rn --arg s "$1" '$s|@uri'
}

destination="${1:-console}"
region="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"

# Build the destination URL the console should land on after login.
if [[ "$destination" == https://* || "$destination" == http://* ]]; then
    # Allow {region} / {amazon_domain} templating in a full URL.
    target_url="${destination//\{region\}/$region}"
    target_url="${target_url//\{amazon_domain\}/$AMAZON_DOMAIN}"
else
    target_url="https://console.${AMAZON_DOMAIN}/${destination}/home?region=${region}"
fi

: "${AWS_ACCESS_KEY_ID:?must be set}"
: "${AWS_SECRET_ACCESS_KEY:?must be set}"
: "${AWS_SESSION_TOKEN:?must be set (federation requires temporary credentials)}"

# Step 1: exchange the temporary credentials for a sign-in token.
session_json=$(jq -n -c \
    --arg id "$AWS_ACCESS_KEY_ID" \
    --arg key "$AWS_SECRET_ACCESS_KEY" \
    --arg token "$AWS_SESSION_TOKEN" \
    '{sessionId: $id, sessionKey: $key, sessionToken: $token}')

signin_token=$(curl -sf -G "https://signin.${AMAZON_DOMAIN}/federation" \
    --data-urlencode "Action=getSigninToken" \
    --data-urlencode "Session=${session_json}" \
    | jq -r '.SigninToken')

if [[ -z "$signin_token" || "$signin_token" == "null" ]]; then
    echo "Failed to obtain a sign-in token" >&2
    exit 1
fi

# Step 2: build the login URL with the sign-in token (constructed locally,
# no request — visiting it is what logs the browser in).
final_url="https://signin.${AMAZON_DOMAIN}/federation"
final_url+="?Action=login"
final_url+="&Issuer="
final_url+="&Destination=$(urlencode "$target_url")"
final_url+="&SigninToken=$(urlencode "$signin_token")"

open "$final_url"
