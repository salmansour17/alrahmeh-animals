# Tests for terraform.rego:  conftest verify --policy policy/terraform
# Each test feeds one hand-made resource, shaped like Conftest's parse of our
# .tf files, and checks which rules fire.
package main

files(kind, block) := [
	{"path": "infra/x.tf", "contents": {"resource": {kind: {"r": [block]}}}},
	{"path": "infra/apps.tf", "contents": {"resource": {"azurerm_container_app": {"good": [good_app]}}}},
]

good_container := {
	"env": [{"name": "DATABASE_URL", "secret_name": "database-url"}],
	"startup_probe": [{"path": "/health"}],
	"readiness_probe": [{"path": "/health"}],
}

app(min, max, insecure, container) := {
	"name": "app",
	"ingress": [{"allow_insecure_connections": insecure}],
	"template": [{"min_replicas": min, "max_replicas": max, "container": [container]}],
}

good_app := app(0, 1, false, good_container)

test_no_container_app_is_denied if {
	deny["no azurerm_container_app found: run with --parser hcl2 --combine on infra/*.tf"] with input as [{"path": "infra/x.tf", "contents": {}}]
}

test_good_container_app_passes if {
	count(deny) == 0 with input as files("azurerm_container_app", good_app)
}

test_min_replicas_above_zero_is_denied if {
	deny["container app app: min_replicas must be 0, so an idle app costs nothing"] with input as files("azurerm_container_app", app(1, 1, false, good_container))
}

test_max_replicas_above_one_is_denied if {
	deny["container app app: max_replicas must be 1, so migrations never run twice at once"] with input as files("azurerm_container_app", app(0, 3, false, good_container))
}

test_insecure_ingress_is_denied if {
	deny["container app app: allow_insecure_connections must be set to false (HTTPS only)"] with input as files("azurerm_container_app", app(0, 1, true, good_container))
}

test_unset_insecure_flag_is_denied if {
	no_flag := json.patch(good_app, [{"op": "replace", "path": "/ingress/0", "value": {}}])
	deny["container app app: allow_insecure_connections must be set to false (HTTPS only)"] with input as files("azurerm_container_app", no_flag)
}

test_missing_probe_is_denied if {
	no_ready := object.remove(good_container, ["readiness_probe"])
	deny["container app app: needs a readiness_probe on /health"] with input as files("azurerm_container_app", app(0, 1, false, no_ready))
}

test_probe_on_another_path_is_denied if {
	elsewhere := object.union(good_container, {"startup_probe": [{"path": "/"}]})
	deny["container app app: needs a startup_probe on /health"] with input as files("azurerm_container_app", app(0, 1, false, elsewhere))
}

test_plain_secret_env_is_denied if {
	plain := object.union(good_container, {"env": [{"name": "DATABASE_URL", "value": "mssql://..."}]})
	deny["container app app: DATABASE_URL must use secret_name, not a plain value"] with input as files("azurerm_container_app", app(0, 1, false, plain))
}

test_plain_non_secret_env_passes if {
	plain := object.union(good_container, {"env": [{"name": "CORS_ORIGINS", "value": "https://x"}]})
	count(deny) == 0 with input as files("azurerm_container_app", app(0, 1, false, plain))
}

test_sql_server_without_tls_12_is_denied if {
	deny[`SQL server sql: minimum_tls_version must be "1.2"`] with input as files("azurerm_mssql_server", {"name": "sql", "minimum_tls_version": "1.0"})
	count(deny) == 0 with input as files("azurerm_mssql_server", {"name": "sql", "minimum_tls_version": "1.2"})
}

test_azure_services_firewall_rule_passes if {
	rule := {"name": "azure", "start_ip_address": "0.0.0.0", "end_ip_address": "0.0.0.0"}
	count(deny) == 0 with input as files("azurerm_mssql_firewall_rule", rule)
}

test_open_firewall_rule_is_denied if {
	rule := {"name": "everyone", "start_ip_address": "0.0.0.0", "end_ip_address": "255.255.255.255"}
	deny["SQL firewall rule everyone opens 0.0.0.0-255.255.255.255; only 0.0.0.0-0.0.0.0 (Azure services) is allowed"] with input as files("azurerm_mssql_firewall_rule", rule)
}
