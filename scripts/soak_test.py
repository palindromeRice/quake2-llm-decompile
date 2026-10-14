#!/usr/bin/env python3
"""Soak test: play every demo map for several minutes with a given game.so (headless,
same setup as playable_demo.py).

Per map: god mode, all weapons, then a repeating loop of running, strafing, turning,
jumping, firing and switching through every weapon, with a save every loop and a
screenshot about every 5 seconds. Maps run back to back in one engine process
(demo1 -> demo2 -> demo3). Passes when the engine exits normally after the last map,
every map was reached, and the console shows no game error.

Usage: soak_test.py <game.so> <name> [--minutes 3]
Writes ~/tools/q2run/<name>/ and ~/tools/q2run/video/<name>.mp4 (screenshots at 10 fps).
"""
import os, re, shutil, subprocess, sys, time
from pathlib import Path

game_so, name = Path(sys.argv[1]).resolve(), sys.argv[2]
MINUTES = float(sys.argv[sys.argv.index("--minutes") + 1]) if "--minutes" in sys.argv else 3
MAPS = ["demo1", "demo2", "demo3"]
T = Path.home() / "tools"
ENGINE, PAK = T / "src/yquake2/release", T / "q2demo/baseq2/pak0.pak"
RUN, HOME = T / "q2run" / name, T / "q2run" / f"home_{name}"
FPS = 30
WEAPONS = ["blaster", "shotgun", "super shotgun", "machinegun", "chaingun", "grenade launcher",
           "rocket launcher", "hyperblaster", "railgun", "bfg10k", "grenades"]
# one loop = 150 waits: run, strafe, turn, jump, fire; screenshot at the end. Console waits
# run faster than cl_maxfps here (measured about 2.5 s per loop), so the script measures real
# time per map while it runs and reports that, not the planned time.
SEC_PER_LOOP = 2.5
LOOP = ["+forward", "w10", "w10", "+attack", "w10", "-attack", "+left", "w10", "-left", "+moveleft", "w10",
        "-moveleft", "+moveup", "w5", "-moveup", "w5", "+attack", "+right", "w10", "w10", "-right", "-attack",
        "-forward", "+back", "w10", "-back", "+moveright", "w10", "-moveright", "+forward", "w10", "w10",
        "+attack", "w10", "w10", "-attack", "-forward", "+lookup", "w5", "-lookup", "+lookdown", "w5", "-lookdown",
        "w10", "shot"]


def cfg():
    loops = max(1, int(MINUTES * 60 / SEC_PER_LOOP))
    lines = [f"set cl_maxfps {FPS}", f"set vid_maxfps {FPS}", 'alias shot "screenshot"',
             f'alias w5 "{";".join(["wait"] * 5)}"', f'alias w10 "{";".join(["wait"] * 10)}"',
             f'alias loop "{"; ".join(LOOP)}"']
    for m, nxt in zip(MAPS, MAPS[1:] + [None]):
        lines.append(f'alias {m}_start "god; give all; w10; {m}_0"')
        for i in range(loops):          # one alias per loop: aliases cannot count
            step = f"use {WEAPONS[i % len(WEAPONS)]}; loop; save soak_{m}"
            after = f"{m}_{i + 1}" if i + 1 < loops else (f"map {nxt}; w10; w10; w10; {nxt}_start" if nxt else "quit")
            lines.append(f'alias {m}_{i} "{step}; {after}"')
    return "\n".join(lines) + "\n"


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
    (RUN / "baseq2/soak.cfg").write_text(cfg())
    env = {**os.environ, "HOME": str(HOME), "SDL_VIDEODRIVER": "offscreen", "SDL_AUDIODRIVER": "dummy",
           "LD_LIBRARY_PATH": str(T / "sdl2/lib")}
    if (T / "q2run/dbg/segv.so").exists():   # optional crash reporter: prints the faulting function
        env["LD_PRELOAD"] = str(T / "q2run/dbg/segv.so")
    log = RUN.parent / f"{name}.log"
    timeout = int(MINUTES * 60 * len(MAPS) * 2 + 300)
    con = HOME / ".local/share/YamagiQ2/baseq2/qconsole.log"
    start, seen = time.time(), {}
    with open(log, "w") as fh:
        p = subprocess.Popen(["./quake2", "-datadir", str(RUN), "+set", "vid_renderer", "soft", "+set", "s_initsound", "0",
                                 "+set", "r_mode", "4", "+set", "cheats", "1", "+set", "skill", "1", "+set", "logfile", "2",
                                 "+map", MAPS[0], "+exec", "soak.cfg", f"+{MAPS[0]}_start"],
                             cwd=RUN, env=env, stdout=fh, stderr=subprocess.STDOUT)
        while p.poll() is None and time.time() - start < timeout:   # note when each map starts
            time.sleep(1)
            for m in re.findall(r"^Map: (demo\d)", con.read_text(errors="replace") if con.exists() else "", re.M):
                seen.setdefault(m, time.time() - start)
        if p.poll() is None:
            p.kill()
        rc = p.wait() if time.time() - start < timeout else "timeout"
    seen["end"] = time.time() - start
    marks = list(seen.values())
    minutes = {m: round((b - a) / 60, 1) for m, a, b in zip(seen, marks, marks[1:])}
    text = log.read_text(errors="replace") + (con.read_text(errors="replace") if con.exists() else "")
    reached = [m for m in MAPS if re.search(rf"^Map: {m}", text, re.M)]
    errors = sorted({l.strip() for l in text.splitlines() if re.search(r"error|segmentation|signal \d+|undefined symbol", l, re.I)
                     and "Error during initialization" not in l})
    shots = HOME / ".local/share/YamagiQ2/baseq2/scrnshot"
    n = len(list(shots.glob("*.tga")))
    video = T / "q2run/video" / f"{name}.mp4"
    video.parent.mkdir(exist_ok=True)
    if n:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", "10", "-i", str(shots / "q2_%04d.tga"),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    saves = sorted(p.name for p in (HOME / ".local/share/YamagiQ2/baseq2/save").glob("soak_*"))
    print(f"{name}: engine exit {rc}; maps reached {reached}; real minutes per map {minutes}; {n} screenshots; saves {saves}; video {video}")
    for e in errors[:10]:
        print("  console:", e[:200])
    sys.exit(0 if rc == 0 and reached == MAPS and not errors else 1)


if __name__ == "__main__":
    main()
