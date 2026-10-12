#!/usr/bin/env python3
"""Compile a candidate (recon.c) and run it against the original object code.

Usage: difftest.py <candidate.c> <original_name> <FUN_name> [out.json]
Original objects come from build/objs (same flags as the evaluation binary).
Records: compile/link errors, crashes/timeouts, per-split mismatch counts.
"""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = json.loads((ROOT / "configs/pilot.json").read_text())
ORIG_OBJS = ["q_shared.o", "g_utils.o", "stubs.o"]


def sh(cmd, timeout=120):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return "timeout", "", ""


def main(candidate, orig, fun, out=None):
    cand = Path(candidate).resolve()
    work = ROOT / "build/difftest" / f"{orig}__{cand.parent.name}"
    work.mkdir(parents=True, exist_ok=True)
    res = {"candidate": str(cand), "function": orig, "target": fun,
           "compiled": False, "linked": False, "splits": {}}

    rc, _, err = sh([CFG["cc"], *CFG["cflags"], "-c", str(cand), "-o", str(work / "cand.o")])
    res["compile_stderr"] = err[-4000:]
    if rc != 0:
        return dump(res, out)
    res["compiled"] = True

    rc, _, err = sh([CFG["cc"], *CFG["cflags"], f"-DRECON={fun}", f"tests/difftest/{orig}.c",
                     str(work / "cand.o"), *[f"build/objs/{o}" for o in ORIG_OBJS],
                     "-no-pie", "-lm", "-o", str(work / "driver")])
    res["link_stderr"] = err[-4000:]
    if rc != 0:
        return dump(res, out)
    res["linked"] = True

    for split in ("dev", "heldout"):
        rc, so, se = sh([str(work / "driver"), split], timeout=60)
        if rc == "timeout" or (isinstance(rc, int) and rc < 0):
            res["splits"][split] = {"status": "timeout" if rc == "timeout" else f"crash(signal {-rc})"}
            continue
        r = json.loads(so.strip().splitlines()[-1])
        r["status"] = "pass" if r["mismatches"] == 0 else "mismatch"
        r["examples"] = se.strip().splitlines()[:5]
        res["splits"][split] = r
    return dump(res, out)


def dump(res, out):
    s = json.dumps(res, indent=2)
    if out:
        Path(out).write_text(s)
    print(s)
    return res


if __name__ == "__main__":
    main(*sys.argv[1:])
