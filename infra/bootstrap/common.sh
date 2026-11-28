#!/usr/bin/env bash
# Shared settings for the bootstrap scripts (01 to 05), which source this file.
# It runs nothing on its own.
#
# One source of truth for every name: the values below are the ones deployed
# (system.yaml), and each can be overridden from the environment to bootstrap
# another copy, e.g. PREFIX=jdoe-ieu2025 ./01-providers-and-group.sh.
# Nothing here is a secret.

# These are read by the scripts that source this file, which shellcheck cannot
# see when it checks this file on its own.
# shellcheck disable=SC2034

SUBSCRIPTION="${SUBSCRIPTION:-Azure for Students}"
PREFIX="${PREFIX:-snsour-ieu2024}"
LOCATION="${LOCATION:-germanywestcentral}"      # Container Apps, resource group, storage
SQL_LOCATION="${SQL_LOCATION:-spaincentral}"    # the SQL server (ADR-8)
REPO="${REPO:-salmansour17/alrahmeh-animals}"   # owner/name on GitHub

# Derived the same way as in infra/main.tf and infra/container_apps.tf.
RESOURCE_GROUP="rg-${PREFIX}"
STORAGE_ACCOUNT="${PREFIX//-/}ui"               # letters and digits only
IDENTITY="${PREFIX}-github"
TFSTATE_CONTAINER="tfstate"                     # backend "azurerm" in infra/main.tf

# What Terraform and the pipeline use. Terraform registers none of them
# (resource_provider_registrations = "none"): that needs rights over the whole
# subscription, and the pipeline's identity has Contributor on one group only.
PROVIDERS=(
  Microsoft.App
  Microsoft.OperationalInsights
  Microsoft.Sql
  Microsoft.Storage
  Microsoft.ManagedIdentity
)

# The GitHub Actions OIDC trust, as azure/login in cd.yml asks for it.
OIDC_ISSUER="https://token.actions.githubusercontent.com"
OIDC_AUDIENCE="api://AzureADTokenExchange"
OIDC_BRANCH="refs/heads/main"

say() { printf '%s\n' "$*"; }

# True when an `az ... show` command finds the thing. Its error text is
# dropped on purpose: "not found" is the expected answer on a first run, and a
# real failure (signed out, wrong subscription) still shows when the create
# command that follows fails loudly.
exists() { "$@" --output none 2>/dev/null; }

use_subscription() {
  az account set --subscription "$SUBSCRIPTION"
  say "Subscription: $(az account show --query name --output tsv)"
}
