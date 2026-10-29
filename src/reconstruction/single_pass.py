#!/usr/bin/env python3
"""Baseline B: one model call per function, Ghidra-derived inputs only.

The model is reached through AGENT_CMD, any command that reads the prompt on
stdin and prints the answer on stdout, either as plain text or as a JSON object
with a "result" field (optional: "usage", "total_cost_usd", "isolation_violation").
It runs from an empty temp dir with AGENT_MODEL in its environment. The wrapper
must give the model no tools, no web access and no user or project settings;
a reported isolation violation keeps the answer for the record but not for use.
AGENT is the label stored with each answer (agent_a, agent_b, ...).

A target counts as done once it has response.json (whichever agent wrote it);
failed calls leave error_<agent>.txt and are retried by resume_run.sh.
A usage/session limit writes <run_dir>/STOP_<agent>.txt; later calls of that
agent in the run are skipped until resume_run.sh clears it.

Usage: AGENT_CMD=<cmd> [AGENT=agent_b] single_pass.py <run_dir> FUN_<addr> [FUN_<addr> ...]
Writes <run_dir>/<FUN>/{prompt.txt, response.json, recon.c}.
"""
import json, os, re, shlex, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "build/agent_inputs"
CFG = json.loads((ROOT / os.environ.get("PILOT_CONFIG", "configs/pilot_O0.json")).read_text())
AGENT = os.environ.get("AGENT", "agent_a")
MODEL = os.environ.get("AGENT_MODEL", CFG["agent_model"])
AGENT_CMD = shlex.split(os.environ.get("AGENT_CMD", ""))
LIMIT_RE = re.compile(r"session limit|usage limit|rate limit|quota|limit reached|too many requests", re.I)
OPT = next(f for f in CFG["cflags"] if f.startswith("-O"))

# v1: pilot/control runs up to 20261012-232321. v2: adds the extern-globals rule.
# v2.1: optimisation level taken from the config (v1/v2 said -O0 even for -O2 builds).
PROMPT_VERSION = "v2.1"
SYSTEM = ("You are a reverse engineer. You reconstruct readable, compilable C source "
          "from decompiler output. You have no tools; answer from the given material only.")

TEMPLATE = """Reconstruct the C source of one function from a stripped x86-64 Linux ELF executable.

Build facts: compiled with GCC 13, {opt}, System V AMD64 ABI, `float` is 32-bit, `int` is 32-bit, pointers 64-bit.

Requirements:
- Output exactly one ```c fenced code block containing a self-contained translation unit.
- Define the function with the exact name `{name}` and external linkage. Do not write main().
- Use only standard C types and standard headers (math.h, string.h, ctype.h, stdlib.h, stddef.h, stdint.h).
- Preserve behaviour exactly, including float vs double precision of intermediate operations and integer truncation.
- Prefer readable code: meaningful local names, real control flow instead of gotos where possible.
- If the function calls other non-library functions, declare them as extern with the name given below.
- Refer to global variables by the names the decompiler output uses (e.g. DAT_xxxxxxxx) and declare them `extern`; never define them. They are linked to the program's real globals.

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
        name=rec["name"], opt=OPT, signature=rec["signature"],
        callees="\n".join(rec["callees"]) or "(none)",
        callers="\n".join(rec["callers"]) or "(none recovered)",
        data="\n".join(f"{a}: {v}" for a, v in rec.get("referenced_data", {}).items()) or "(none)",
        pseudocode=rec["pseudocode"].strip(),
        disassembly="\n".join(rec["disassembly"]))


def call_agent(prompt):
    if not AGENT_CMD:
        raise RuntimeError("AGENT_CMD is not set")
    with tempfile.TemporaryDirectory() as empty:
        p = subprocess.run(AGENT_CMD, input=SYSTEM + "\n\n" + prompt, capture_output=True, text=True,
                           cwd=empty, timeout=900, env={**os.environ, "AGENT_MODEL": MODEL})
    if p.returncode:
        raise RuntimeError(f"rc={p.returncode} stdout={p.stdout[-1500:]} stderr={p.stderr[-1500:]}")
    try:
        resp = json.loads(p.stdout)
    except json.JSONDecodeError:
        resp = None
    if not isinstance(resp, dict) or "result" not in resp:
        resp = {"result": p.stdout}
    resp.update(agent=AGENT, model=MODEL)
    return resp


def record_failure(run_dir, out, fun, e):
    msg = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {e}\n"
    with open(out / f"error_{AGENT}.txt", "a") as fh:
        fh.write(msg)
    if LIMIT_RE.search(str(e)):
        (Path(run_dir) / f"STOP_{AGENT}.txt").write_text(msg)
        print(f"{fun}: {AGENT} usage limit hit, stopping this agent for the run")
    else:
        print(f"{fun}: reconstruction call failed")


def extract_code(text):
    blocks = re.findall(r"```c\s*\n(.*?)```", text, re.S)
    return blocks[0] if len(blocks) == 1 else None


def main(run_dir, *funs):
    cap = float(os.environ.get("COST_CAP_USD", "inf"))
    for fun in funs:
        if (Path(run_dir) / f"STOP_{AGENT}.txt").exists():
            print(f"{fun}: skipped, {AGENT} usage limit reached earlier in this run")
            continue
        if (Path(run_dir) / fun / "response.json").exists():
            print(f"{fun}: skipped, already has a response")
            continue
        spent = sum(json.loads(r.read_text()).get("total_cost_usd") or 0 for r in Path(run_dir).glob("FUN_*/response.json"))
        if spent >= cap:   # ponytail: racy under parallel jobs, may overshoot by JOBS calls
            print(f"{fun}: skipped, cost cap ${cap} reached (spent ${spent:.2f})")
            continue
        rec = json.loads((INPUTS / f"{fun}.json").read_text())
        out = Path(run_dir) / fun
        out.mkdir(parents=True, exist_ok=True)
        prompt = build_prompt(rec)
        (out / "prompt.txt").write_text(prompt)
        t0 = time.time()
        try:
            resp = call_agent(prompt)
        except (RuntimeError, subprocess.TimeoutExpired) as e:   # e.g. usage limit: keep the evidence, move on
            record_failure(run_dir, out, fun, e)
            continue
        resp["wall_seconds"] = round(time.time() - t0, 2)
        resp["prompt_version"] = PROMPT_VERSION
        (out / "response.json").write_text(json.dumps(resp, indent=2))
        code = extract_code(resp.get("result", ""))
        if resp.get("isolation_violation"):
            print(f"{fun}: isolation violation (agent ran tools {resp['item_types']}), answer not used")
            continue
        if code is None:
            print(f"{fun}: no single ```c block in response")
            continue
        (out / "recon.c").write_text(code)
        print(f"{fun}: ok ({AGENT}), ${resp.get('total_cost_usd') or 0:.4f}, {resp['wall_seconds']}s")


if __name__ == "__main__":
    main(*sys.argv[1:])
