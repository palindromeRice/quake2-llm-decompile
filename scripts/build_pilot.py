#!/usr/bin/env python3
"""Build the pilot binary from unmodified Quake II sources.

Outputs (build/, git-ignored):
  pilot.unstripped   -- debug copy, evaluation side only
  pilot.stripped     -- the only binary Ghidra / the agent sees
  objs/*.o           -- original objects, reused by the differential tests
  eval/ground_truth.json -- name -> address map (evaluation side only)
  build_info.json    -- compiler version, flags, commands, hashes
"""
import hashlib, json, platform, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"


def run(cmd, log):
    log.append(cmd)
    subprocess.run(cmd, check=True, cwd=ROOT)


def sha256(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(cfg_path="configs/pilot.json"):
    cfg = json.loads((ROOT / cfg_path).read_text())
    (BUILD / "objs").mkdir(parents=True, exist_ok=True)
    (BUILD / "eval").mkdir(exist_ok=True)
    cmds, objs = [], []
    inc = [f"-I{d}" for d in cfg["include_dirs"]]
    for src in cfg["sources"]:
        obj = BUILD / "objs" / (Path(src).stem + ".o")
        run([cfg["cc"], *cfg["cflags"], *inc, "-c", src, "-o", str(obj.relative_to(ROOT))], cmds)
        objs.append(str(obj.relative_to(ROOT)))
    run([cfg["cc"], *objs, *cfg["ldflags"], "-o", "build/pilot.unstripped"], cmds)
    run(["strip", "--strip-all", "-o", "build/pilot.stripped", "build/pilot.unstripped"], cmds)

    # name -> address, from the unstripped copy (strip does not move code)
    nm = subprocess.run(["nm", "--defined-only", "build/pilot.unstripped"], cwd=ROOT,
                        capture_output=True, text=True, check=True).stdout
    syms = {l.split()[2]: int(l.split()[0], 16) for l in nm.splitlines() if l.split()[1] in "Tt"}
    missing = [f for f in cfg["pilot_functions"] if f not in syms]
    if missing:
        sys.exit(f"pilot functions missing from binary: {missing}")
    truth = {f: f"{syms[f]:08x}" for f in cfg["pilot_functions"]}
    (BUILD / "eval" / "ground_truth.json").write_text(json.dumps(truth, indent=2))

    # leak check: no original identifiers may remain in the stripped binary
    blob = (BUILD / "pilot.stripped").read_bytes()
    leaked = [f for f in cfg["pilot_functions"] if f.encode() in blob]

    info = {
        "cc_version": subprocess.run([cfg["cc"], "--version"], capture_output=True, text=True).stdout.splitlines()[0],
        "host": platform.platform(), "arch": platform.machine(),
        "cflags": cfg["cflags"], "ldflags": cfg["ldflags"], "commands": cmds,
        "sha256": {p: sha256(BUILD / p) for p in ("pilot.unstripped", "pilot.stripped")},
        "quake2_commit": subprocess.run(["git", "-C", "third_party/Quake-2", "rev-parse", "HEAD"],
                                        cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "pilot_names_found_in_stripped_binary": leaked,
    }
    (BUILD / "build_info.json").write_text(json.dumps(info, indent=2))
    print(json.dumps({"ground_truth": truth, "leaked_names": leaked}, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:])
