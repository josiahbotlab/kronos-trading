#!/usr/bin/env bash
# check_baseline.sh — integrity check for the canonical v3 baseline.
# Prints the baseline sha256, verifies the referenced pool exists, and exits
# non-zero with a loud message if the pool is missing.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASELINE="$DIR/baseline_800_v4.json"

if [ ! -f "$BASELINE" ]; then
  echo "FATAL: baseline file missing: $BASELINE" >&2
  exit 2
fi
echo "baseline     : $BASELINE"
echo "baseline sha256: $(sha256sum "$BASELINE" | cut -d' ' -f1)"

POOL="$(python3 -c "import json;print(json.load(open('$BASELINE'))['fleet_trades_source'])")"
echo "pool path    : $POOL"

if [ ! -f "$POOL" ]; then
  echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
  echo "FATAL: canonical fleet pool is MISSING: $POOL" >&2
  echo "The baseline cannot be reproduced. Run rebuild_baseline.sh." >&2
  echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" >&2
  exit 1
fi
echo "pool sha256  : $(sha256sum "$POOL" | cut -d' ' -f1)"
echo "pool trades  : $(python3 -c "import json;d=json.load(open('$POOL'));print(sum(len(v) for v in d.values()))")"
echo "canonical    : $(python3 -c "import json;print(json.load(open('$BASELINE'))['canonical'])")"
echo "OK: baseline present, pool present."
exit 0
