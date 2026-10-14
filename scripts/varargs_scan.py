#!/usr/bin/env python3
"""Find AI code that calls a variadic function through a non-variadic type.

On x86-64 Linux such a call usually still works; on Apple arm64 variadic arguments go
on the stack instead of registers, so the callee reads garbage. Flags each statement
that mentions a variadic target (engine print/error slots in the game_import table,
the game's own variadic helpers, libc printf family) and gives it a function type
without "...", directly or through a typedef. Output is a review list, not a proof.

Usage: varargs_scan.py <ai_source>/ai <eval binary>
"""
import re, subprocess, sys
from pathlib import Path

ai, binary = Path(sys.argv[1]), sys.argv[2]
syms = {l.split()[2]: int(l.split()[0], 16) for l in subprocess.run(["nm", binary], capture_output=True, text=True).stdout.splitlines() if len(l.split()) == 3}
gi = syms["gi"]
TARGETS = {f"DAT_{gi + 8 * i:08x}": n for i, n in [(0, "gi.bprintf"), (1, "gi.dprintf"), (2, "gi.cprintf"), (3, "gi.centerprintf"), (7, "gi.error")]}
TARGETS.update({f"FUN_{syms[n]:08x}": n for n in ("Sys_Error", "Com_Printf", "va", "Com_sprintf")})
TARGETS.update({n: n for n in ("printf", "sprintf", "snprintf", "fprintf", "sscanf", "__isoc99_sscanf")})
FNTYPE = re.compile(r"\(\s*\*\s*\w*\s*\)\s*\(([^()]*)\)")       # (*name)(params) / (*)(params)

hits = []
for f in sorted(ai.glob("*.c")):
    src = re.sub(r"/\*.*?\*/|//[^\n]*", "", f.read_text(errors="replace"), flags=re.S)
    tdefs = {m.group(1): "..." in m.group(2) for m in re.finditer(r"typedef[^;(]*\(\s*\*\s*(\w+)\s*\)\s*\(([^()]*)\)", src)}
    for st in re.split(r"[;{}]", src):
        for sym, name in TARGETS.items():
            if not re.search(rf"\b{sym}\b", st):
                continue
            bad = [p for p in FNTYPE.findall(st) if "..." not in p]
            bad += [t for t, ok in tdefs.items() if not ok and re.search(rf"\b{t}\b", st)]
            if re.match(rf"\s*(extern\s+|static\s+)?(const\s+)?(void|int|char|long|unsigned|float|double)\b[\w\s\*]*\b{sym}\s*\(([^()]*)\)\s*$", st) and "..." not in st:
                bad.append("plain prototype")   # e.g. extern void sprintf(char*, char*, int)
            if bad:
                hits.append((f.name, name, " ".join(st.split())[:160]))
for h in hits:
    print(*h, sep="  |  ")
print(f"{len(hits)} suspicious statements in {len({h[0] for h in hits})} files")
