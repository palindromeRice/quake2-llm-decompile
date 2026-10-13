#!/usr/bin/env python3
"""Where a run stands, per agent. Usage: status.py <run_dir>"""
import collections, json, sys
from pathlib import Path

run = Path(sys.argv[1])
gt = json.loads((run / "_meta/ground_truth.json").read_text())
c = collections.Counter()
for addr in gt.values():
    d = run / f"FUN_{addr}"
    if not d.exists():
        c["extraction_missed"] += 1
        continue
    r = d / "response.json"
    if r.exists():
        a = json.loads(r.read_text()).get("agent", "agent_a")
        c[f"answered_by_{a}"] += 1
        c[f"recon_by_{a}"] += (d / "recon.c").exists()
    else:
        c["pending_first_attempt"] += 1
    r1 = d / "repair1/response.json"
    if r1.exists():
        c[f"repaired_by_{json.loads(r1.read_text()).get('agent', 'agent_a')}"] += 1
print(run.name, "targets", len(gt))
for k in sorted(c):
    print(f"  {k:24s} {c[k]}")
for s in sorted(run.glob("STOP_*.txt")):
    print(f"  {s.name}: {s.read_text().strip()[:200]}")
