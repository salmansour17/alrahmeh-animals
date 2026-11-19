# The three services, each a Container App on the Consumption plan in one
# environment. Each scales to zero when idle and to at most one replica, so a
# quiet site costs nothing and migrations, which run at start-up, never run in
# two replicas at once (ADR-8).

resource "azurerm_container_app_environment" "main" {
  name                = "${var.prefix}-env"
  resource_group_name = data.azurerm_resource_group.main.name
  location            = var.location
  # No Log Analytics workspace: that is a separate resource billed per GB.
  # Without one, the containers' stdout (one line per request) is still
  # streamed: az containerapp logs show --name <app> --follow.
}

locals {
  # What differs between the three apps. Everything else is shared below.
  services = {
    animals = {
      env = {
        SAMPLE_ANIMALS = "1"
      }
      secrets = {}
    }
    donations = {
      env = {
        # The animals service's public HTTPS address. A Container App's address
        # is its name followed by the environment's domain, so it is known
        # before the app exists and needs no reference to it.
        ANIMALS_URL       = "https://${var.prefix}-animals.${azurerm_container_app_environment.main.default_domain}"
        ANIMALS_TIMEOUT_S = "2"
        # Stripe sends donors back to the website after paying.
        PUBLIC_BASE_URL = local.website_origin
      }
      # Card donations only when both Stripe values are set; with either empty
      # the service keeps them switched off (503) and everything else works.
      secrets = var.stripe_secret_key != "" && var.stripe_webhook_secret != "" ? {
        STRIPE_SECRET_KEY     = { name = "stripe-secret-key", value = var.stripe_secret_key }
        STRIPE_WEBHOOK_SECRET = { name = "stripe-webhook-secret", value = var.stripe_webhook_secret }
      } : {}
    }
    enquiries = {
      env     = {}
      secrets = {}
    }
  }
}

resource "azurerm_container_app" "service" {
  for_each = local.services

  name                         = "${var.prefix}-${each.key}"
  resource_group_name          = data.azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  # One revision at a time: a deploy replaces the running version.
  revision_mode = "Single"

  # Secrets are stored by Container Apps, encrypted, and reach the container as
  # environment variables through secret_name below. They never appear as
  # plain values in the app's configuration.
  secret {
    name  = "database-url"
    value = local.database_urls[each.key]
  }
  secret {
    name  = "admin-password"
    value = var.admin_password
  }
  dynamic "secret" {
    for_each = each.value.secrets
    content {
      name  = secret.value.name
      value = secret.value.value
    }
  }

  ingress {
    # Public HTTPS, because the browser calls every service directly.
    external_enabled           = true
    target_port                = 8000
    transport                  = "auto"
    allow_insecure_connections = false

    # Required by the provider even in Single mode: all traffic goes to the
    # newest revision.
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    # Scale to zero when idle, never above one replica.
    min_replicas = 0
    max_replicas = 1

    # The load-based scaling rule, stated explicitly: add a replica when one
    # handles more than 10 requests at once. With max_replicas = 1 it can only
    # wake the app from zero; it is the setting to raise at higher traffic.
    http_scale_rule {
      name                = "http-requests"
      concurrent_requests = "10"
    }

    container {
      name   = each.key
      image  = "${var.registry}/alrahmeh-${each.key}:${var.image_tags[each.key]}"
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }
      env {
        name        = "ADMIN_PASSWORD"
        secret_name = "admin-password"
      }
      # The website's origin is the only one allowed to call from a browser.
      env {
        name  = "CORS_ORIGINS"
        value = local.website_origin
      }
      dynamic "env" {
        for_each = each.value.env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = each.value.secrets
        content {
          name        = env.key
          secret_name = env.value.name
        }
      }

      # Start-up runs the migrations and may wait up to a minute for a paused
      # database to resume, so the app gets up to 5 minutes (30 checks, 10 s
      # apart) to answer /health with 200 before it counts as failed to start.
      startup_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/health"
        interval_seconds        = 10
        timeout                 = 8
        failure_count_threshold = 30
      }

      # Traffic only reaches a replica whose /health says it can use its
      # database. There is deliberately no liveness probe on /health: a
      # database pausing is not a reason to restart the container, and a
      # restart would not bring the database back sooner.
      readiness_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/health"
        interval_seconds        = 10
        timeout                 = 8
        failure_count_threshold = 3
      }
    }
  }
}
