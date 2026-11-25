# Rules every service Dockerfile must follow. Checked by Conftest in
# security.yml:  conftest test --policy policy/dockerfile services/*/Dockerfile
#
# Conftest hands each Dockerfile to these rules as a flat list of its
# instructions in file order, for example
# {"Cmd": "from", "Value": ["python:3.13@sha256:...", "AS", "build"]}.
# Every `deny` message is one reason the build fails.
package main

# --- The container must not run as root ---------------------------------

# The USER instructions in file order. Only the last one decides who the
# container runs as, because each USER replaces the one before it.
users := [instr.Value[0] | some instr in input; instr.Cmd == "user"]

deny contains msg if {
	count(users) == 0
	msg := "no USER instruction: the container would run as root"
}

deny contains msg if {
	count(users) > 0
	last := users[count(users) - 1]
	is_root(last)
	msg := sprintf("the last USER is %q, which is root", [last])
}

# "root", "0", "root:root", "0:0", "root:app" all mean the root user.
is_root(user) if {
	name := split(user, ":")[0]
	name in {"root", "0"}
}

# --- Base images are pinned -----------------------------------------------

# Names given to earlier build stages (FROM ... AS build). A later
# `FROM build` refers to that stage, not to an image, so it needs no tag.
stage_names := {lower(instr.Value[2]) |
	some instr in input
	instr.Cmd == "from"
	count(instr.Value) >= 3
	lower(instr.Value[1]) == "as"
}

# A guard: if no FROM is found, the input is not what these rules expect
# (another parser, a changed format), and every rule below would pass
# without looking at anything. Fail loudly instead.
deny contains msg if {
	count([instr | some instr in input; instr.Cmd == "from"]) == 0
	msg := "no FROM instruction found: is this a Dockerfile, parsed as one?"
}

# Every image a FROM pulls from a registry.
base_images contains image if {
	some instr in input
	instr.Cmd == "from"
	image := instr.Value[0]
	not lower(image) in stage_names
	image != "scratch"
}

deny contains msg if {
	some image in base_images
	tag(image) == ""
	msg := sprintf("FROM %s has no tag, which means `latest`", [image])
}

deny contains msg if {
	some image in base_images
	tag(image) == "latest"
	msg := sprintf("FROM %s uses `latest`, which changes without notice", [image])
}

deny contains msg if {
	some image in base_images
	not contains(image, "@sha256:")
	msg := sprintf("FROM %s has no @sha256 digest; a tag can be re-pushed, a digest cannot", [image])
}

# The tag of an image reference, or "" if it has none.
#   python:3.13@sha256:ab..  -> "3.13"
#   localhost:5000/python    -> ""   (that colon belongs to the port)
tag(image) := t if {
	name := split(image, "@")[0]
	parts := split(name, ":")
	count(parts) > 1
	last := parts[count(parts) - 1]
	not contains(last, "/")
	t := last
} else := ""
