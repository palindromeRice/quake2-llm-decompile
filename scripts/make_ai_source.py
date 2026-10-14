#!/usr/bin/env python3
"""Generate a portable C source tree of the Quake II game module whose functions are
the AI reconstructions, under their real names. Builds with any C compiler (Linux,
macOS), unlike build_ai_gameso.py, which patches x86-64 machine code.

  orig/<file>.c  copy of each original game file. Every replaced function's original
                 definition is renamed <name>__orig (kept for reference, unused) and loses
                 `static`, so the AI version (a separate file) provides <name> to every caller,
                 including function-pointer tables. File-scope objects the AI code reads
                 through Ghidra names (DAT_/PTR_/_UNK_ at evaluation-binary addresses) are
                 bound by assembler aliases in the defining file, so statics need no renaming.
  ai/FUN_<addr>.c  the AI reconstruction with FUN_<addr> tokens renamed to the real
                 function names. Extra global helpers it defines get a file-unique name.
  ai/consts.c    read-only constants the AI code reads by address (bytes copied from the
                 evaluation binary; pointer words bound to the same original symbol).
  build.sh       builds game.so (Linux) or game.dylib (macOS) from the tree.

Which reconstruction is used per function: repair round if it passed both splits, else the
first attempt if it passed, else (with --include-untested) a first attempt that compiled
but has no harness. Everything else keeps the original body.

Needs build/ to hold the run's own build (names map through build/pilot.unstripped).
Usage: make_ai_source.py <run_dir> <out_dir> [--include-untested] [--exclude ingame_failures.json] [--no-relocate]
"""
import json, os, re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN, OUT = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
INCLUDE_UNTESTED = "--include-untested" in sys.argv
RELOCATE = "--no-relocate" not in sys.argv
# functions found broken by in-game testing keep the original body: name -> reason
EXCLUDE = json.loads(Path(sys.argv[sys.argv.index("--exclude") + 1]).read_text()) if "--exclude" in sys.argv else {}
os.environ["PILOT_CONFIG"] = str(next(p for p in (RUN / "_meta").glob("*.json")
                                      if p.stem not in ("build_info", "ground_truth", "extraction_summary")))
sys.path.insert(0, str(ROOT / "src/evaluation"))
import difftest

CFG, EVAL = difftest.CFG, ROOT / "build/pilot.unstripped"
TOK = re.compile(r"\b(?:FUN|_?DAT|_UNK|PTR_\w*?|s_\w*?|u_\w*?)_[0-9a-fA-F]{6,16}\b")


def status(dt):
    if not dt.exists():
        return None
    d = json.loads(dt.read_text())
    if d["linked"] and d["splits"] and all(v.get("status") == "pass" for v in d["splits"].values()):
        return "pass"
    return "untested" if d["compiled"] and "untested" in d else "fail"


def definition_span(src, name):
    """(start, brace) of `<type> name (params)\\n{` at file scope, params possibly multi-line."""
    # search a copy with comments blanked (same length, so positions carry over)
    masked = re.sub(r"/\*.*?\*/|//[^\n]*", lambda m: re.sub(r"[^\n]", " ", m.group(0)), src, flags=re.S)
    m = re.search(rf"^(?![ \t#])[^\n;{{}}()]*?\b{re.escape(name)}\s*\([^;{{}}]*?\)\s*\{{", masked, re.M)
    return (m.start(), m.end() - 1) if m else None


