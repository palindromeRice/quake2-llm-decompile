#!/usr/bin/env bash
# End-to-end pilot: build -> Ghidra extract -> Baseline A + B -> difftest -> metrics.
# Usage: run_pilot.sh [configs/pilot_O0.json]
# Env: JAVA_HOME (defaults to ~/tools install), GHIDRA_HOME (see run_ghidra.py).
set -euo pipefail
cd "$(dirname "$0")/.."
export PILOT_CONFIG="${1:-configs/pilot_O0.json}"
export JAVA_HOME="${JAVA_HOME:-$HOME/tools/jdk-21.0.12.1+1}"
export PATH="$JAVA_HOME/bin:$PATH"

[ -d third_party/Quake-2 ] || git clone https://github.com/id-Software/Quake-2 third_party/Quake-2
git -C third_party/Quake-2 checkout -q 372afde46e7defc9dd2d719a1732b8ace1fa096e

python3 scripts/build_pilot.py "$PILOT_CONFIG"
python3 src/extraction/run_ghidra.py

RUN="experiments/pilot/runs/$(date +%Y%m%d-%H%M%S)-$(basename "$PILOT_CONFIG" .json)"
# snapshot everything needed to interpret this run later
mkdir -p "$RUN/_meta"
cp "$PILOT_CONFIG" build/build_info.json build/eval/ground_truth.json build/ghidra/extraction_summary.json "$RUN/_meta/"
cp -r build/agent_inputs "$RUN/_meta/"

# targets: config "reconstruct" list, resolved to addresses (evaluation side)
mapfile -t PAIRS < <(python3 -c '
import json, os; c=json.load(open(os.environ["PILOT_CONFIG"])); t=json.load(open("build/eval/ground_truth.json"))
[print(f"{n}=FUN_{t[n]}") for n in c["reconstruct"] if os.path.exists(f"build/agent_inputs/FUN_{t[n]}.json")]')

python3 src/evaluation/baseline_a.py "$RUN" "${PAIRS[@]}" >/dev/null
for p in "${PAIRS[@]}"; do
  name="${p%%=*}"; fun="${p##*=}"
  python3 src/reconstruction/single_pass.py "$RUN" "$fun"
  if [ -f "$RUN/$fun/recon.c" ]; then
    python3 src/evaluation/difftest.py "$RUN/$fun/recon.c" "$name" "$fun" "$RUN/$fun/difftest_baseline_b.json" >/dev/null
  fi
done
python3 src/metrics/collect.py "$RUN"
