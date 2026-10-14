#!/usr/bin/env python3
"""Compile a candidate (recon.c) and run it against the original object code.

Usage: difftest.py <candidate.c> <original_name> <FUN_name> [out.json]
Original objects come from build/objs (same flags as the evaluation binary).
Records: compile/link errors, crashes/timeouts, per-split mismatch counts.
"""
import hashlib, json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUIET = False
CFG_PATH = os.environ.get("PILOT_CONFIG", "configs/pilot_O0.json")
CFG = json.loads((ROOT / CFG_PATH).read_text())
# original objects = every configured source except the empty main
ORIG_OBJS = [Path(s).stem + ".o" for s in CFG["sources"] if Path(s).name != "main.c"]


def sh(cmd, timeout=120):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout, cwd=ROOT)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return "timeout", "", ""


def main(candidate, orig, fun, out=None):
    cand = Path(candidate).resolve()
    # one work dir per candidate file: runs and baselines never share one
    work = ROOT / "build/difftest" / f"{orig}__{cand.parent.name}__{hashlib.sha1(str(cand.parent).encode()).hexdigest()[:8]}"
    work.mkdir(parents=True, exist_ok=True)
    res = {"candidate": str(cand), "function": orig, "target": fun,
           "compiled": False, "linked": False, "splits": {}}

    if cand.suffix == ".o":   # pre-built candidate object (used by mutation_check)
        rc, err = 0, ""
        (work / "cand.o").write_bytes(cand.read_bytes())
    else:
        rc, _, err = sh([CFG["cc"], *CFG["cflags"], "-c", str(cand), "-o", str(work / "cand.o")])
    res["compile_stderr"] = err[-4000:]
    if rc != 0:
        return dump(res, out)
    res["compiled"] = True
    if STATEFUL and orig not in STATEFUL:   # harness cannot call this signature yet
        res["untested"] = CFG.get("compile_only", {}).get(orig, "no harness for this signature")
        return dump(res, out)

    rc, err = link_driver(orig, fun, work / "cand.o", work / "driver")
    res["link_stderr"] = err[-4000:]
    if rc != 0:
        return dump(res, out)
    res["linked"] = True

    for split in ("dev", "heldout"):
        rc, so, se = sh([str(work / "driver"), split], timeout=300)
        if rc == "timeout" or (isinstance(rc, int) and rc < 0):
            res["splits"][split] = {"status": "timeout" if rc == "timeout" else f"crash(signal {-rc})"}
            continue
        r = json.loads(so.strip().splitlines()[-1])
        r["status"] = "pass" if r["mismatches"] == 0 else "mismatch"
        r["examples"] = se.strip().splitlines()[:5]
        if STATEFUL:   # whole-state byte comparison has no NaN-relaxed mode
            r["mismatches_nan_relaxed"] = r["mismatches"]
            res["splits"][split] = r
            continue
        # secondary metric: NaN sign/payload differences ignored
        rc2, so2, _ = sh([str(work / "driver"), split, "relaxed"], timeout=60)
        r["mismatches_nan_relaxed"] = json.loads(so2.strip().splitlines()[-1])["mismatches"] if rc2 in (0, 1) else None
        res["splits"][split] = r
    return dump(res, out)


STATEFUL = CFG.get("stateful", {})   # name -> harness call shape (self|pair|use|spawn)
INC = [f"-I{d}" for d in CFG["include_dirs"]]
GHIDRA_SYM = re.compile(r"^(?:FUN|_?DAT|_UNK|PTR_\w*?|s_\w*?|u_\w*?)_([0-9a-fA-F]{6,16})$")


