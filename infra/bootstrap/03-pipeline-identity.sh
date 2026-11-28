#!/usr/bin/env bash
# Bootstrap step 3: the identity GitHub Actions deploys as.
#
# - A user-assigned managed identity, <prefix>-github.
# - Contributor on the resource group only: it can create and change what is
#   inside the group, and nothing outside it. It cannot assign roles, which is
#   why this script (run by the subscription's owner) has to do it.
# - Two OIDC trust entries (federated credentials): Azure accepts a token
#   from GitHub as this identity only when the token says it comes from a
#   workflow on the main branch of this repository. No password exists
#   anywhere. GitHub can name the repository either by name or by numeric IDs
#   in that token (the IDs survive a rename); both forms are trusted, and both
#   only for main.
#
# Needs `gh auth login` first (the numeric IDs come from the GitHub API).
# Run after 01. Running it again changes nothing.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$HERE/common.sh"

ROLE_RETRIES=6        # a new identity takes a little while to be visible
ROLE_RETRY_WAIT_S=10  # to role assignments

use_subscription

if exists az identity show --name "$IDENTITY" --resource-group "$RESOURCE_GROUP"; then
  say "identity $IDENTITY: exists, left as it is"
else
  az identity create --name "$IDENTITY" --resource-group "$RESOURCE_GROUP" --location "$LOCATION" --output none
  say "identity $IDENTITY: created"
fi

principal_id="$(az identity show --name "$IDENTITY" --resource-group "$RESOURCE_GROUP" --query principalId --output tsv)"
group_id="$(az group show --name "$RESOURCE_GROUP" --query id --output tsv)"

has_contributor() {
  [[ "$(az role assignment list --assignee "$principal_id" --role Contributor --scope "$group_id" \
    --query "length(@)" --output tsv)" != "0" ]]
}

if has_contributor; then
  say "Contributor on $RESOURCE_GROUP: already assigned"
else
  for ((try = 1; try <= ROLE_RETRIES; try++)); do
    if az role assignment create --assignee-object-id "$principal_id" --assignee-principal-type ServicePrincipal \
      --role Contributor --scope "$group_id" --output none; then
      break
    fi
    if ((try == ROLE_RETRIES)); then
      say "Could not assign Contributor after $ROLE_RETRIES tries" >&2
      exit 1
    fi
    say "identity not visible yet, trying again in ${ROLE_RETRY_WAIT_S}s ($try/$ROLE_RETRIES)"
    sleep "$ROLE_RETRY_WAIT_S"
  done
  say "Contributor on $RESOURCE_GROUP: assigned"
fi

trust() {
  local name="$1" subject="$2"
  if exists az identity federated-credential show --name "$name" --identity-name "$IDENTITY" \
    --resource-group "$RESOURCE_GROUP"; then
    say "trust $name: exists, left as it is"
  else
    az identity federated-credential create --name "$name" --identity-name "$IDENTITY" \
      --resource-group "$RESOURCE_GROUP" --issuer "$OIDC_ISSUER" --audiences "$OIDC_AUDIENCE" \
      --subject "$subject" --output none
    say "trust $name: created for $subject"
  fi
}

by_ids="$(gh api "repos/$REPO" --jq '"\(.owner.login)@\(.owner.id)/\(.name)@\(.id)"')"
trust github-main "repo:$REPO:ref:$OIDC_BRANCH"
trust github-main-ids "repo:$by_ids:ref:$OIDC_BRANCH"
