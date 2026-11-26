#!/usr/bin/env bash
# Prints each service's start-up log into the deploy's own log, so the lines
# the migration runner writes ("Applied migration 003_ledger_reversals.sql to
# ...") stay in the Actions log for good. There is no Log Analytics workspace
# (a billed resource), so Azure keeps a container's console output only while
# that container runs; once the app scales to zero, the lines are gone.
#
#   show-startup-logs.sh <terraform outputs.json>
#
# Reads PREFIX and RESOURCE_GROUP from the environment. Signed in to Azure
# already (azure/login, earlier in the job).
#
# This step reports; it never decides. It exits 0 whatever happens, on
# purpose and explicitly below, so empty logs cannot fail a good deploy, and
# it runs after a failed step too (cd.yml: if: always()) without hiding that
# failure: the job keeps the failed step's status. A missing migration line
# is a visible ::warning::, not an error.
set -u

outputs=${1:?usage: $0 <terraform outputs.json>}
: "${PREFIX:?PREFIX is not set}" "${RESOURCE_GROUP:?RESOURCE_GROUP is not set}"

# az may need its containerapp extension; install it without asking.
export AZURE_EXTENSION_USE_DYNAMIC_INSTALL=yes_without_prompt

# Wake an app that has scaled to zero, so it has a running container whose
# log can be read: up to about three minutes, as a paused database can take
# a minute to resume before the app answers.
wake() {
  local url=$1
  for _ in $(seq 1 18); do
    if curl --silent --fail --max-time 10 --output /dev/null "$url"; then
      return 0
    fi
    sleep 10
  done
  return 1
}

for service in animals donations enquiries; do
  app="$PREFIX-$service"
  echo "::group::$service: start-up log ($app)"
  if [ -f "$outputs" ]; then
    url=$(jq -r ".service_urls.value.$service // empty" "$outputs")/health
    wake "$url" || echo "::warning::$service did not answer $url; its log may be empty"
  else
    echo "No Terraform outputs (an earlier step failed before apply); reading the log without waking the app"
  fi

  # --type console: the container's own stdout and stderr, which works
  # without Log Analytics. --tail: the start-up lines come first after a new
  # revision starts, before the access log grows.
  if log=$(az containerapp logs show --name "$app" --resource-group "$RESOURCE_GROUP" \
      --type console --tail 300 --format text 2>&1); then
    printf '%s\n' "$log"
  else
    echo "::warning::could not read the log of $app: $log"
    log=""
  fi
  echo "::endgroup::"

  # Outside the group, so the line is visible without expanding anything.
  if migrations=$(printf '%s\n' "$log" | grep -E "Applied migration|is up to date \("); then
    printf '%s migrations:\n%s\n' "$service" "$migrations"
  else
    echo "::warning::no migration line found in the $service log (the container may have started before the log window)"
  fi
done
exit 0