def link_driver(orig, recon_sym, cand_obj, exe, extra=()):
    """Build the differential driver. Returns (rc, stderr)."""
    objs = [f"build/objs/{o}" for o in ORIG_OBJS]
    if not STATEFUL:
        rc, _, err = sh([CFG["cc"], *CFG["cflags"], f"-DRECON={recon_sym}", f"tests/difftest/{orig}.c",
                         *([str(cand_obj)] if cand_obj else []), *objs, "-no-pie", "-lm", "-o", str(exe)])
        return rc, err
    spec = target_spec(orig)
    sig_h = Path(exe).with_suffix(".sig.h").resolve()
    sig_h.write_text(sig_header(spec["sig"]))
    hobj = Path(exe).with_suffix(".harness.o")
    rc, _, err = sh([CFG["cc"], *CFG["cflags"], *INC, f'-DSIG_H="{sig_h}"',
                     "-c", "tests/stateful/harness.c", "-o", str(hobj)])
    if rc != 0:
        return rc, err
    cmd = [CFG["cc"], str(hobj), *objs, *([str(cand_obj)] if cand_obj else []), "-no-pie", "-lm", "-o", str(exe)]
    # Two-pass link. Pass 1 binds every name we must resolve to 0 to learn the layout;
    # pass 2 binds each to its real address. Absolute symbols do not change section
    # sizes, so the layout is identical in both passes (checked below).
    #  - orig_target: the original function (may be file-local static)
    #  - recon_target: the candidate's FUN_ symbol, or the original itself (self-check)
    #  - Ghidra names the candidate uses (FUN_/DAT_<eval addr>): the same original symbol (+offset)
    undef = sh(["nm", "-u", str(cand_obj)])[1].split() if cand_obj else []
    ghidra = [u for u in undef if GHIDRA_SYM.match(u)]
    eval_bin = ROOT / "build/pilot.unstripped"
    evaltab = symtab(eval_bin)
    named, consts, missing = {}, {}, []
    for g in ghidra:
        addr = int(GHIDRA_SYM.match(g).group(1), 16)
        hit = next(((f, n, addr - v) for f, n, v, sz, t in evaltab
                    if v <= addr < v + max(sz, 1) and t in ("FUNC", "OBJECT")), None)
        if hit:
            named[g] = hit
        elif (b := rodata_bytes(eval_bin, addr)) is not None:
            consts[g] = b   # unnamed read-only constant (literal pool): same bytes as the binary
        else:
            missing.append(f"{g}: no original symbol at 0x{addr:x}")
    if missing:
        return 1, "unmapped Ghidra symbols:\n" + "\n".join(missing)
    # Unnamed rodata constants are re-created from the binary's bytes. An 8-byte word that
    # equals an original symbol's address (e.g. -O2 tables of function pointers) is
    # re-bound to that symbol in the driver binary via a __reloc_N placeholder.
    relocs = {}   # placeholder -> (file, name, offset)
    if consts:
        lines = []
        for g, b in consts.items():
            if len(b) % 8:
                lines.append(f"const unsigned char {g}[{len(b)}] __attribute__((aligned(16))) = {{{', '.join(map(str, b))}}};\n")
                continue
            words = []
            for i in range(0, len(b), 8):
                v = int.from_bytes(bytes(b[i:i + 8]), "little")
                hit = next(((f, n, v - a) for f, n, a, sz, t in evaltab
                            if a <= v < a + max(sz, 1) and t in ("FUNC", "OBJECT")), None)
                if hit:
                    ph = f"__reloc_{len(relocs)}"
                    relocs[ph] = hit
                    words.append(f"(unsigned long)&{ph}")
                else:
                    words.append(f"{v}UL")
            lines.append(f"const unsigned long {g}[{len(words)}] __attribute__((aligned(16))) = {{{', '.join(words)}}};\n")
        csrc = Path(exe).with_suffix(".consts.c")
        csrc.write_text("".join(f"extern char {ph};\n" for ph in relocs) + "".join(lines))
        rc, _, err = sh([CFG["cc"], "-c", str(csrc), "-o", str(csrc.with_suffix(".o"))])
        if rc != 0:
            return rc, err
        cmd.insert(-4, str(csrc.with_suffix(".o")))
    # Two-pass link: pass 1 binds Ghidra names to 0 to learn the layout; pass 2 binds
    # each to the same original symbol (+offset) in this binary. Absolute symbols do
    # not change section sizes, so the layout is identical in both passes.
    recon_def = [f"-Wl,--defsym=recon_target={recon_sym}"] if cand_obj else []
    rc, _, err = sh(cmd + [f"-Wl,--defsym={g}=0" for g in [*named, *relocs, "orig_target"]] +
                    (recon_def or ["-Wl,--defsym=recon_target=0"]))
    if rc != 0:
        return rc, err
    drv = {(f, n): v for f, n, v, _, _ in symtab(exe)}
    keys = [k for k in drv if k[1] == orig and (k[0] is None or spec["file"] in (None, k[0]))]
    if len(keys) != 1:
        return 1, f"original {orig} ({spec['file']}) found {len(keys)} times in driver binary"
    defs = [f"-Wl,--defsym=orig_target=0x{drv[keys[0]]:x}"]
    defs += recon_def or [f"-Wl,--defsym=recon_target=0x{drv[keys[0]]:x}"]
    for g, (f, n, off) in {**named, **relocs}.items():
        if (f, n) not in drv:
            return 1, f"{g}: {n} ({f}) not in driver binary"
        defs.append(f"-Wl,--defsym={g}=0x{drv[(f, n)] + off:x}")
    rc, _, err = sh(cmd + defs)
    if rc == 0 and {k: v for k, v in symtab_map(exe).items() if not GHIDRA_SYM.match(k[1]) and not k[1].startswith("__reloc_")} != \
            {k: v for k, v in drv.items() if not GHIDRA_SYM.match(k[1]) and not k[1].startswith("__reloc_")}:
        return 1, "layout changed between link passes"
    return rc, err


