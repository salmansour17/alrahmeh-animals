#!/usr/bin/env bash
# Bootstrap step 4: the GitHub secrets and variables cd.yml expects (its
# header lists them all).
#
# - Variables (not secret): written every time, which is harmless.
# - The three Azure IDs: read from Azure and stored as secrets. They are not
#   passwords, but they are kept out of logs all the same.
# - The passwords: never in this file. For each one not set yet, gh asks for
#   it at a hidden prompt; one already set is left alone.
# - Stripe's two keys are optional and are not asked for here; without them
#   card donations stay off (see "Card donations" in the README).
#
# The three database passwords go inside a connection string, so use letters
# and digits only (8 or more, with upper case, lower case and a digit).
#
# Needs `gh auth login` as someone who can change the repository's settings.
# Run after 03. Running it again asks only for what is missing.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$HERE/common.sh"

PASSWORD_SECRETS=(
  SQL_ADMIN_PASSWORD
  ANIMALS_DB_PASSWORD
  DONATIONS_DB_PASSWORD
  ENQUIRIES_DB_PASSWORD
  ADMIN_PASSWORD
)

use_subscription

set_variable() {
  gh variable set "$1" --repo "$REPO" --body "$2"
  say "variable $1 = $2"
}

set_variable PREFIX "$PREFIX"
set_variable LOCATION "$LOCATION"
set_variable SQL_LOCATION "$SQL_LOCATION"
set_variable RESOURCE_GROUP "$RESOURCE_GROUP"
set_variable UI_STORAGE "$STORAGE_ACCOUNT"

# Piped in, so no ID appears on the command line or in the shell's history.
set_id_secret() {
  local name="$1" value="$2"
  if [[ -z "$value" ]]; then
    say "could not read $name from Azure" >&2
    exit 1
  fi
  printf '%s' "$value" | gh secret set "$name" --repo "$REPO"
  say "secret $name: set"
}

set_id_secret AZURE_CLIENT_ID "$(az identity show --name "$IDENTITY" --resource-group "$RESOURCE_GROUP" --query clientId --output tsv)"
set_id_secret AZURE_TENANT_ID "$(az account show --query tenantId --output tsv)"
set_id_secret AZURE_SUBSCRIPTION_ID "$(az account show --query id --output tsv)"

existing="$(gh secret list --repo "$REPO" --json name --jq '.[].name')"
for name in "${PASSWORD_SECRETS[@]}"; do
  if grep --quiet --line-regexp --fixed-strings "$name" <<<"$existing"; then
    say "secret $name: already set, left as it is"
  else
    say "secret $name: type it at the hidden prompt"
    gh secret set "$name" --repo "$REPO"
  fi
done
