#!/usr/bin/env python3
"""Build a playable Quake II game.so whose functions run AI-reconstructed code.

Original game sources are compiled with -fPIC into a shared library. Every
function whose AI reconstruction passed both test splits is linked in, and the
original function's first instruction is overwritten with a jump to the AI
version, so every caller (direct calls, function-pointer tables, statics) runs
the AI code. Ghidra names used by the reconstructions (FUN_/DAT_/PTR_/_UNK_ at
evaluation-binary addresses) are bound to the same original symbols, as in
difftest.py. Functions without a passing reconstruction keep the original code.

Needs build/ to hold the run's own build (scripts/build_pilot.py <run config>),
because names are mapped through build/pilot.unstripped.
Usage: build_ai_gameso.py <run_dir> <out_dir> [--include-untested]
Writes <out_dir>/game.so (AI), <out_dir>/game_orig.so (same build, no patching)
and <out_dir>/manifest.json (which function runs which code).
"""
import json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
INCLUDE_UNTESTED = "--include-untested" in sys.argv
os.environ["PILOT_CONFIG"] = str(next(p for p in (RUN / "_meta").glob("*.json")
                                      if p.stem not in ("build_info", "ground_truth", "extraction_summary")))
sys.path.insert(0, str(ROOT / "src/evaluation"))
import difftest

CFG = difftest.CFG
FLAGS = [f for f in CFG["cflags"] if f not in ("-fno-pie",)] + ["-fPIC", "-w"]
EVAL = ROOT / "build/pilot.unstripped"


