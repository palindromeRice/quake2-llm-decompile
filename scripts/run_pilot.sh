#!/usr/bin/env bash
# End-to-end pilot: build -> Ghidra extract -> Baseline A + B -> difftest -> metrics.
# Env: GHIDRA_HOME, JAVA_HOME (default to ~/tools installs).
set -euo pipefail
cd "$(dirname "$0")/.."
export JAVA_HOME="${JAVA_HOME:-$HOME/tools/jdk-21.0.12.1+1}"
export PATH="$JAVA_HOME/bin:$PATH"

[ -d third_party/Quake-2 ] || git clone https://github.com/id-Software/Quake-2 third_party/Quake-2
git -C third_party/Quake-2 checkout -q 372afde46e7defc9dd2d719a1732b8ace1fa096e

python3 scripts/build_pilot.py
python3 src/extraction/run_ghidra.py

RUN="experiments/pilot/runs/$(date +%Y%m%d-%H%M%S)"
# targets: configs/pilot.json "reconstruct" list, resolved to addresses (evaluation side)
mapfile -t PAIRS < <(python3 -c '
import json; c=json.load(open("configs/pilot.json")); t=json.load(open("build/eval/ground_truth.json"))
[print(f"{n}=FUN_{t[n]}") for n in c["reconstruct"]]')

python3 src/evaluation/baseline_a.py "$RUN" "${PAIRS[@]}"
for p in "${PAIRS[@]}"; do
  name="${p%%=*}"; fun="${p##*=}"
  python3 src/reconstruction/single_pass.py "$RUN" "$fun"
  if [ -f "$RUN/$fun/recon.c" ]; then
    python3 src/evaluation/difftest.py "$RUN/$fun/recon.c" "$name" "$fun" "$RUN/$fun/difftest_baseline_b.json" >/dev/null
  fi
done
python3 src/metrics/collect.py "$RUN"
