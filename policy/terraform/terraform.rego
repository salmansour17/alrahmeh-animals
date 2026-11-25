# Rules the Azure Terraform must follow. Checked by Conftest in security.yml:
#   conftest test --parser hcl2 --combine --policy policy/terraform infra/*.tf
#
# --combine hands every .tf file to these rules at once, as a list of
# {"path": "infra/x.tf", "contents": <the file parsed into JSON>}, so a rule
# can look at resources wherever they are declared.
package main

resources(kind) := [block |
	some file in input
	some blocks in file.contents.resource[kind]
	some block in blocks
]

container_apps := resources("azurerm_container_app")

# A guard: if no container app is found, the input is not shaped as these
# rules expect (run without --combine, another parser), and every rule below
# would pass without looking at anything. Fail loudly instead.
deny contains msg if {
	count(container_apps) == 0
	msg := "no azurerm_container_app found: run with --parser hcl2 --combine on infra/*.tf"
}

# --- Scaling: scale to zero, never above one replica (ADR-8) --------------

deny contains msg if {
	some app in container_apps
	some template in app.template
	object.get(template, "min_replicas", null) != 0
	msg := sprintf("container app %s: min_replicas must be 0, so an idle app costs nothing", [app.name])
}

deny contains msg if {
	some app in container_apps
	some template in app.template
	object.get(template, "max_replicas", null) != 1
	msg := sprintf("container app %s: max_replicas must be 1, so migrations never run twice at once", [app.name])
}

# --- Ingress: HTTPS only ----------------------------------------------------

deny contains msg if {
	some app in container_apps
	some ingress in app.ingress
	object.get(ingress, "allow_insecure_connections", null) != false
	msg := sprintf("container app %s: allow_insecure_connections must be set to false (HTTPS only)", [app.name])
}

# --- Health: startup and readiness probes on /health ----------------------

deny contains msg if {
	some app in container_apps
	some template in app.template
	some container in template.container
	some probe_kind in ["startup_probe", "readiness_probe"]
	not probe_on_health(container, probe_kind)
	msg := sprintf("container app %s: needs a %s on /health", [app.name, probe_kind])
}

probe_on_health(container, kind) if {
	some probe in container[kind]
	probe.path == "/health"
}

# --- Secrets never as plain environment values ----------------------------

# Variables that always hold a secret. They must come from a Container Apps
# secret (secret_name), never be written into the app's configuration.
secret_env_names := {
	"DATABASE_URL",
	"ADMIN_PASSWORD",
	"TOKEN_SIGNING_KEY",
	"STAFF_BOOTSTRAP_PASSWORD",
	"STRIPE_SECRET_KEY",
	"STRIPE_WEBHOOK_SECRET",
}

deny contains msg if {
	some app in container_apps
	some template in app.template
	some container in template.container
	some env in object.get(container, "env", [])
	env.name in secret_env_names
	not env.secret_name
	msg := sprintf("container app %s: %s must use secret_name, not a plain value", [app.name, env.name])
}

# --- SQL server: TLS 1.2 and no firewall opening beyond Azure services -----

deny contains msg if {
	some server in resources("azurerm_mssql_server")
	object.get(server, "minimum_tls_version", null) != "1.2"
	msg := sprintf("SQL server %s: minimum_tls_version must be \"1.2\"", [server.name])
}

# The only firewall rule Terraform may create is 0.0.0.0-0.0.0.0, Azure's
# special "Azure services" rule. My own IP is added by hand during the
# bootstrap and removed straight after; it never belongs in code.
deny contains msg if {
	some rule in resources("azurerm_mssql_firewall_rule")
	not azure_services_only(rule)
	msg := sprintf("SQL firewall rule %s opens %s-%s; only 0.0.0.0-0.0.0.0 (Azure services) is allowed", [rule.name, rule.start_ip_address, rule.end_ip_address])
}

azure_services_only(rule) if {
	rule.start_ip_address == "0.0.0.0"
	rule.end_ip_address == "0.0.0.0"
}