def sh(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if p.returncode:
        raise SystemExit(f"failed: {' '.join(map(str, cmd))}\n{p.stderr[-3000:]}")
    return p.stdout


def passed(dt):
    return dt.exists() and (d := json.loads(dt.read_text()))["linked"] and d["splits"] and \
        all(v.get("status") == "pass" for v in d["splits"].values())


def compiled_untested(dt):
    return dt.exists() and "untested" in (d := json.loads(dt.read_text())) and d["compiled"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    objs = OUT / "objs"
    objs.mkdir(exist_ok=True)
    truth = json.loads((RUN / "_meta/ground_truth.json").read_text())

    # 1. original game, -fPIC. File-local symbols get unique global names so the
    #    AI code and the patcher can refer to them: <name> in g_ai.c -> __q2_g_ai__<name>.
    orig = []
    for s in CFG["sources"]:
        if Path(s).name == "main.c":
            continue
        src = ROOT / "build/patched" / Path(s).name
        src = src if src.exists() else ROOT / s
        o = objs / (Path(s).stem + ".o")
        sh([CFG["cc"], *FLAGS, *[f"-I{ROOT / d}" for d in CFG["include_dirs"]], "-c", str(src), "-o", str(o)])
        renames = []
        for line in sh(["nm", str(o)]).splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[1] in "tdbr":
                renames += [f"--redefine-sym={parts[2]}=__q2_{o.stem}__{parts[2]}",
                            f"--globalize-symbol=__q2_{o.stem}__{parts[2]}"]
        if renames:
            sh(["objcopy", *renames, str(o)])
        orig.append(o)
    sh([CFG["cc"], "-shared", "-o", str(OUT / "game_orig.so"), *map(str, orig), "-lm"])

    # 2. choose one AI version per function: repair round if it passed, else first attempt.
    chosen, manifest = {}, {}
    for name, addr in truth.items():
        d = RUN / f"FUN_{addr}"
        pick = None
        if passed(d / "repair1/difftest.json"):
            pick = ("repair", d / "repair1/recon.c")
        elif passed(d / "difftest_baseline_b.json"):
            pick = ("first_attempt", d / "recon.c")
        elif INCLUDE_UNTESTED and compiled_untested(d / "difftest_baseline_b.json"):
            pick = ("untested", d / "recon.c")
        manifest[name] = pick[0] if pick else "original"
        if pick:
            chosen[name] = (addr, pick[1])

    # 3. compile AI code; keep only FUN_<addr> global so helper names cannot collide.
    ai = []
    for name, (addr, src) in chosen.items():
        o = objs / f"ai_FUN_{addr}.o"
        sh([CFG["cc"], *FLAGS, "-c", str(src), "-o", str(o)])
        sh(["objcopy", f"--keep-global-symbol=FUN_{addr}", str(o)])
        ai.append(o)

    # 4. bind the Ghidra names the AI code still needs to original symbols.
    evaltab = difftest.symtab(EVAL)
    defined = {f"FUN_{a}" for a, _ in chosen.values()}
    undef = set()
    for o in ai:
        undef |= {u for u in sh(["nm", "-u", str(o)]).split() if difftest.GHIDRA_SYM.match(u)}
    undef -= defined
    so_name = lambda f, n: n if f is None else f"__q2_{Path(f).stem}__{n}"
    # Aliases are added as section-relative symbols inside the object that defines the
    # target (objcopy --add-symbol). --defsym would make them absolute, which breaks in a
    # shared library loaded at a random base.
    where = {}   # .so symbol name -> (object, section, value)
    for o in orig:
        secs = {}
        for line in sh(["readelf", "-SW", str(o)]).splitlines():
            m = re.match(r"\s*\[\s*(\d+)\]\s+(\S+)", line)
            if m:
                secs[m.group(1)] = m.group(2)
        for line in sh(["readelf", "-sW", str(o)]).splitlines():
            f = line.split()
            if len(f) >= 8 and f[0].rstrip(":").isdigit() and f[6] in secs and f[4] == "GLOBAL":
                where[f[7]] = (o, secs[f[6]], int(f[1], 16))
    adds = {}    # object -> [--add-symbol ...]
    def alias(new, target, off):
        o, sec, v = where[target]
        adds.setdefault(o, []).append(f"--add-symbol={new}={sec}:{v + off:#x},global")
    consts, relocs = [], []
    for g in sorted(undef):
        a = int(difftest.GHIDRA_SYM.match(g).group(1), 16)
        hit = next(((f, n, a - v) for f, n, v, sz, t in evaltab if v <= a < v + max(sz, 1) and t in ("FUNC", "OBJECT")), None)
        if hit:
            alias(g, so_name(hit[0], hit[1]), hit[2])
            continue
        b = difftest.rodata_bytes(EVAL, a)
        if b is None:
            raise SystemExit(f"{g}: no original symbol at 0x{a:x}")
        words = []
        for i in range(0, len(b) - len(b) % 8, 8):
            v = int.from_bytes(bytes(b[i:i + 8]), "little")
            h = next(((f, n, v - s) for f, n, s, sz, t in evaltab if s <= v < s + max(sz, 1) and t in ("FUNC", "OBJECT")), None)
            if h:
                relocs.append(f"__reloc_{len(relocs)}")
                alias(relocs[-1], so_name(h[0], h[1]), h[2])
                words.append(f"(unsigned long)&{relocs[-1]}")
            else:
                words.append(f"{v}UL")
        consts.append(f"const unsigned long {g}[{len(words)}] __attribute__((aligned(16))) = {{{', '.join(words)}}};\n")
    for o, a in adds.items():
        sh(["objcopy", *a, str(o)])
    csrc = objs / "consts.c"
    csrc.write_text("".join(f"extern char {r};\n" for r in relocs) + "".join(consts))
    sh([CFG["cc"], *FLAGS, "-c", str(csrc), "-o", str(objs / "consts.o")])
    so = OUT / "game.so"
    sh([CFG["cc"], "-shared", "-o", str(so), *map(str, orig), *map(str, ai), str(objs / "consts.o"), "-lm"])

    # 5. patch: original function entry -> jmp rel32 to the AI version.
    syms = {}
    for line in sh(["nm", str(so)]).splitlines():
        p = line.split()
        if len(p) == 3:
            syms[p[2]] = int(p[0], 16)
    text = next(l.split() for l in sh(["readelf", "-SW", str(so)]).splitlines() if " .text " in l)
    tva, toff = int(text[text.index(".text") + 2], 16), int(text[text.index(".text") + 3], 16)
    data = bytearray(so.read_bytes())
    for name, (addr, _) in chosen.items():
        f = next((f for f, n, v, sz, t in evaltab if n == name and t == "FUNC" and f"{v:x}" == addr.lstrip("0")), None)
        src_sym = so_name(f, name)
        at, to = syms[src_sym], syms[f"FUN_{addr}"]
        rel = to - (at + 5)
        data[toff + at - tva: toff + at - tva + 5] = b"\xe9" + rel.to_bytes(4, "little", signed=True)
    so.write_bytes(bytes(data))
    counts = {k: sum(v == k for v in manifest.values()) for k in sorted(set(manifest.values()))}
    (OUT / "manifest.json").write_text(json.dumps({"run": RUN.name, "counts": counts, "functions": manifest}, indent=1))
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
