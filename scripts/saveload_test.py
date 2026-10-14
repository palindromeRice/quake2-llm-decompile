#!/usr/bin/env python3
"""Save/load and level-change test for a Quake II game.so (headless, same setup as
playable_demo.py).

Script: play demo1 briefly, pause, save s1, load s1, save s2. Then unpause, change level
demo1 -> demo2 -> demo1 (level-transition save/restore), play on, save s3.
s1 and s2 are not byte-identical even with the original game.so: loading runs a few
server frames, and the engine adds the client address to the saved userinfo. The test
therefore checks: no crash, all three saves written, s1/s2 files of equal size, and both
level changes reached. Differing byte counts are printed for comparison with the original.
Quake II saves store function pointers as offsets inside game.so, so saves are only
loadable by the same build; the round trip is therefore checked within one build.

Usage: saveload_test.py <game.so> <name>    Exit status 0 = all checks pass.
"""
import os, shutil, subprocess, sys
from pathlib import Path

game_so, name = Path(sys.argv[1]).resolve(), sys.argv[2]
T = Path.home() / "tools"
ENGINE, PAK = T / "src/yquake2/release", T / "q2demo/baseq2/pak0.pak"
RUN, HOME = T / "q2run" / name, T / "q2run" / f"home_{name}"
W = lambda n: ";".join(["w10"] * (n // 10))   # console lines max 1024 chars: wait in blocks of 10
CFG = "\n".join([
    "set cl_maxfps 30", "set vid_maxfps 30", f'alias w10 "{";".join(["wait"] * 10)}"',
    f'alias p1 "god; give all; {W(60)}; use chaingun; +attack; {W(40)}; -attack; {W(20)}; p2"',
    f'alias p2 "set paused 1; {W(10)}; save s1; {W(20)}; load s1; {W(120)}; set paused 1; {W(10)}; save s2; {W(20)}; p3"',
    f'alias p3 "set paused 0; {W(30)}; gamemap demo2; {W(150)}; +forward; {W(40)}; -forward; gamemap demo1; {W(150)}; p4"',
    f'alias p4 "+attack; {W(40)}; -attack; {W(20)}; save s3; {W(20)}; quit"',
]) + "\n"


def main():
    shutil.rmtree(RUN, ignore_errors=True)
    shutil.rmtree(HOME, ignore_errors=True)
    (RUN / "baseq2").mkdir(parents=True)
    (HOME / ".local/share").mkdir(parents=True)
    for f in ("quake2", "ref_soft.so"):
        shutil.copy(ENGINE / f, RUN / f)
    os.symlink(PAK, RUN / "baseq2/pak0.pak")
    os.symlink(PAK.parent / "players", RUN / "baseq2/players")
    shutil.copy(game_so, RUN / "baseq2/game.so")
    (RUN / "baseq2/saveload.cfg").write_text(CFG)
    env = {**os.environ, "HOME": str(HOME), "SDL_VIDEODRIVER": "offscreen", "SDL_AUDIODRIVER": "dummy",
           "LD_LIBRARY_PATH": str(T / "sdl2/lib")}
    if (T / "q2run/dbg/segv.so").exists():   # optional crash reporter: prints the faulting function
        env["LD_PRELOAD"] = str(T / "q2run/dbg/segv.so")
    log = RUN.parent / f"{name}.log"
    with open(log, "w") as fh:
        rc = subprocess.run(["./quake2", "-datadir", str(RUN), "+set", "vid_renderer", "soft", "+set", "s_initsound", "0",
                             "+set", "r_mode", "4", "+set", "cheats", "1", "+set", "skill", "1", "+set", "logfile", "2",
                             "+map", "demo1", "+exec", "saveload.cfg", "+p1"],
                            cwd=RUN, env=env, stdout=fh, stderr=subprocess.STDOUT, timeout=300).returncode
    save = HOME / ".local/share/YamagiQ2/baseq2/save"
    s1, s2, s3 = (save / s for s in ("s1", "s2", "s3"))
    have = {s.name: s.exists() for s in (s1, s2, s3)}
    ndiff, sizes_ok = {}, s1.exists() and s2.exists()
    if sizes_ok:
        for f in sorted(p.name for p in s1.iterdir()):
            a, b = (s1 / f).read_bytes(), (s2 / f).read_bytes() if (s2 / f).exists() else b""
            sizes_ok &= len(a) == len(b)
            ndiff[f] = sum(x != y for x, y in zip(a, b))
    con = HOME / ".local/share/YamagiQ2/baseq2/qconsole.log"   # flushed console log (logfile 2)
    text = log.read_text(errors="replace") + (con.read_text(errors="replace") if con.exists() else "")
    levels = [l for l in text.splitlines() if l.startswith(("Map:", "==== InitGame", "Loading game", "Saving game"))]
    maps = [l for l in levels if l.startswith("Map:")]
    level_ok = any(m.startswith("Map: demo2") for m in maps) and maps[-1].startswith("Map: demo1")
    print(f"{name}: engine exit {rc}; saves {have}; s1/s2 same sizes {sizes_ok}; bytes differing {ndiff}; "
          f"level changes {level_ok}")
    print("  " + " | ".join(levels[-12:])[:600])
    if "failed to load game DLL" in text:
        print("  game library failed to load")
    sys.exit(0 if rc == 0 and all(have.values()) and sizes_ok and level_ok and "failed to load game DLL" not in text else 1)


if __name__ == "__main__":
    main()
