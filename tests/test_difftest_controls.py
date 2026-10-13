"""Harness sanity: the original logic must pass, a one-constant mutant must fail.
Needs build/objs (run scripts/build_pilot.py first)."""
import json, re, subprocess, sys
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/evaluation"))
import difftest


def _copy_of_original(tmp, mutate=False):
    src = (ROOT / "third_party/Quake-2/game/g_utils.c").read_text()
    body = re.search(r"float vectoyaw \(vec3_t vec\)\n\{.*?\n\}", src, re.S).group(0)
    body = (body.replace("vectoyaw (vec3_t vec)", "FUN_ctrl (float *vec)")
                .replace("[PITCH]", "[0]").replace("[YAW]", "[1]").replace("M_PI", "3.14159265358979323846"))
    if mutate:
        body = body.replace("yaw += 360", "yaw += 359")
    d = tmp / ("mut" if mutate else "orig")
    d.mkdir()
    (d / "recon.c").write_text("#include <math.h>\n" + body)
    return difftest.main(str(d / "recon.c"), "vectoyaw", "FUN_ctrl")


needs_pilot = pytest.mark.skipif("vectoyaw" not in difftest.CFG["pilot_functions"], reason="pilot config only")


@needs_pilot
def test_original_passes(tmp_path):
    r = _copy_of_original(tmp_path)
    assert all(s["status"] == "pass" for s in r["splits"].values())


@needs_pilot
def test_mutant_fails(tmp_path):
    r = _copy_of_original(tmp_path, mutate=True)
    assert all(s["status"] == "mismatch" for s in r["splits"].values())


FUNCS = difftest.CFG["pilot_functions"]


@pytest.mark.parametrize("name", FUNCS)
def test_driver_self_consistent(name, tmp_path):
    """Original vs itself must pass on both splits: driver is deterministic."""
    exe = tmp_path / "drv"
    rc, err = difftest.link_driver(name, name, None, exe)
    assert rc == 0, err
    for split in ("dev", "heldout"):
        out = subprocess.run([str(exe), split], capture_output=True, text=True, timeout=300)
        r = json.loads(out.stdout.strip().splitlines()[-1])
        assert out.returncode == 0 and r["mismatches"] == 0 and r["cases"] > 1000, (split, r)
        assert r.get("skipped_orig_crash", 0) < r["cases"] // 2, (split, r)   # world generator must be mostly valid
