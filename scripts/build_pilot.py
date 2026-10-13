#!/usr/bin/env python3
"""Build the pilot binary from unmodified Quake II sources.

Outputs (build/, git-ignored):
  pilot.unstripped   -- debug copy, evaluation side only
  pilot.stripped     -- the only binary Ghidra / the agent sees
  objs/*.o           -- original objects, reused by the differential tests
  eval/ground_truth.json -- name -> address map (evaluation side only)
  build_info.json    -- compiler version, flags, commands, hashes
"""
import hashlib, json, os, platform, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"


def run(cmd, log):
    log.append(cmd)
    subprocess.run(cmd, check=True, cwd=ROOT)


def sha256(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def apply_patches(patches):
    """Portability patches: write a patched copy under build/patched/, never touch third_party.
    Each patch: {file, pattern, replace, count, why}. Returns {original path: patched path}."""
    out = {}
    for p in patches:
        src = (ROOT / out.get(p["file"], p["file"])).read_text(errors="surrogateescape")
        new, n = re.subn(p["pattern"], p["replace"], src, flags=re.M)
        if n != p["count"]:
            sys.exit(f"patch for {p['file']} matched {n} times, expected {p['count']}")
        dst = BUILD / "patched" / Path(p["file"]).name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(new, errors="surrogateescape")
        out[p["file"]] = str(dst.relative_to(ROOT))
    return out


def main(cfg_path="configs/pilot_O0.json"):
    cfg = json.loads((ROOT / cfg_path).read_text())
    (BUILD / "objs").mkdir(parents=True, exist_ok=True)
    (BUILD / "eval").mkdir(exist_ok=True)
    cmds, objs = [], []
    inc = [f"-I{d}" for d in cfg["include_dirs"]]
    os.environ["SOURCE_DATE_EPOCH"] = "946684800"   # pins __DATE__/__TIME__ in the game code
    patched = apply_patches(cfg.get("patches", []))
    for src in cfg["sources"]:
        src = patched.get(src, src)
        obj = BUILD / "objs" / (Path(src).stem + ".o")
        run([cfg["cc"], *cfg["cflags"], *inc, "-c", src, "-o", str(obj.relative_to(ROOT))], cmds)
        objs.append(str(obj.relative_to(ROOT)))
    run([cfg["cc"], *objs, *cfg["ldflags"], "-o", "build/pilot.unstripped"], cmds)
    run(["strip", "--strip-all", "-o", "build/pilot.stripped", "build/pilot.unstripped"], cmds)

    # name -> address, from the unstripped copy (strip does not move code)
    nm = subprocess.run(["nm", "--defined-only", "build/pilot.unstripped"], cwd=ROOT,
                        capture_output=True, text=True, check=True).stdout
    syms = {l.split()[2]: int(l.split()[0], 16) for l in nm.splitlines() if l.split()[1] in "Tt"}
    # functions present in source but not emitted (unused statics, disabled code) are recorded, not fatal
    missing = [f for f in cfg["pilot_functions"] if f not in syms]
    truth = {f: f"{syms[f]:08x}" for f in cfg["pilot_functions"] if f in syms}
    (BUILD / "eval" / "ground_truth.json").write_text(json.dumps(truth, indent=2))

    # leak check: no original identifiers may remain in the stripped binary
    blob = (BUILD / "pilot.stripped").read_bytes()
    leaked = [f for f in cfg["pilot_functions"] if f.encode() in blob]

    info = {
        "config": cfg_path,
        "cc_version": subprocess.run([cfg["cc"], "--version"], capture_output=True, text=True).stdout.splitlines()[0],
        "host": platform.platform(), "arch": platform.machine(),
        "cflags": cfg["cflags"], "ldflags": cfg["ldflags"], "commands": cmds,
        "patches": cfg.get("patches", []), "SOURCE_DATE_EPOCH": os.environ["SOURCE_DATE_EPOCH"],
        "sha256": {p: sha256(BUILD / p) for p in ("pilot.unstripped", "pilot.stripped")},
        "quake2_commit": subprocess.run(["git", "-C", "third_party/Quake-2", "rev-parse", "HEAD"],
                                        cwd=ROOT, capture_output=True, text=True).stdout.strip(),
        "pilot_names_found_in_stripped_binary": leaked,
        "pilot_functions_not_in_binary": missing,
    }
    (BUILD / "build_info.json").write_text(json.dumps(info, indent=2))
    print(json.dumps({"targets": len(truth), "not_in_binary": missing, "leaked_names": leaked}, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:])
