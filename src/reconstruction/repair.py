#!/usr/bin/env python3
"""Baseline C: one feedback round on top of baseline B.

For each failed B target, agent A gets the original prompt, its previous answer, and
mechanical feedback: compiler errors, or the dev-split mismatch locations from the
differential harness (state offsets only, no original names). Held-out results are
never shown, so held-out pass rate stays an independent check.

Agent: AGENT=agent_a|agent_b, same isolation as single_pass.py. Skips targets that
already have repair1/response.json (from any agent) and stops on a usage limit.
Later rounds (ROUND=2, ...) build on the previous round's answer and its test result.
In-game feedback: experiments/playable/ingame_feedback.json maps a function name to what was
observed when the game ran it (e.g. where it crashed). It is used for functions the harness
cannot call, and only describes behaviour, never the original source.
Usage: [AGENT=agent_b] [ROUND=1] repair.py <run_dir> <original_name> FUN_<addr>
Writes <run_dir>/<FUN>/repair<ROUND>/{prompt.txt, response.json, recon.c, difftest.json}.
"""
import json, os, re, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from single_pass import AGENT, OPT, ROOT, call_agent, extract_code, record_failure

ROUND = int(os.environ.get("ROUND", "1"))
INGAME = ROOT / "experiments/playable/ingame_feedback.json"

FEEDBACK = """{prompt}

Your previous answer was:
<previous_answer>
{previous}
</previous_answer>

It was compiled with `gcc {opt} -c` and run against the original binary on randomized test states.
Result: {problem}
{details}

Fix the reconstruction. Same requirements as above: exactly one ```c fenced code block, same function name."""


def feedback(prev_dir, res, test_json, name):
    """(problem, details) for a failed previous attempt, or None if it passed / was untested."""
    if not (prev_dir / "recon.c").exists():
        n = res.get("result", "").count("```c")
        return "format error", f"The answer contained {n} ```c code blocks; exactly one is required."
    d = json.loads((prev_dir / test_json).read_text())
    ingame = json.loads(INGAME.read_text()).get(name) if INGAME.exists() else None
    if ingame and "untested" in d:
        return "in-game failure", ingame
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
    out = fun_dir / f"repair{ROUND}"
    prev, test_json = (fun_dir, "difftest_baseline_b.json") if ROUND == 1 else (fun_dir / f"repair{ROUND - 1}", "difftest.json")
    if (Path(run_dir) / f"STOP_{AGENT}.txt").exists() or (out / "response.json").exists():
        return
    if not (prev / "response.json").exists():
        if ROUND == 1:
            print(f"{fun}: no first attempt yet, run resume_run.sh first")
        return
    resp_b = json.loads((prev / "response.json").read_text())
    fb = feedback(prev, resp_b, test_json, name)
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
