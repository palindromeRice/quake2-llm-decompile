#!/usr/bin/env bash
# Finish an interrupted run: reconstruct + test only targets with no response.json yet
# (failed calls / usage limit). Targets answered by any agent are never redone.
# Needs build/ to hold the same config's build (rebuilt and checked here).
# Usage: AGENT_CMD=<cmd> [AGENT=agent_a|agent_b] [JOBS=6] resume_run.sh <run_dir>
set -euo pipefail
cd "$(dirname "$0")/.."
RUN="$1"
export RUN PILOT_CONFIG="$RUN/_meta/$(ls "$RUN/_meta" | grep -vxE '(build_info|ground_truth|extraction_summary)\.json' | grep '\.json$')"
python3 scripts/build_pilot.py "$PILOT_CONFIG" >/dev/null 2>&1
cmp -s build/eval/ground_truth.json "$RUN/_meta/ground_truth.json" || { echo "rebuild differs from run" >&2; exit 1; }
rm -f "$RUN/STOP_${AGENT:-agent_a}.txt"   # limit may have reset; single_pass re-creates it if not
rm -rf build/agent_inputs && cp -r "$RUN/_meta/agent_inputs" build/agent_inputs
python3 -c '
import json, os, sys
run = sys.argv[1]
for name, addr in json.load(open(f"{run}/_meta/ground_truth.json")).items():
    d = f"{run}/FUN_{addr}"
    if os.path.exists(f"build/agent_inputs/FUN_{addr}.json") and not os.path.exists(f"{d}/response.json"):
        print(f"{name}=FUN_{addr}")' "$RUN" | xargs -P "${JOBS:-6}" -I{} sh -c '
  name="${1%%=*}"; fun="${1##*=}"
  python3 src/reconstruction/single_pass.py "$RUN" "$fun" || true
  if [ -f "$RUN/$fun/recon.c" ]; then
    python3 src/evaluation/difftest.py "$RUN/$fun/recon.c" "$name" "$fun" "$RUN/$fun/difftest_baseline_b.json" >/dev/null 2>&1 || true
  fi' _ {}
python3 src/metrics/collect.py "$RUN"
