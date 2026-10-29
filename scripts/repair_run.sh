#!/usr/bin/env bash
# One repair round over a whole run: every target whose first attempt failed gets one
# feedback call (repair.py decides; passes and already-repaired targets are skipped).
# Safe to re-run after a usage limit or an agent switch: nothing done is redone.
# Usage: AGENT_CMD=<cmd> [AGENT=agent_a|agent_b] [JOBS=6] repair_run.sh <run_dir>
set -euo pipefail
cd "$(dirname "$0")/.."
RUN="$1"
export RUN PILOT_CONFIG="$RUN/_meta/$(ls "$RUN/_meta" | grep -vxE '(build_info|ground_truth|extraction_summary)\.json' | grep '\.json$')"
python3 scripts/build_pilot.py "$PILOT_CONFIG" >/dev/null 2>&1
cmp -s build/eval/ground_truth.json "$RUN/_meta/ground_truth.json" || { echo "rebuild differs from run" >&2; exit 1; }
rm -f "$RUN/STOP_${AGENT:-agent_a}.txt"
python3 -c '
import json, os, sys
run = sys.argv[1]
for name, addr in json.load(open(f"{run}/_meta/ground_truth.json")).items():
    if os.path.exists(f"{run}/FUN_{addr}/response.json"):
        print(name, f"FUN_{addr}")' "$RUN" | xargs -P "${JOBS:-6}" -n 2 sh -c 'python3 src/reconstruction/repair.py "$RUN" "$0" "$1"'
python3 src/metrics/collect.py "$RUN" >/dev/null
python3 scripts/status.py "$RUN"
