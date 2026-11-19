# The Azure side of the system, applied by the deploy pipeline (cd.yml) on every
# push to main. Run nothing here by hand: after the one-time bootstrap
# (docs/deployment.md), only the pipeline changes Azure.
#
# What this manages: the Container Apps environment and the three Container
# Apps (container_apps.tf), and the SQL server with its firewall rule
# (database.tf). What it does not: the resource group, the storage account that
# serves the website and holds this state file, and the pipeline's identity,
# which the bootstrap creates because the pipeline's identity cannot create
# them itself; and the three databases, which the pipeline creates with az
# because this provider cannot set Azure SQL's free offer (ADR-8).

terraform {
  required_version = ">= 1.13.0, < 2.0.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.50"
    }
  }

  # The state file lives in the `tfstate` container of the website's storage
  # account. The pipeline fills in the account and resource group at
  # `terraform init` time (-backend-config), so no name is hard-coded here.
  backend "azurerm" {
    container_name = "tfstate"
    key            = "alrahmeh.tfstate"
    use_oidc       = true
  }
}

# The provider needs this block even when empty (`features`). Two settings
# matter here:
provider "azurerm" {
  features {}

  # The pipeline signs in as a managed identity through OpenID Connect, with no
  # password anywhere (cd.yml, azure/login).
  use_oidc = true

  # Register nothing. That needs rights over the whole subscription, which the
  # pipeline's identity (Contributor on one resource group) does not have; the
  # bootstrap registers the few providers this uses, once.
  resource_provider_registrations = "none"
}

locals {
  resource_group = "rg-${var.prefix}"
  # Storage account names allow only lowercase letters and digits.
  storage_account = "${replace(var.prefix, "-", "")}ui"
}

# Created by the bootstrap; read here, never changed.
data "azurerm_resource_group" "main" {
  name = local.resource_group
}

data "azurerm_storage_account" "website" {
  name                = local.storage_account
  resource_group_name = data.azurerm_resource_group.main.name
}

locals {
  # The website's address without the trailing slash, e.g.
  # https://<prefix>ui.z6.web.core.windows.net. The only origin the services
  # accept from a browser (CORS_ORIGINS), and where Stripe sends donors back.
  website_origin = trimsuffix(data.azurerm_storage_account.website.primary_web_endpoint, "/")
}
