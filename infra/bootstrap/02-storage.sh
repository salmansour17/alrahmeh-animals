#!/usr/bin/env bash
# Bootstrap step 2: the storage account that serves the website and holds
# Terraform's state.
#
# - The account: StorageV2, locally redundant, HTTPS only, TLS 1.2, and no
#   anonymous access to blob containers (the static website is served
#   separately from $web and is not affected).
# - The static website, with index.html as the 404 page too, so a deep link
#   such as /animals/3 loads the React app, which then shows the right page.
# - A private `tfstate` container, where `terraform init` in cd.yml keeps the
#   state file (backend "azurerm" in infra/main.tf).
#
# Run after 01. Running it again changes nothing.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$HERE/common.sh"

use_subscription

if exists az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP"; then
  say "storage account $STORAGE_ACCOUNT: exists, left as it is"
else
  az storage account create --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" --kind StorageV2 --sku Standard_LRS \
    --min-tls-version TLS1_2 --https-only true --allow-blob-public-access false \
    --output none
  say "storage account $STORAGE_ACCOUNT: created"
fi

# Setting the same values twice is harmless, so this runs every time.
az storage blob service-properties update --account-name "$STORAGE_ACCOUNT" --auth-mode key \
  --static-website --index-document index.html --404-document index.html --output none
say "static website: on, index.html for both the index and 404 pages"

if [[ "$(az storage container exists --account-name "$STORAGE_ACCOUNT" --auth-mode key \
  --name "$TFSTATE_CONTAINER" --query exists --output tsv)" == "true" ]]; then
  say "container $TFSTATE_CONTAINER: exists, left as it is"
else
  az storage container create --account-name "$STORAGE_ACCOUNT" --auth-mode key \
    --name "$TFSTATE_CONTAINER" --public-access off --output none
  say "container $TFSTATE_CONTAINER: created (private)"
fi

say "website address: $(az storage account show --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" --query primaryEndpoints.web --output tsv)"
