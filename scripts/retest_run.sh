#!/usr/bin/env bash
# Re-run difftests + metrics for an existing run directory without new agent A calls.
# Rebuilds the run's config first so original objects match. Usage: retest_run.sh <run_dir>
set -euo pipefail
cd "$(dirname "$0")/.."
RUN="$1"
export PILOT_CONFIG="$RUN/_meta/$(ls "$RUN/_meta" | grep '^pilot_.*\.json$')"
python3 scripts/build_pilot.py "$PILOT_CONFIG" >/dev/null
cmp -s build/eval/ground_truth.json "$RUN/_meta/ground_truth.json" || { echo "rebuild differs from run" >&2; exit 1; }
python3 - "$RUN" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, "src/evaluation")
import difftest
run = Path(sys.argv[1])
truth = json.loads((run / "_meta/ground_truth.json").read_text())
for name, addr in truth.items():
    d = run / f"FUN_{addr}"
    for cand, out in ((d / "baseline_a/recon.c", "difftest_baseline_a.json"), (d / "recon.c", "difftest_baseline_b.json")):
        if cand.exists():
            difftest.main(str(cand), name, f"FUN_{addr}", str(d / out))
PY
python3 src/metrics/collect.py "$RUN"