SIG_LEGACY = {"self": "n:e", "pair": "i:ee", "use": "n:eee", "spawn": "e:"}
C_TYPE = {"g": "gitem_t *", "p": "cplane_t *", "u": "csurface_t *", "l": "gclient_t *", "U": "usercmd_t *",
          "m": "moveinfo_t *", "h": "short", "G": "gitem_t *",
          "c": "edict_t *", "e": "edict_t *", "f": "float", "i": "int", "b": "qboolean", "v": "float *", "s": "char *", "o": "int", "n": "void"}
GEN = {"g": "arg_g ()", "p": "arg_p ({i})", "u": "arg_u ({i})", "l": "arg_l ()", "U": "arg_U ({i})", "m": "arg_m ()",
       "h": "(short)arg_i ()",
       "c": "&g_edicts[ri (1, game.maxclients)]", "e": "arg_e ({i})", "f": "arg_f ()", "i": "arg_i ()", "b": "arg_b ()", "v": "arg_v ({i})", "s": "arg_s ()", "o": "arg_o ()"}
RET = {"h": "((long)(F))", "G": "({ gitem_t *it_ = (F); it_ ? (long)(it_ - itemlist) : -1L; })", "n": "((F), 0L)", "i": "((long)(F))", "b": "((long)(F))", "f": "fbits_l (F)", "e": "EI (F)", "s": "((long)hash_str (F))"}


def target_spec(name):
    """Config entry -> {"sig": "<ret>:<args>", "file": basename or None}. Codes: e edict_t*,
    c player edict_t* (slots 1..maxclients, for functions the game only calls on players), f float,
    harness v2: g gitem_t*, G gitem_t* return (compared as item index), p cplane_t*, u csurface_t*,
    l gclient_t*, U usercmd_t*, m moveinfo_t*, h short,
    i int, b qboolean, v vec3_t, s char*, o string-field offset, n void."""
    t = STATEFUL[name]
    if isinstance(t, str):
        return {"sig": SIG_LEGACY.get(t, t), "file": None}
    return {"sig": t["sig"], "file": t.get("file")}


def sig_header(sig):
    ret, args = sig.split(":")
    decl = "".join(f"static {C_TYPE[c]} a{i};\n" for i, c in enumerate(args))
    gen = " ".join(f"a{i} = {GEN[c].format(i=i)};" for i, c in enumerate(args))
    if args.startswith("ee"):
        gen += " inject_pair (a0, a1);"
    params = ", ".join(C_TYPE[c] for c in args) or "void"
    call = f"((fn_t)(void *)(f)) ({', '.join(f'a{i}' for i in range(len(args)))})"
    return (f"{decl}typedef {C_TYPE[ret]} (*fn_t) ({params});\n"
            f"#define GEN_ARGS() do {{ {gen} }} while (0)\n"
            f"#define CALL(f) {RET[ret].replace('F', call)}\n")


def symtab_map(binary):
    return {(f, n): v for f, n, v, _, _ in symtab(binary)}


def rodata_bytes(binary, addr, n=16):
    """Bytes at addr if it lies in a read-only, non-exec allocated section, else None."""
    for line in sh(["readelf", "-SW", str(binary)])[1].splitlines():
        m = re.match(r"\s*\[\s*\d+\]\s+(\S+)\s+\S+\s+([0-9a-f]+)\s+([0-9a-f]+)\s+([0-9a-f]+)\s+\S+\s+(\S*)", line)
        if not m:
            continue
        name, va, off, size, flags = m.group(1), int(m.group(2), 16), int(m.group(3), 16), int(m.group(4), 16), m.group(5)
        if "A" in flags and "W" not in flags and "X" not in flags and va <= addr < va + size:
            with open(binary, "rb") as fh:
                fh.seek(off + addr - va)
                return list(fh.read(min(n, va + size - addr)))
    return None


def symtab(binary):
    """(file-or-None, name, value, size, type) for FUNC/OBJECT symbols; locals keyed by their source file."""
    out, cur = [], None
    for line in sh(["readelf", "-sW", str(binary)])[1].splitlines():
        f = line.split()
        if len(f) < 8 or not f[0].rstrip(":").isdigit():
            continue
        if f[3] == "FILE":
            cur = f[7]
            continue
        if f[3] in ("FUNC", "OBJECT") and f[6] != "UND":
            out.append((cur if f[4] == "LOCAL" else None, f[7], int(f[1], 16), int(f[2], 0), f[3]))
    return out


def dump(res, out):
    s = json.dumps(res, indent=2)
    if out:
        Path(out).write_text(s)
    if not QUIET:
        print(s)
    return res


if __name__ == "__main__":
    main(*sys.argv[1:])
