#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/china-testing/bazi.git"
COMMIT="33b18354d5407727640e545c3aaec0efb4bf5282"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
TARGET="$ROOT/python_modules/buqiuren_bazi"
trap 'rm -rf "$TMP"' EXIT

printf 'Fetching china-testing/bazi @ %s\n' "$COMMIT"
git -C "$TMP" init -q
git -C "$TMP" remote add origin "$REPO"
git -C "$TMP" fetch -q --depth 1 origin "$COMMIT"
git -C "$TMP" checkout -q FETCH_HEAD

# pywrangler owns python_modules and may rebuild it during `pywrangler sync`.
# This script therefore MUST run after sync. The .pth file adds the isolated
# upstream directory to sys.path without editing any upstream imports.
rm -rf "$TARGET"
mkdir -p "$TARGET"
find "$TMP" -maxdepth 1 -type f -name '*.py' -exec cp '{}' "$TARGET/" ';'
printf '%s\n' "$COMMIT" > "$TARGET/UPSTREAM_COMMIT"
printf '%s\n' 'buqiuren_bazi' > "$ROOT/python_modules/buqiuren_bazi.pth"

cat > "$TARGET/README.vendor.txt" <<EOF
This directory is generated at build time from china-testing/bazi.
Upstream: $REPO
Commit:   $COMMIT
Do not hand-edit generated files.
The parent buqiuren_bazi.pth exposes this directory to the Worker Python path.
EOF

printf 'Vendored root Python sources into %s\n' "$TARGET"
