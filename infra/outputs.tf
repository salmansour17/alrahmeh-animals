# What the pipeline reads after `terraform apply`: where each service answers,
# for the website's config.js and the health checks, and the names it needs to
# create the databases and upload the website.

output "service_urls" {
  description = "Public HTTPS address of each service."
  value = {
    for service, app in azurerm_container_app.service :
    service => "https://${app.ingress[0].fqdn}"
  }
}

output "website_url" {
  description = "The system's public address: the storage account's static website."
  value       = local.website_origin
}

output "storage_account" {
  description = "Storage account holding the website ($web) and this state file (tfstate)."
  value       = local.storage_account
}

output "sql_server" {
  description = "Name of the SQL server the pipeline creates the databases on."
  value       = azurerm_mssql_server.main.name
}

output "databases" {
  description = "Database name per service."
  value       = local.databases
}
