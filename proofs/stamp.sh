#!/usr/bin/env bash
# Create an OpenTimestamps proof for the current git HEAD.
# Usage: bash proofs/stamp.sh [label]
# Example: bash proofs/stamp.sh v1.0
set -euo pipefail

OTS_BIN="${OTS_BIN:-/home/emin/.local/ots-venv/bin/ots}"
LABEL="${1:-$(date +%Y-%m-%d)}"
ROOT="$(git rev-parse --show-toplevel)"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD)"
OUT="$ROOT/proofs/snapshot-${LABEL}-${COMMIT}.tar.gz"

git -C "$ROOT" archive --format=tar.gz HEAD -o "$OUT"
"$OTS_BIN" stamp "$OUT"

echo
echo "Created: $OUT"
echo "Proof:   ${OUT}.ots"
echo "Commit:  $COMMIT"
echo
echo "Commit both files. After ~1-24 hours run:"
echo "  $OTS_BIN upgrade ${OUT}.ots"
echo "to attach the Bitcoin block confirmation."
