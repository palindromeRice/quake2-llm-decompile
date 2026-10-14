#!/usr/bin/env python3
"""Check a macOS build of the AI source tree without a Mac: every name alias in the
Mach-O objects points at the right address, GetGameAPI is exported, and the undefined
symbols left for the dynamic loader are listed (they should all be C library functions).

Usage: macho_check.py <ai_source tree built with TARGET_OS=Darwin>
"""
import re, struct, sys
from pathlib import Path
tree = Path(sys.argv[1])

def symtab(p):
    d = p.read_bytes(); magic, cpu, _, _, ncmds = struct.unpack_from("<5I", d, 0); assert magic == 0xfeedfacf, p
    off, syms = 32, {}
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<2I", d, off)
        if cmd == 2:
            symoff, nsyms, stroff, _ = struct.unpack_from("<4I", d, off + 8)
            for i in range(nsyms):
                strx, typ, sect, desc, val = struct.unpack_from("<IBBHQ", d, symoff + 16 * i)
                name = d[stroff + strx:d.index(b"\0", stroff + strx)].decode()
                if typ & 0x0e == 0x0e: syms[name[1:]] = (sect, val, bool(typ & 1))  # drop Mach-O '_' prefix
        off += size
    return cpu, syms

cpu, lib = symtab(tree / "game.dylib")
print("dylib cpu", hex(cpu), "exports GetGameAPI", lib.get("GetGameAPI", (0, 0, 0))[2])
bad = ok = 0
for f in sorted((tree / "ai").glob("FUN_*.c")) + sorted((tree / "orig").glob("*.c")):
    pairs = [(n, t, 0) for n, t in re.findall(r'\.globl _(\w+)\\n_\w+ = _(\w+)\\n', f.read_text())]
    txt = re.sub(r"#if defined\(__clang__\)\n(.*?\n)#else\n.*?\n#endif\n", r"\1", f.read_text())  # clang branch
    pairs += [(n, t, int(o, 0)) for n, t, o in re.findall(r"^Q2_ALIAS\((\w+), ([\w.]+), (\w+)\)", txt, re.M)]
    if not pairs: continue
    _, s = symtab(tree / "obj" / (f.stem + ".o"))
    for n, t, o in pairs:
        good = n in s and t in s and s[n][:2] == (s[t][0], s[t][1] + o) and s[n][2]   # same section, address, exported
        ok += good; bad += not good
        if not good: print("wrong", f.name, n, t, o, s.get(n), s.get(t))
        # final library: exported alias keeps its offset relative to the real function/object
        elif s[t][2] and lib[n][1] != lib[t][1] + o: bad += 1; print("moved in dylib", n, t)
print("aliases ok", ok, "wrong", bad)

und = []
d = (tree / "game.dylib").read_bytes(); off = 32
for _ in range(struct.unpack_from("<5I", d, 0)[4]):
    cmd, size = struct.unpack_from("<2I", d, off)
    if cmd == 2:
        so, ns, st, _ = struct.unpack_from("<4I", d, off + 8)
        for i in range(ns):
            sx, t = struct.unpack_from("<IB", d, so + 16 * i)
            if t & 0x0e == 0 and t & 1: und.append(d[st + sx:d.index(b"\0", st + sx)].decode())
    off += size
print(len(und), "undefined:", " ".join(sorted(und)))
