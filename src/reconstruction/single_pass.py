#!/usr/bin/env python3
"""Baseline B: one agent A call per function, Ghidra-derived inputs only.

agent A runs via `agent_a -p` from an empty temp dir with all tools disabled,
user/project settings (hooks, project instruction files) not loaded, and a fixed system
prompt, so it cannot read the original source tree.

Usage: single_pass.py <run_dir> FUN_<addr> [FUN_<addr> ...]
Writes <run_dir>/<FUN>/{prompt.txt, response.json, recon.c}.
"""
import json, re, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "experiments/pilot/agent_inputs"
MODEL = json.loads((ROOT / "configs/pilot.json").read_text())["agent_a_model"]

SYSTEM = ("You are a reverse engineer. You reconstruct readable, compilable C source "
          "from decompiler output. You have no tools; answer from the given material only.")

TEMPLATE = """Reconstruct the C source of one function from a stripped x86-64 Linux ELF executable.

Build facts: compiled with GCC 13, -O0, System V AMD64 ABI, `float` is 32-bit, `int` is 32-bit, pointers 64-bit.

Requirements:
- Output exactly one ```c fenced code block containing a self-contained translation unit.
- Define the function with the exact name `{name}` and external linkage. Do not write main().
- Use only standard C types and standard headers (math.h, string.h, ctype.h, stdlib.h, stddef.h, stdint.h).
- Preserve behaviour exactly, including float vs double precision of intermediate operations and integer truncation.
- Prefer readable code: meaningful local names, real control flow instead of gotos where possible.
- If the function calls other non-library functions, declare them as extern with the name given below.

Ghidra recovered signature:
{signature}

Callees (Ghidra name @ address :: signature):
{callees}

Callers:
{callers}

Constants read from initialized non-code memory (address: 8 bytes read as little-endian u64, plus float/double views of the same bytes):
{data}

Ghidra decompiler output:
```c
{pseudocode}
```

Disassembly:
```
{disassembly}
```
"""


def build_prompt(rec):
    return TEMPLATE.format(
        name=rec["name"], signature=rec["signature"],
        callees="\n".join(rec["callees"]) or "(none)",
        callers="\n".join(rec["callers"]) or "(none recovered)",
        data="\n".join(f"{a}: {v}" for a, v in rec.get("referenced_data", {}).items()) or "(none)",
        pseudocode=rec["pseudocode"].strip(),
        disassembly="\n".join(rec["disassembly"]))


def call_agent_a(prompt):
    with tempfile.TemporaryDirectory() as empty:
        p = subprocess.run(
            ["agent_a", "-p", "--model", MODEL, "--output-format", "json",
             "--tools", "", "--setting-sources", "", "--no-session-persistence",
             "--system-prompt", SYSTEM],
            input=prompt, capture_output=True, text=True, cwd=empty, timeout=600)
    if p.returncode:
        raise RuntimeError(p.stderr[-2000:])
    return json.loads(p.stdout)


def extract_code(text):
    blocks = re.findall(r"```c\s*\n(.*?)```", text, re.S)
    return blocks[0] if len(blocks) == 1 else None


def main(run_dir, *funs):
    for fun in funs:
        rec = json.loads((AGENT / f"{fun}.json").read_text())
        out = Path(run_dir) / fun
        out.mkdir(parents=True, exist_ok=True)
        prompt = build_prompt(rec)
        (out / "prompt.txt").write_text(prompt)
        t0 = time.time()
        resp = call_agent_a(prompt)
        resp["wall_seconds"] = round(time.time() - t0, 2)
        (out / "response.json").write_text(json.dumps(resp, indent=2))
        code = extract_code(resp.get("result", ""))
        if code is None:
            print(f"{fun}: no single ```c block in response")
            continue
        (out / "recon.c").write_text(code)
        print(f"{fun}: ok, ${resp.get('total_cost_usd', 0):.4f}, {resp['wall_seconds']}s")


if __name__ == "__main__":
    main(*sys.argv[1:])
