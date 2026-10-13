#!/usr/bin/env python3
"""Baseline C: one feedback round on top of baseline B.

For each failed B target, agent A gets the original prompt, its previous answer, and
mechanical feedback: compiler errors, or the dev-split mismatch locations from the
differential harness (state offsets only, no original names). Held-out results are
never shown, so held-out pass rate stays an independent check.

Agent: AGENT=agent_a|agent_b, same isolation as single_pass.py. Skips targets that
already have repair1/response.json (from any agent) and stops on a usage limit.
Usage: [AGENT=agent_b] repair.py <run_dir> <original_name> FUN_<addr>
Writes <run_dir>/<FUN>/repair1/{prompt.txt, response.json, recon.c, difftest.json}.
"""
import json, re, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from single_pass import AGENT, OPT, ROOT, call_agent, extract_code, record_failure

FEEDBACK = """{prompt}

Your previous answer was:
<previous_answer>
{previous}
</previous_answer>

It was compiled with `gcc {opt} -c` and run against the original binary on randomized test states.
Result: {problem}
{details}

Fix the reconstruction. Same requirements as above: exactly one ```c fenced code block, same function name."""


def feedback(fun_dir, res):
    """(problem, details) for a failed B attempt, or None if B passed / was untested."""
    if not (fun_dir / "recon.c").exists():
        n = res.get("result", "").count("```c")
        return "format error", f"The answer contained {n} ```c code blocks; exactly one is required."
    d = json.loads((fun_dir / "difftest_baseline_b.json").read_text())
    if not d["compiled"]:   # strip local paths so only the file name remains
        return "compile error", re.sub(r"\S*/recon\.c", "recon.c", d["compile_stderr"])[-3000:]
    if "untested" in d:
        return None
    if not d["linked"]:
        return "link error", re.sub(r"\S*/", "", d["link_stderr"])[-3000:]
    dev = d["splits"].get("dev", {})
    if dev.get("status") == "pass":
        return None
    if dev.get("status") != "mismatch":
        return "runtime failure", f"The program {dev.get('status')} on the dev inputs."
    return ("behaviour mismatch",
            f"{dev['mismatches']} of {dev['cases']} dev test cases differ from the original. "
            "First differing byte per case (edict[i]+off = edict i at byte offset off; "
            "header = return value, error flag, rand() state, edict count, engine-call log):\n" +
            "\n".join(dev["examples"]))


def main(run_dir, name, fun):
    fun_dir = Path(run_dir) / fun
    out = fun_dir / "repair1"
    if (Path(run_dir) / f"STOP_{AGENT}.txt").exists() or (out / "response.json").exists():
        return
    if not (fun_dir / "response.json").exists():
        print(f"{fun}: no first attempt yet, run resume_run.sh first")
        return
    resp_b = json.loads((fun_dir / "response.json").read_text())
    fb = feedback(fun_dir, resp_b)
    if fb is None:
        return
    out.mkdir(exist_ok=True)
    prompt = FEEDBACK.format(opt=OPT, prompt=(fun_dir / "prompt.txt").read_text().rstrip(),
                             previous=resp_b.get("result", "").strip(), problem=fb[0], details=fb[1])
    (out / "prompt.txt").write_text(prompt)
    t0 = time.time()
    try:
        resp = call_agent(prompt)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        record_failure(run_dir, out, fun, e)
        return
    resp["wall_seconds"] = round(time.time() - t0, 2)
    resp["feedback_kind"] = fb[0]
    (out / "response.json").write_text(json.dumps(resp, indent=2))
    code = None if resp.get("isolation_violation") else extract_code(resp.get("result", ""))
    if code is None:
        print(f"{fun}: repair gave no single ```c block")
        return
    (out / "recon.c").write_text(code)
    subprocess.run([sys.executable, str(ROOT / "src/evaluation/difftest.py"), str(out / "recon.c"),
                    name, fun, str(out / "difftest.json")], capture_output=True, cwd=ROOT)
    print(f"{fun}: repaired by {AGENT} ({fb[0]}), ${resp.get('total_cost_usd') or 0:.4f}")


if __name__ == "__main__":
    main(*sys.argv[1:])
