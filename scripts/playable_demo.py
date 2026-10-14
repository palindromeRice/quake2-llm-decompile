#!/usr/bin/env python3
"""Play a scripted Quake II fight headless with a given game.so and record it.

Engine: Yamagi Quake II (GPL, built against a user-local SDL2, soft renderer,
SDL offscreen video, no sound). Data: the official free Quake II demo pak0.pak.
Neither is redistributed here; see docs/playable_demo.md for setup.

The fight: demo1 with five soldiers/infantry placed in front of the player start
through an engine-side entity override (identical for every game.so), then a
fixed console script (god mode, chaingun, super shotgun), screenshot every 3rd
frame. Timing comes from the engine's frame clock, so two runs are similar but
not frame-identical.

Usage: playable_demo.py <game.so> <name> [--tools ~/tools]
Writes ~/tools/q2run/<name>/ (run dir) and ~/tools/q2run/video/<name>.mp4.
"""
import math, os, re, shutil, struct, subprocess, sys
from pathlib import Path

game_so, name = Path(sys.argv[1]).resolve(), sys.argv[2]
T = Path(sys.argv[sys.argv.index("--tools") + 1] if "--tools" in sys.argv else Path.home() / "tools")
ENGINE, PAK = T / "src/yquake2/release", T / "q2demo/baseq2/pak0.pak"
RUN = T / "q2run" / name
HOME = T / "q2run" / f"home_{name}"
SQUAD = [(260, 0, "monster_soldier"), (300, -70, "monster_soldier_light"), (300, 70, "monster_infantry"),
         (380, -40, "monster_soldier"), (380, 40, "monster_infantry")]   # (distance, lateral, class)


def pak_file(path):
    with open(PAK, "rb") as f:
        off, ln = struct.unpack("<ii", f.read(12)[4:12])
        f.seek(off)
        for _ in range(ln // 64):
            e = f.read(64)
            if e[:56].split(b"\0")[0].decode() == path:
                o, l = struct.unpack("<ii", e[56:64])
                f.seek(o)
                return f.read(l)
    raise SystemExit(f"{path} not in {PAK}")


def entities_with_squad():
    bsp = pak_file("maps/demo1.bsp")
    eo, el = struct.unpack("<ii", bsp[8:16])
    ents = bsp[eo:eo + el].decode("latin1").rstrip("\0")
    start = next(b for b in re.findall(r"\{[^{}]*\}", ents) if "info_player_start" in b and "targetname" not in b)
    px, py, pz = map(float, re.search(r'"origin" "([^"]+)"', start).group(1).split())
    a = math.radians(float(re.search(r'"angle" "([^"]+)"', start).group(1)))
    fx, fy = math.cos(a), math.sin(a)
    add = "".join('{\n"classname" "%s"\n"origin" "%d %d %d"\n"angle" "%d"\n}\n'
                  % (c, px + fx * d - fy * l, py + fy * d + fx * l, pz, (math.degrees(a) + 180) % 360)
                  for d, l, c in SQUAD)
    return ents + add


def fight_cfg():
    w3 = "wait;wait;shot"
    seq = [w3] * 25                                       # monsters notice the player and attack
    for _ in range(4):
        seq += ["use chaingun", "+attack", *[w3] * 12, "-attack", *[w3] * 4,
                "+left", *[w3] * 2, "-left", "+attack", *[w3] * 8, "-attack", "+right", *[w3] * 4, "-right"]
    seq += ["use super shotgun", "+attack", *[w3] * 15, "-attack", *[w3] * 20]
    lines = ["set cl_maxfps 30", "set vid_maxfps 30", "god", "give all", 'alias shot "screenshot"']
    chunks = [seq[i:i + 40] for i in range(0, len(seq), 40)]   # console line length limit
    for i, c in enumerate(chunks):
        lines.append(f'alias part{i} "{"; ".join(c)}; {f"part{i + 1}" if i + 1 < len(chunks) else "quit"}"')
    return "\n".join(lines) + "\n"


def main():
    shutil.rmtree(RUN, ignore_errors=True)
    shutil.rmtree(HOME, ignore_errors=True)
    (RUN / "baseq2/maps").mkdir(parents=True)
    (HOME / ".local/share").mkdir(parents=True)
    for f in ("quake2", "ref_soft.so"):
        shutil.copy(ENGINE / f, RUN / f)
    os.symlink(PAK, RUN / "baseq2/pak0.pak")
    os.symlink(PAK.parent / "players", RUN / "baseq2/players")
    shutil.copy(game_so, RUN / "baseq2/game.so")
    (RUN / "baseq2/maps/demo1.ent").write_text(entities_with_squad(), encoding="latin1")
    (RUN / "baseq2/fight.cfg").write_text(fight_cfg())
    env = {**os.environ, "HOME": str(HOME), "SDL_VIDEODRIVER": "offscreen", "SDL_AUDIODRIVER": "dummy",
           "LD_LIBRARY_PATH": str(T / "sdl2/lib")}
    if (T / "q2run/dbg/segv.so").exists():   # optional crash reporter: prints the faulting function
        env["LD_PRELOAD"] = str(T / "q2run/dbg/segv.so")
    log = RUN.parent / f"{name}.log"
    with open(log, "w") as fh:
        rc = subprocess.run(["./quake2", "-datadir", str(RUN), "+set", "vid_renderer", "soft", "+set", "s_initsound", "0",
                             "+set", "r_mode", "4", "+set", "cheats", "1", "+set", "skill", "1",
                             "+map", "demo1", "+exec", "fight.cfg", "+part0"],
                            cwd=RUN, env=env, stdout=fh, stderr=subprocess.STDOUT, timeout=600).returncode
    shots = HOME / ".local/share/YamagiQ2/baseq2/scrnshot"
    n = len(list(shots.glob("*.tga")))
    video = T / "q2run/video" / f"{name}.mp4"
    video.parent.mkdir(exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", "10", "-i", str(shots / "q2_%04d.tga"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    loaded = "failed to load game DLL" not in log.read_text(errors="replace")   # engine exits 0 even then
    print(f"{name}: engine exit {rc}, game library loaded {loaded}, {n} frames, log {log}, video {video}")
    if rc != 0 or not loaded:
        sys.exit(1)


if __name__ == "__main__":
    main()