def local_statics(binary):
    """gcc symbol of a function-local static ('fire_frames.0') -> clang's name for it
    ('Weapon_Blaster.fire_frames'), keyed by address, from the binary's DWARF."""
    out, func, tag = {}, None, None
    for line in subprocess.run(["readelf", "--debug-dump=info", binary], capture_output=True, text=True).stdout.splitlines():
        m = re.match(r"\s*<(\d+)><\w+>: Abbrev Number: \d+ \((DW_TAG_\w+)\)", line)
        if m:
            depth, tag, name = int(m.group(1)), m.group(2), None
            if depth <= 1:
                func = None
            continue
        m = re.match(r"\s*<\w+>\s+DW_AT_name\s+:.*?(\w+)\s*$", line)
        if m:
            name = m.group(1)
            if tag == "DW_TAG_subprogram" and depth == 1:
                func = name
        m = re.search(r"DW_OP_addr: ([0-9a-f]+)\)", line)
        if m and tag == "DW_TAG_variable" and depth >= 2 and func and name:
            out[int(m.group(1), 16)] = f"{func}.{name}"
    return out


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    (OUT / "orig").mkdir(parents=True)
    (OUT / "ai").mkdir()
    truth = json.loads((RUN / "_meta/ground_truth.json").read_text())
    evaltab = difftest.symtab(EVAL)
    clang_local = local_statics(EVAL)
    file_of = {}   # function name -> source file basename (statics and globals)
    stems = {Path(x).stem for x in CFG["sources"] if Path(x).name != "main.c"}
    for o in [ROOT / "build/objs" / f"{st}.o" for st in sorted(stems)]:   # globals: defining object
        for line in subprocess.run(["nm", "--defined-only", "-g", str(o)], capture_output=True, text=True).stdout.splitlines():
            if len(line.split()) == 3:
                file_of.setdefault(line.split()[2], o.stem + ".c")
    for f, n, v, sz, t in evaltab:
        if t == "FUNC" and f:
            file_of.setdefault(n, f)

    # choose AI versions
    chosen, manifest = {}, {}
    for name, addr in truth.items():
        d = RUN / f"FUN_{addr}"
        # latest version first: later repair rounds, then the first attempt
        versions = [(d / f"repair{k}", "difftest.json") for k in range(9, 0, -1)] + [(d, "difftest_baseline_b.json")]
        pick = next((("repair" if v != d else "first_attempt", v / "recon.c") for v, t in versions
                     if status(v / t) == "pass"), None)
        if pick is None and INCLUDE_UNTESTED:
            pick = next((("untested", v / "recon.c") for v, t in versions if status(v / t) == "untested"), None)
        if pick and name in EXCLUDE:
            pick = ("excluded_in_game", None)
        if pick and pick[1]:
            chosen[name] = (addr, pick[1])
        manifest[name] = pick[0] if pick else "original"
    name_of_addr = {a: n for n, a in truth.items()}

    # AI files are copied unchanged. The real name becomes an alias of the AI definition
    # (same address, so function-pointer identity holds); FUN_ names the AI code calls that
    # keep the original body get an alias in the original file.
    data_tokens, needs_global, ai_real, fun_refs = set(), set(), {}, set()
    lo = min(v for f, n, v, sz, t in evaltab)
    hi = max(v + sz for f, n, v, sz, t in evaltab)
    relocated = {}   # AI file -> literals rewritten to symbol addresses
    for name, (addr, src) in chosen.items():
        code = src.read_text()
        if RELOCATE:
            # Relocation repair: in a non-PIE binary a symbol address is an immediate the
            # decompiler shows as a plain number. Integer literals equal to an evaluation-binary
            # symbol address (or inside one) become that symbol's address in this build.
            def fix(m):
                if m.group(1) is None:
                    return m.group(0)      # comment or string literal: unchanged
                lit = m.group(1)
                v = int(lit, 16) if lit.lower().startswith("0x") else int(lit)
                if not lo <= v < hi or not any(a <= v < a + max(sz, 1) for f, n, a, sz, t in evaltab):
                    return m.group(0)
                relocated.setdefault(name, []).append(hex(v))
                data_tokens.add(f"q2_abs_{v:08x}")
                return f"((unsigned long)&q2_abs_{v:08x})"
            code = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|(?<![\w.])(0[xX][0-9a-fA-F]+|\d+)[uUlL]*(?![\w.])',
                          fix, code, flags=re.S)
            if name in relocated:
                code = "".join(f"extern char q2_abs_{int(h, 16):08x};\n" for h in sorted(set(relocated[name]))) + code
        for tok in set(TOK.findall(code)):
            (fun_refs if tok.startswith("FUN_") else data_tokens).add(tok)
        code += ("\n#if defined(__APPLE__)\n__asm__(\".globl _%s\\n_%s = _FUN_%s\\n\");\n#else\n"
                 "__asm__(\".globl %s\\n.set %s, FUN_%s\\n\");\n#endif\n") % (name, name, addr, name, name, addr)
        (OUT / "ai" / f"FUN_{addr}.c").write_text(code)
        ai_real[addr] = name
        needs_global.add(name)
    fun_refs -= {f"FUN_{a}" for a, _ in chosen.values()}
    data_tokens |= fun_refs        # bound like data: alias to the original function

    # extra global symbols an AI file defines (helpers, stray copies of globals) get a
    # file-unique name so two AI files, or an AI file and the original, cannot clash
    for addr, name in ai_real.items():
        f = OUT / "ai" / f"FUN_{addr}.c"
        o = OUT / "ai" / f"FUN_{addr}.o"
        subprocess.run([CFG["cc"], "-O0", "-w", "-c", str(f), "-o", str(o)], check=True)
        extra = [l.split()[2] for l in subprocess.run(["nm", "--defined-only", "-g", str(o)], capture_output=True,
                 text=True).stdout.splitlines() if len(l.split()) == 3 and l.split()[2] not in (name, f"FUN_{addr}")]
        o.unlink()
        if extra:
            f.write_text("".join(f"#define {x} {x}__FUN_{addr}\n" for x in extra) + f.read_text())

    # bind data tokens: object symbol (+offset) -> alias in its defining file; else rodata bytes
    aliases = {}      # source basename (or None for globals) -> [(alias, target, offset, target address)]
    consts, relocs = [], 0
    def bind(alias, a):
        hit = next(((f, n, a - v, v) for f, n, v, sz, t in evaltab if v <= a < v + max(sz, 1) and t in ("FUNC", "OBJECT")), None)
        if hit and hit[1] in chosen and chosen[hit[1]][1] is not None:
            # the target function is AI code now: an assembler alias must sit in the file that
            # defines its symbol, so it goes into the AI file, relative to FUN_<addr>
            fun = f"FUN_{chosen[hit[1]][0]}"
            with open(OUT / "ai" / f"{fun}.c", "a") as fh:
                fh.write(f'\n#if defined(__APPLE__)\n__asm__(".globl _{alias}\\n_{alias} = _{fun} + {hit[2]}\\n");\n'
                         f'#else\n__asm__(".globl {alias}\\n.set {alias}, {fun} + {hit[2]}\\n");\n#endif\n')
        elif hit:
            f = hit[0] or file_of.get(hit[1])
            aliases.setdefault(f, []).append((alias, hit[1], hit[2], hit[3]))
        return hit
    for tok in sorted(data_tokens):
        a = int(tok.split("_")[-1], 16)
        if bind(tok, a):
            continue
        b = difftest.rodata_bytes(EVAL, a, 512 if tok.startswith(("s_", "u_")) else 16)
        if b is not None and tok.startswith(("s_", "u_")):
            b = b[:b.index(0) + 1] if 0 in b else b
            b = b + [0] * (-len(b) % 8)
        if b is None:
            raise SystemExit(f"{tok}: no original symbol at 0x{a:x}")
        words = []
        for i in range(0, len(b) - len(b) % 8, 8):
            v = int.from_bytes(bytes(b[i:i + 8]), "little")
            alias = f"q2_reloc_{relocs}"
            if bind(alias, v):
                relocs += 1
                words.append(f"(unsigned long)&{alias}")
            else:
                words.append(f"{v}UL")
        consts.append(f"const unsigned long {tok}[{len(words)}] __attribute__((aligned(16))) = {{{', '.join(words)}}};\n")
    (OUT / "ai/compat.c").write_text(COMPAT)
    (OUT / "ai/consts.c").write_text("".join(f"extern char q2_reloc_{i};\n" for i in range(relocs)) + "".join(consts))

    # original files
    for s in CFG["sources"]:
        if Path(s).name == "main.c":
            continue
        src_path = ROOT / "build/patched" / Path(s).name
        src = (src_path if src_path.exists() else ROOT / s).read_text(errors="replace")
        base = Path(s).name
        for name in [n for n in chosen if file_of.get(n) == base]:
            span = definition_span(src, name)
            if span is None:
                raise SystemExit(f"{base}: definition of {name} not found")
            head = re.sub(r"^static\s+", "", src[span[0]:span[1]])
            proto = head.rstrip() + ";\n"          # real name stays declared for later uses
            head = re.sub(rf"\b{re.escape(name)}\b", f"{name}__orig", head, count=1)
            src = src[:span[0]] + proto + head + src[span[1]:]
        for name in needs_global:     # file-local prototypes/definitions of names the AI code calls
            if file_of.get(name) == base:
                src = re.sub(rf"^static\s+((?:[\w\s\*]+?)\b{re.escape(name)}\s*\()", r"\1", src, flags=re.M)
        renamed = lambda fv: (lambda f, v: f"{f}__orig.{v}" if f in chosen and file_of.get(f) == base else fv)(*fv.split("."))
        lines = [f'Q2_ALIAS({al}, {tgt}, {off})\n' if "." not in tgt else     # function-local static: compilers name it differently
                 f'#if defined(__clang__)\nQ2_ALIAS({al}, {renamed(clang_local[addr])}, {off})\n#else\nQ2_ALIAS({al}, {tgt}, {off})\n#endif\n'
                 for al, tgt, off, addr in aliases.get(base, [])]
        if lines:
            src += ('\n/* AI code reads these objects by evaluation-binary address */\n'
                    '#if defined(__APPLE__)\n#define Q2_ALIAS(n, t, o) __asm__(".globl _" #n "\\n_" #n " = _" #t " + " #o "\\n");\n'
                    '#else\n#define Q2_ALIAS(n, t, o) __asm__(".globl " #n "\\n.set " #n ", " #t " + " #o "\\n");\n#endif\n'
                    + "".join(lines))
        (OUT / "orig" / base).write_text(src)
    leftovers = aliases.get(None, [])
    if leftovers:
        raise SystemExit(f"aliases without a source file: {leftovers[:5]}")

    for h in (ROOT / CFG["include_dirs"][0]).glob("*.h"):
        shutil.copy(h, OUT / "orig" / h.name)      # headers too: the tree builds on its own
    (OUT / "build.sh").write_text(BUILD)
    os.chmod(OUT / "build.sh", 0o755)
    counts = {k: sum(v == k for v in manifest.values()) for k in sorted(set(manifest.values()))}
    (OUT / "manifest.json").write_text(json.dumps({"run": RUN.name, "counts": counts, "relocated_literals": relocated,
                                                   "functions": manifest}, indent=1))
    if relocated:
        print("relocated literals:", json.dumps(relocated))
    print(json.dumps(counts))


