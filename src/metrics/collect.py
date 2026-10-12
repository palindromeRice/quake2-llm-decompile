#!/usr/bin/env python3
"""Aggregate one run directory into results/<run>.csv and results/<run>.json.

Usage: collect.py <run_dir>
Failure category per row: compile_error | link_error | crash | timeout |
behavior_mismatch | heldout_only_mismatch | no_code | pass.
"""
import csv, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def category(dt):
    if dt == "missing":
        return "extraction_missed"
    if dt is None:
        return "no_code"
    if not dt["compiled"]:
        return "compile_error"
    if not dt["linked"]:
        return "link_error"
    st = {k: v["status"] for k, v in dt["splits"].items()}
    for bad in ("crash", "timeout"):
        if any(s.startswith(bad) for s in st.values()):
            return bad
    if st.get("dev") != "pass":
        return "behavior_mismatch"
    return "heldout_only_mismatch" if st.get("heldout") != "pass" else "pass"


def main(run_dir):
    run = Path(run_dir)
    gt = run / "_meta/ground_truth.json"
    if not gt.exists():   # runs before per-run snapshots existed
        gt = ROOT / "build/eval/ground_truth.json"
    truth = {v: k for k, v in json.loads(gt.read_text()).items()}
    rows = []
    for addr, orig in sorted(truth.items()):
        fdir = run / f"FUN_{addr}"
        for base, dt_file in (("A_ghidra", "difftest_baseline_a.json"), ("B_agent_a_single", "difftest_baseline_b.json")):
            f = fdir / dt_file
            dt = "missing" if not fdir.exists() else json.loads(f.read_text()) if f.exists() else None
            if dt == "missing":
                rows.append({"function_addr": fdir.name, "original_name": orig, "baseline": base,
                             "category": "extraction_missed"})
                continue
            row = {"function_addr": fdir.name, "original_name": orig, "baseline": base,
                   "category": category(dt),
                   "compiled": bool(dt and dt["compiled"]),
                   "dev_pass": bool(dt and dt["splits"].get("dev", {}).get("status") == "pass"),
                   "heldout_pass": bool(dt and dt["splits"].get("heldout", {}).get("status") == "pass"),
                   "pass_nan_relaxed": bool(dt and dt["splits"] and all(
                       s.get("mismatches_nan_relaxed") == 0 for s in dt["splits"].values())),
                   "dev_cases": dt["splits"].get("dev", {}).get("cases") if dt else None,
                   "heldout_cases": dt["splits"].get("heldout", {}).get("cases") if dt else None,
                   "agent_a_calls": 0, "input_tokens": 0, "cache_creation_tokens": 0,
                   "output_tokens": 0, "cost_usd": 0.0, "wall_seconds": None,
                   "original_name_in_recon": None, "prompt_leak": None}
            resp = fdir / "response.json"
            if base.startswith("B") and resp.exists():
                r = json.loads(resp.read_text())
                u = r.get("usage", {})
                row.update(agent_a_calls=1, input_tokens=u.get("input_tokens", 0),
                           cache_creation_tokens=u.get("cache_creation_input_tokens", 0),
                           output_tokens=u.get("output_tokens", 0),
                           cost_usd=r.get("total_cost_usd", 0.0), wall_seconds=r.get("wall_seconds"))
                # validity flag: original name or project name reached the prompt via the binary
                prompt = (fdir / "prompt.txt").read_text()
                row["prompt_leak"] = bool(re.search(rf"\b{re.escape(orig)}\b|quake", prompt, re.I))
                recon = fdir / "recon.c"
                # contamination signal: original identifier appearing in output
                row["original_name_in_recon"] = bool(recon.exists() and re.search(
                    rf"\b{re.escape(orig)}\b", recon.read_text(), re.I))
            rows.append(row)
    (ROOT / "results").mkdir(exist_ok=True)
    out = ROOT / "results" / run.name
    with open(f"{out}.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=max((list(r) for r in rows), key=len))
        w.writeheader()
        w.writerows(rows)
    summary = {}
    for base in sorted({r["baseline"] for r in rows}):
        rs = [r for r in rows if r["baseline"] == base]
        summary[base] = {"attempted": len(rs),
                         "compile_rate": sum(r.get("compiled", False) for r in rs) / len(rs),
                         "dev_pass_rate": sum(r.get("dev_pass", False) for r in rs) / len(rs),
                         "heldout_pass_rate": sum(r.get("heldout_pass", False) for r in rs) / len(rs),
                         "pass_nan_relaxed_rate": sum(r.get("pass_nan_relaxed", False) for r in rs) / len(rs),
                         "agent_a_calls": sum(r.get("agent_a_calls", 0) for r in rs),
                         "cost_usd": round(sum(r.get("cost_usd", 0) for r in rs), 4),
                         "categories": {c: sum(r["category"] == c for r in rs) for c in {r["category"] for r in rs}}}
    Path(f"{out}.json").write_text(json.dumps({"run": run.name, "summary": summary, "rows": rows}, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:])
