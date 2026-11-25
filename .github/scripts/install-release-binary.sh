#!/usr/bin/env bash
# Installs one binary from a release archive, but only if the archive's
# SHA-256 matches the one we pinned. Used by security.yml for gitleaks and
# conftest, so both are installed the same way.
#
#   install-release-binary.sh <archive URL> <expected sha256> <binary name>
#
# A changed or tampered archive fails the checksum and stops the job before
# anything from it runs.
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "usage: $0 <archive URL> <expected sha256> <binary name>" >&2
  exit 2
fi
url=$1
expected_sha256=$2
binary=$3

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

curl --fail --silent --show-error --location --output "$workdir/archive.tar.gz" "$url"
echo "${expected_sha256}  $workdir/archive.tar.gz" | sha256sum --check --strict
tar --extract --gzip --file "$workdir/archive.tar.gz" --directory "$workdir" "$binary"
sudo install "$workdir/$binary" /usr/local/bin/
"$binary" --version
