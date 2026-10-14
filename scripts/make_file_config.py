#!/usr/bin/env python3
"""Make a stateful config covering every testable function in whole game files.

Usage: make_file_config.py <out.json> <opt e.g. O0> <game file> [<game file> ...]
Signature codes are derived from the source prototypes (evaluation side).
Functions with unsupported parameter/return types are reconstructed and
compile-checked only ("compile_only"). Names defined in more than one game file
are excluded ("skipped"): their ground-truth address would be ambiguous.
Pass "ALL" as the only file to cover every game/*.c.
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / "third_party/Quake-2/game"
RET = {"void": "n", "int": "i", "qboolean": "b", "float": "f", "vec_t": "f", "edict_t *": "e", "char *": "s",
       "short": "h", "gitem_t *": "G"}
DEF = re.compile(r"^(static\s+)?([A-Za-z_][\w \t]*?\*?)\s*\b(\w+)\s*\(([^;{}()]*)\)\s*\n\{", re.M)


def param_code(p):
    p = " ".join(p.split())
    if p in ("", "void"):
        return ""
    m = re.match(r"^(const\s+)?(\w+)\s*(\**)\s*(\w+)$", p)
    if not m:
        return None
    t, star, name = m.group(2), m.group(3), m.group(4)
    if t == "int" and name == "fieldofs":
        return "o"
    return {("edict_t", "*"): "e", ("float", ""): "f", ("vec_t", ""): "f", ("int", ""): "i", ("qboolean", ""): "b",
            ("vec3_t", ""): "v", ("float", "*"): "v", ("char", "*"): "s", ("short", ""): "h",
            ("gitem_t", "*"): "g", ("cplane_t", "*"): "p", ("csurface_t", "*"): "u", ("gclient_t", "*"): "l",
            ("usercmd_t", "*"): "U", ("moveinfo_t", "*"): "m"}.get((t, star))


def definitions(path):
    for m in DEF.finditer(path.read_text(errors="replace")):
        ret = " ".join(m.group(2).split()).replace(" *", " *")
        ret = re.sub(r"\s*\*$", " *", ret)
        yield m.group(3), ret, m.group(4)


def main(out, opt, *files):
    counts = {}
    for f in GAME.glob("*.c"):
        for name, _, _ in definitions(f):
            counts[name] = counts.get(name, 0) + 1
    stateful, skipped, compile_only = {}, {}, {}
    if files == ("ALL",):
        files = tuple(sorted(f.name for f in GAME.glob("*.c")))
    for fname in files:
        for name, ret, params in definitions(GAME / fname):
            r = RET.get(ret)
            codes = [param_code(p) for p in params.split(",")] if params.strip() not in ("", "void") else []
            if counts[name] > 1:
                skipped[name] = "name defined in several game files"
            elif r is None or None in codes:
                compile_only[name] = f"unsupported signature: {ret} ({params.strip()})"
            else:
                stateful[name] = {"sig": f"{r}:{''.join(codes)}", "file": fname}
    base = json.loads((ROOT / f"configs/stateful_{opt}.json").read_text())
    base.update({"_comment": f"EVALUATION-SIDE config. All functions of {len(files)} game files, -{opt}.",
                 "pilot_functions": list(stateful) + list(compile_only),
                 "reconstruct": list(stateful) + list(compile_only),
                 "stateful": stateful, "compile_only": compile_only, "skipped": skipped})
    Path(out).write_text(json.dumps(base, indent=2) + "\n")
    print(f"{len(stateful)} testable, {len(compile_only)} compile-only, {len(skipped)} skipped")


if __name__ == "__main__":
    main(*sys.argv[1:])
