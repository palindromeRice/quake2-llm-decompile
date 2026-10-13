#!/usr/bin/env python3
"""Baseline B: one model call per function, Ghidra-derived inputs only.

AGENT=agent_a (default): `agent_a -p` from an empty temp dir, all tools disabled,
user/project settings (hooks, project instruction files) not loaded, fixed system prompt.
AGENT=agent_b: `agent_b exec` from an empty temp dir, read-only sandbox, clean
AGENT_B_HOME (no AGENTS.md, memories or skills; login shared by symlink),
web search off. Any command execution is an isolation violation: the answer
is kept for the record but not used.

A target counts as done once it has response.json (whichever agent wrote it);
failed calls leave error_<agent>.txt and are retried by resume_run.sh.
A usage/session limit writes <run_dir>/STOP_<agent>.txt; later calls of that
agent in the run are skipped until resume_run.sh clears it.

Usage: [AGENT=agent_b] single_pass.py <run_dir> FUN_<addr> [FUN_<addr> ...]
Writes <run_dir>/<FUN>/{prompt.txt, response.json, recon.c}.
"""
import json, os, re, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "build/agent_inputs"
CFG = json.loads((ROOT / os.environ.get("PILOT_CONFIG", "configs/pilot_O0.json")).read_text())
AGENT = os.environ.get("AGENT", "agent_a")
MODEL = CFG["agent_a_model"] if AGENT == "agent_a" else os.environ.get("AGENT_B_MODEL", "agent-b-model")
AGENT_B_HOME = Path(os.environ.get("AGENT_B_HOME", Path.home() / ".agent-b-home"))
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


def call_agent_a(prompt):
    with tempfile.TemporaryDirectory() as empty:
        p = subprocess.run(
            ["agent_a", "-p", "--model", MODEL, "--output-format", "json",
             "--tools", "", "--setting-sources", "", "--no-session-persistence",
             "--system-prompt", SYSTEM],
            input=prompt, capture_output=True, text=True, cwd=empty, timeout=600)
    if p.returncode:
        raise RuntimeError(f"rc={p.returncode} stdout={p.stdout[-1500:]} stderr={p.stderr[-1500:]}")
    return json.loads(p.stdout)


def call_agent_b(prompt):
    AGENT_B_HOME.mkdir(exist_ok=True)
    auth = AGENT_B_HOME / "auth.json"
    if not auth.exists():
        auth.symlink_to(Path.home() / ".agent_b/auth.json")
    with tempfile.TemporaryDirectory() as empty:
        out = Path(empty) / ".last_message"
        p = subprocess.run(
            ["agent_b", "exec", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
             "-s", "read-only", "-C", empty, "-m", MODEL, "-c", "features.memories=false",
             "-c", "web_search=disabled", "--json", "-o", str(out), "-"],
            input=SYSTEM + "\n\n" + prompt, capture_output=True, text=True, timeout=900,
            env={**os.environ, "AGENT_B_HOME": str(AGENT_B_HOME)})
        events = [json.loads(l) for l in p.stdout.splitlines() if l.startswith("{")]
        if p.returncode or not out.exists():
            raise RuntimeError(f"rc={p.returncode} events={json.dumps(events[-3:])[-1500:]} stderr={p.stderr[-1500:]}")
        result = out.read_text()
    items = [e.get("item", {}).get("type") for e in events if e.get("type") == "item.completed"]
    usage = next((e.get("usage", {}) for e in events if e.get("type") == "turn.completed"), {})
    version = subprocess.run(["agent_b", "--version"], capture_output=True, text=True).stdout.strip()
    return {"result": result, "usage": usage, "total_cost_usd": None, "cli_version": version,
            "item_types": items,
            "isolation_violation": any(t not in ("agent_message", "reasoning") for t in items)}


def call_agent(prompt):
    resp = call_agent_a(prompt) if AGENT == "agent_a" else call_agent_b(prompt)
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
