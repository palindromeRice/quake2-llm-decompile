#!/usr/bin/env python3
"""Baseline A: Ghidra pseudocode, mechanically adapted, then differentially tested.

Mechanical adaptation only: prepend standard headers and typedefs for Ghidra's
pseudo-types. No signature fixes, no semantic edits.
Usage: baseline_a.py <run_dir> <original_name>=FUN_<addr> ...
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import difftest

ROOT = Path(__file__).resolve().parents[2]
PRELUDE = """#include <math.h>
#include <string.h>
#include <stdint.h>
typedef unsigned char undefined; typedef unsigned char undefined1; typedef uint16_t undefined2;
typedef uint32_t undefined4; typedef uint64_t undefined8; typedef unsigned char byte;
typedef unsigned int uint; typedef unsigned long ulong; typedef unsigned short ushort;
typedef long long longlong; typedef unsigned long long ulonglong; typedef unsigned char bool;
#define true 1
#define false 0
"""


def main(run_dir, *pairs):
    for pair in pairs:
        orig, fun = pair.split("=")
        rec = json.loads((ROOT / f"build/agent_inputs/{fun}.json").read_text())
        out = Path(run_dir) / fun
        out.mkdir(parents=True, exist_ok=True)
        sub = out / "baseline_a"
        sub.mkdir(exist_ok=True)
        (sub / "recon.c").write_text(PRELUDE + rec["pseudocode"])
        difftest.main(str(sub / "recon.c"), orig, fun, str(out / "difftest_baseline_a.json"))


if __name__ == "__main__":
    main(*sys.argv[1:])
