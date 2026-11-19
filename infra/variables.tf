# Everything that differs between deployments is a variable. The pipeline
# passes them as TF_VAR_* environment variables (cd.yml); none has a value in
# the repository except harmless defaults.

variable "prefix" {
  description = "IE username with dots replaced by hyphens; every resource name starts with it."
  type        = string
}

variable "location" {
  description = "Azure region for the Container Apps, one allowed by the Azure for Students policy."
  type        = string
}

variable "sql_location" {
  description = "Azure region for the SQL server. Can differ from location, because the free offer is not available everywhere."
  type        = string
}

variable "registry" {
  description = "Where the images are, e.g. ghcr.io/<owner>."
  type        = string
}

variable "image_tags" {
  description = "Image tag per service: the git commit the pipeline built."
  type = object({
    animals   = string
    donations = string
    enquiries = string
  })
}

variable "sql_admin_login" {
  description = "The SQL server's administrator login, used only for the one-time setup of each service's database user."
  type        = string
  default     = "sqladmin"
}

variable "sql_admin_password" {
  description = "Password of the SQL server's administrator login. GitHub secret SQL_ADMIN_PASSWORD."
  type        = string
  sensitive   = true
}

variable "db_passwords" {
  description = "Password of each service's own database user. GitHub secrets ANIMALS_DB_PASSWORD, DONATIONS_DB_PASSWORD, ENQUIRIES_DB_PASSWORD."
  type = object({
    animals   = string
    donations = string
    enquiries = string
  })
  sensitive = true
}

variable "admin_password" {
  description = "The staff portal password. GitHub secret ADMIN_PASSWORD."
  type        = string
  sensitive   = true
}

variable "stripe_secret_key" {
  description = "Stripe test-mode secret key. Empty leaves card donations switched off."
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_webhook_secret" {
  description = "Stripe webhook signing secret. Empty leaves card donations switched off."
  type        = string
  sensitive   = true
  default     = ""
}