COMPAT = r'''/* glibc-internal names some AI code calls directly, because they are what the Linux
   evaluation binary calls. Other C libraries (macOS) lack them. */
#if !defined(__GLIBC__)
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
int __isoc99_sscanf(const char *s, const char *fmt, ...)
{
    va_list ap;
    int r;
    va_start(ap, fmt);
    r = vsscanf(s, fmt, ap);
    va_end(ap);
    return r;
}
void __assert_fail(const char *expr, const char *file, unsigned int line, const char *func)
{
    fprintf(stderr, "%s:%u: %s: assertion '%s' failed\n", file, line, func, expr);
    abort();
}
#endif
'''

BUILD = r'''#!/bin/sh
# Build the AI game module. Usage: ./build.sh   (CC and TARGET_OS may be overridden)
# Output: game.so (Linux) or game.dylib (macOS).
set -e
cd "$(dirname "$0")"
CC="${CC:-cc}"
# 1997 C (implicit int etc.) is an error in newer compilers: keep it a warning
CFLAGS="-O0 -g -fPIC -fno-strict-aliasing -w -Iorig -Wno-error=implicit-int -Wno-error=implicit-function-declaration -Wno-error=int-conversion -Wno-error=incompatible-pointer-types"
mkdir -p obj
for f in orig/*.c ai/*.c; do
  $CC $CFLAGS -c "$f" -o "obj/$(basename "$f" .c).o"
done
if [ "${TARGET_OS:-$(uname)}" = Darwin ]; then
  $CC -dynamiclib -undefined dynamic_lookup -o game.dylib obj/*.o
else
  $CC -shared -Wl,-z,defs -o game.so obj/*.o -lm   # fail on any unresolved symbol
fi
echo built
'''

if __name__ == "__main__":
    main()
