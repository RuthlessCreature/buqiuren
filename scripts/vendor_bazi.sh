#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/china-testing/bazi.git"
COMMIT="33b18354d5407727640e545c3aaec0efb4bf5282"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

printf 'Fetching china-testing/bazi @ %s\n' "$COMMIT"
git -C "$TMP" init -q
git -C "$TMP" remote add origin "$REPO"
git -C "$TMP" fetch -q --depth 1 origin "$COMMIT"
git -C "$TMP" checkout -q FETCH_HEAD

rm -rf "$ROOT/vendor_bazi"
mkdir -p "$ROOT/vendor_bazi"
find "$TMP" -maxdepth 1 -type f -name '*.py' -exec cp '{}' "$ROOT/vendor_bazi/" ';'
printf '%s\n' "$COMMIT" > "$ROOT/vendor_bazi/UPSTREAM_COMMIT"

cat > "$ROOT/vendor_bazi/README.vendor.txt" <<EOF
This directory is generated at build time from china-testing/bazi.
Upstream: $REPO
Commit:   $COMMIT
Do not hand-edit generated files.
EOF

printf 'Vendored root Python sources into %s/vendor_bazi\n' "$ROOT"
