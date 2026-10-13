#!/usr/bin/env bash
# Re-run difftests + metrics for an existing run directory without new model calls (A, B and repair round).
# Rebuilds the run's config first so original objects match. Usage: [JOBS=6] retest_run.sh <run_dir>
set -euo pipefail
cd "$(dirname "$0")/.."
RUN="$1"
export PILOT_CONFIG="$RUN/_meta/$(ls "$RUN/_meta" | grep -vxE '(build_info|ground_truth|extraction_summary)\.json' | grep '\.json$')"
python3 scripts/build_pilot.py "$PILOT_CONFIG" >/dev/null
cmp -s build/eval/ground_truth.json "$RUN/_meta/ground_truth.json" || { echo "rebuild differs from run" >&2; exit 1; }
python3 - "$RUN" <<'PY'
import json, os, sys
from multiprocessing import Pool
from pathlib import Path
sys.path.insert(0, "src/evaluation")
import difftest
difftest.QUIET = True
run = Path(sys.argv[1])
truth = json.loads((run / "_meta/ground_truth.json").read_text())
jobs = []
for name, addr in truth.items():
    d = run / f"FUN_{addr}"
    for cand, out in ((d / "baseline_a/recon.c", "difftest_baseline_a.json"), (d / "recon.c", "difftest_baseline_b.json"),
                      (d / "repair1/recon.c", "repair1/difftest.json")):
        if cand.exists():
            jobs.append((str(cand), name, f"FUN_{addr}", str(d / out)))
with Pool(int(os.environ.get("JOBS", 6))) as p:   # work dirs are per candidate, so parallel-safe
    res = p.starmap(difftest.main, jobs, chunksize=1)
# Safety net: re-run every linked non-pass result alone. (3 false crashes seen once came from a
# stray concurrent re-test sharing work dirs, since fixed; this check stays cheap insurance.)
for job, r in zip(jobs, res):
    if r["linked"] and any(v.get("status") != "pass" for v in r["splits"].values()):
        difftest.main(*job)
PY
python3 src/metrics/collect.py "$RUN"
