# Tests for dockerfile.rego:  conftest verify --policy policy/dockerfile
# Each test builds a tiny parsed Dockerfile and checks which rules fire.
package main

from(image) := {"Cmd": "from", "Value": [image]}

user(name) := {"Cmd": "user", "Value": [name]}

pinned := "python:3.13.18-slim-bookworm@sha256:f0fa218d5b06f9b9235024fa061cde2cb141f726de52134471053d2d9b5324a3"

test_pinned_image_and_non_root_user_pass if {
	count(deny) == 0 with input as [from(pinned), user("app")]
}

test_missing_user_is_denied if {
	deny["no USER instruction: the container would run as root"] with input as [from(pinned)]
}

test_root_user_is_denied if {
	deny[`the last USER is "root", which is root`] with input as [from(pinned), user("root")]
}

test_numeric_root_with_group_is_denied if {
	deny[`the last USER is "0:0", which is root`] with input as [from(pinned), user("0:0")]
}

test_only_the_last_user_counts if {
	# Switching to root at the end undoes an earlier non-root USER.
	deny[`the last USER is "root", which is root`] with input as [from(pinned), user("app"), user("root")]
	count(deny) == 0 with input as [from(pinned), user("root"), user("app")]
}

test_input_without_from_is_denied if {
	deny["no FROM instruction found: is this a Dockerfile, parsed as one?"] with input as [user("app")]
}

test_untagged_image_is_denied if {
	deny["FROM python has no tag, which means `latest`"] with input as [from("python"), user("app")]
}

test_latest_tag_is_denied if {
	deny["FROM python:latest uses `latest`, which changes without notice"] with input as [from("python:latest"), user("app")]
}

test_tag_without_digest_is_denied if {
	deny["FROM python:3.13-slim has no @sha256 digest; a tag can be re-pushed, a digest cannot"] with input as [from("python:3.13-slim"), user("app")]
}

test_registry_port_is_not_a_tag if {
	deny["FROM localhost:5000/python has no tag, which means `latest`"] with input as [from("localhost:5000/python"), user("app")]
}

test_reference_to_an_earlier_stage_needs_no_tag if {
	stages := [
		{"Cmd": "from", "Value": [pinned, "AS", "build"]},
		{"Cmd": "from", "Value": ["build"]},
		user("app"),
	]
	count(deny) == 0 with input as stages
}
