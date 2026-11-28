#!/usr/bin/env bash
# Bootstrap step 5: read-only access for the two professors.
#
# Reader on the resource group: they can see every resource of this project,
# its settings and its logs, and can change nothing. The resource group is the
# narrowest scope that still shows all of it; nothing else in the subscription
# is visible to them.
#
# Their addresses are never written into the repository. Supply them when
# running it:
#
#   PROFESSOR_EMAIL_1=... PROFESSOR_EMAIL_2=... ./05-professor-reader.sh
#
# Each address must already be a user (or invited guest) in this Azure
# directory; if Azure says the user does not exist, invite them first in the
# portal (Microsoft Entra ID > Users > Invite external user).
# Run after 01. Running it again changes nothing.
set -euo pipefail
: "${PROFESSOR_EMAIL_1:?set PROFESSOR_EMAIL_1 to the address of the first professor}"
: "${PROFESSOR_EMAIL_2:?set PROFESSOR_EMAIL_2 to the address of the second professor}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$HERE/common.sh"

use_subscription
group_id="$(az group show --name "$RESOURCE_GROUP" --query id --output tsv)"

for who in "$PROFESSOR_EMAIL_1" "$PROFESSOR_EMAIL_2"; do
  if [[ "$(az role assignment list --assignee "$who" --role Reader --scope "$group_id" \
    --query "length(@)" --output tsv)" != "0" ]]; then
    say "Reader for $who: already assigned"
  else
    az role assignment create --assignee "$who" --role Reader --scope "$group_id" --output none
    say "Reader for $who: assigned on $RESOURCE_GROUP"
  fi
done
