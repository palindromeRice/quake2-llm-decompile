#!/usr/bin/env python3
"""Mutation check: how many small bugs does each differential driver catch?

For each target in the current PILOT_CONFIG, makes single-edit mutants of the
ORIGINAL function (relational op, arithmetic op, constant +1, &&/||), builds
each mutant as candidate FUN_mut, and runs the driver. A mutant is "killed"
if any split reports a mismatch, crash or timeout. Survivors may be
equivalent mutants and are listed for manual review.
Needs a build of the same config (scripts/build_pilot.py) first.
Edits inside comments and #if 0 blocks are skipped.
Usage: PILOT_CONFIG=configs/x.json mutation_check.py [max_mutants_per_function [function ...]]
"""
import json, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/evaluation"))
import difftest

difftest.QUIET = True
CFG = difftest.CFG
OPS = [  # (pattern, replacement) applied to one occurrence at a time
    (r"<=", "<"), (r">=", ">"), (r"(?<![<\-])>(?![>=])", ">="), (r"(?<!<)<(?![<=])", "<="),
    (r"&&", "||"), (r"\|\|", "&&"),
    (r"(?<![+=])\+(?![+=])", "-"), (r"(?<![-=>])-(?![-=>])(?=\s)", "+"),
    (r"(?<![\w.])(\d+)(?![\w.x])", None),  # integer constant +1
]


def find_function(src, name):
    # definition = line starting with a type (not indented, not a comment), params on one line
    m = re.search(rf"^(?![ \t/*])[^\n;{{}}()]*\b{name}\s*\([^;{{}}()\n]*\)\s*\n?\{{", src, re.M)
    if not m:
        return None
    depth, i = 0, m.end() - 1
    while True:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
        if depth == 0:
            return m.start(), i


def comment_spans(body):
    return [m.span() for m in re.finditer(r"/\*.*?\*/|//[^\n]*|^#if 0.*?^#endif", body, re.S | re.M)]


def mutants(body):
    dead = comment_spans(body)
    for pat, rep in OPS:
        for m in re.finditer(pat, body):
            if any(a <= m.start() < b for a, b in dead):
                continue
            new = str(int(m.group(1)) + 1) if rep is None else rep
            yield f"{m.group(0)!r}->{new!r}@{m.start()}", body[:m.start()] + new + body[m.end():]


def main(limit=12, *only):
    limit = int(limit)
    srcs = [ROOT / s for s in CFG["sources"] if Path(s).name != "main.c"]
    inc = [f"-I{ROOT / d}" for d in CFG["include_dirs"]]
    report = {}
    for name in only or CFG["pilot_functions"]:
        src_path = next(p for p in srcs if find_function(p.read_text(), name))
        src = src_path.read_text()
        a, b = find_function(src, name)
        header_end = src.index("{", a)
        sig, body = src[a:header_end], src[header_end:b]
        muts = list(mutants(body))
        step = max(1, len(muts) // limit)
        muts = muts[::step][:limit]
        killed, survivors = 0, []
        for label, mbody in muts:
            # original stays intact (other code in the file may refer to it); mutant appended
            mutated = src + "\n" + re.sub(rf"\b{name}\b", "FUN_mut", sig, 1) + mbody + "\n"
            with tempfile.TemporaryDirectory() as td:
                c, o = Path(td) / "mut.c", Path(td) / "mut.o"
                c.write_text(mutated)
                ok = subprocess.run([CFG["cc"], *CFG["cflags"], *inc, "-w", "-c", str(c), "-o", str(o)],
                                    capture_output=True).returncode == 0
                if not ok:
                    continue  # mutant does not compile: not counted
                subprocess.run(["objcopy", "-G", "FUN_mut", str(o)], check=True)
                (Path(td) / "mut").mkdir()
                o2 = Path(td) / "mut" / "recon.o"
                o.rename(o2)
                r = difftest.main(str(o2), name, "FUN_mut")
            if not r["linked"]:
                continue
            if any(s["status"] != "pass" for s in r["splits"].values()):
                killed += 1
            else:
                survivors.append(label)
        total = killed + len(survivors)
        report[name] = {"mutants": total, "killed": killed, "survivors": survivors}
        print(f"{name:20s} killed {killed}/{total}  survivors: {survivors}")
    out = ROOT / "results" / f"mutation_{Path(difftest.CFG_PATH).stem}.json"
    if not only:
        out.write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main(*sys.argv[1:])
