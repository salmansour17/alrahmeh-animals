# One logical SQL server holding one database per service.
#
# The three databases themselves are created by the pipeline, not here (cd.yml,
# step "Create the databases if missing"), with the Azure CLI. That was chosen
# for Azure SQL's free offer, which this provider cannot set; Azure then
# refused the free offer for this subscription, so they are ordinary
# serverless databases, and they stay with the CLI because they already exist
# (ADR-8). Each service reaches only its own database, through a user created
# inside that database during the bootstrap.

resource "azurerm_mssql_server" "main" {
  name                = "${var.prefix}-sql"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = var.sql_location
  version             = "12.0"

  administrator_login          = var.sql_admin_login
  administrator_login_password = var.sql_admin_password

  # Clients must use TLS 1.2 or newer. Every connection from the services is
  # encrypted (?encrypt=true in DATABASE_URL).
  minimum_tls_version = "1.2"

  # The Container Apps reach the server over the internet, not a private
  # network, so public access stays on; the firewall rule below decides who
  # may connect.
  public_network_access_enabled = true
}

# The firewall: allow connections from Azure services only. 0.0.0.0 to 0.0.0.0
# is Azure's special rule for "any Azure service", which is how the Container
# Apps get in. Nothing else may connect. During the bootstrap, my own IP is
# added for a few minutes by hand and removed again (docs/deployment.md).
resource "azurerm_mssql_firewall_rule" "azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_mssql_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

locals {
  # Database name per service, as the brief's naming rule sets them.
  databases = {
    animals   = "${var.prefix}-animals-db"
    donations = "${var.prefix}-donations-db"
    enquiries = "${var.prefix}-enquiries-db"
  }

  # Each service's connection string, with its own user and password. Passed
  # to its Container App as a secret, never as a plain environment variable.
  # Usernames are the service name plus _app, matching the bootstrap's
  # CREATE USER statements. The passwords use letters and digits only, so they
  # need no escaping inside the URL.
  database_urls = {
    for service, database in local.databases :
    service => "mssql://${service}_app:${var.db_passwords[service]}@${azurerm_mssql_server.main.fully_qualified_domain_name}:1433/${database}?encrypt=true"
  }
}
