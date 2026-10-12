#!/usr/bin/env python3
"""Run Ghidra headless on the stripped binary and emit agent-visible inputs.

  build/ghidra/functions.jsonl          all functions Ghidra found
  build/ghidra/headless.log             full Ghidra log
  experiments/pilot/agent_inputs/*.json one file per pilot target (Ghidra data only)

Targets are chosen by address via the evaluation-side ground truth; the agent
input files contain only what Ghidra recovered from the stripped binary.
"""
import json, os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GHIDRA = Path(os.environ.get("GHIDRA_HOME", Path.home() / "tools/ghidra_12.1.4_PUBLIC"))
OUT = ROOT / "build/ghidra"
AGENT = ROOT / "experiments/pilot/agent_inputs"


def main(binary="build/pilot.stripped"):
    OUT.mkdir(parents=True, exist_ok=True)
    AGENT.mkdir(parents=True, exist_ok=True)
    jsonl = OUT / "functions.jsonl"
    cmd = [str(GHIDRA / "support/analyzeHeadless"), str(OUT), "pilot",
           "-import", str(ROOT / binary), "-overwrite", "-deleteProject",
           "-scriptPath", str(ROOT / "ghidra_scripts"),
           "-postScript", "ExportFunctions.java", str(jsonl)]
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True)
    (OUT / "headless.log").write_text(p.stdout + p.stderr)
    if p.returncode or not jsonl.exists():
        sys.exit(f"ghidra failed (rc={p.returncode}); see build/ghidra/headless.log")

    funcs = {int(r["address"], 16): r for r in map(json.loads, jsonl.read_text().splitlines())}
    truth = json.loads((ROOT / "build/eval/ground_truth.json").read_text())
    errors = []
    for name, addr in truth.items():
        rec = funcs.get(int(addr, 16))
        if rec is None:
            errors.append({"address": addr, "error": "no function at address"})
            continue
        if rec.get("error"):
            errors.append({"address": addr, "error": rec.get("error")})
        (AGENT / f"FUN_{addr}.json").write_text(json.dumps(rec, indent=2))
    summary = {"functions_found": len(funcs), "targets": len(truth), "errors": errors,
               "seconds": round(time.time() - t0, 1),
               "ghidra_version": GHIDRA.name}
    (OUT / "extraction_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:])
