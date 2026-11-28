#!/usr/bin/env bash
# Bootstrap step 1: register the resource providers and create the resource
# group that holds everything else.
#
# Run once in Azure Cloud Shell (Bash), signed in as the subscription's owner.
# Running it again changes nothing: each part checks before it creates.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$HERE/common.sh"

use_subscription

for namespace in "${PROVIDERS[@]}"; do
  state="$(az provider show --namespace "$namespace" --query registrationState --output tsv)"
  if [[ "$state" == "Registered" ]]; then
    say "provider $namespace: already registered"
  else
    az provider register --namespace "$namespace" --wait --output none
    say "provider $namespace: registered"
  fi
done

if [[ "$(az group exists --name "$RESOURCE_GROUP")" == "true" ]]; then
  say "resource group $RESOURCE_GROUP: exists, left as it is"
else
  az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
  say "resource group $RESOURCE_GROUP: created in $LOCATION"
fi
