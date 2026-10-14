# quake-decompile

Research testbed: can an LLM agent reconstruct functionally equivalent C from
stripped game binaries? Testbed is the GPL Quake II source (id Software, 3.19).

Status: **pilot proof of concept** — one function end to end, two baselines.
Nothing here is a general result yet.

## Pipeline

```
Quake II source (unmodified) --gcc--> pilot.unstripped --strip--> pilot.stripped
                                          |                           |
                       ground_truth.json (eval only)        Ghidra headless (ExportFunctions.java)
                                                                      |
                                                       agent_inputs/FUN_<addr>.json
                                                         |                      |
                                     Baseline A: pseudocode + typedefs   Baseline B: 1 agent A call
                                                         \                      /
                                     difftest: candidate vs original object code, dev + held-out inputs
                                                                      |
                                                       results/<run>.{csv,json}
```

## Reproduce

Requirements: Linux x86-64, gcc, Python 3.10+, JDK 21, Ghidra 12.1.4, agent A CLI or agent B CLI (logged in), depending on `AGENT`.

```bash
# one-time, user-local, no sudo (~1.2 GB)
mkdir -p ~/tools/dl && cd ~/tools/dl
curl -LO https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/OpenJDK21U-jdk_x64_linux_hotspot_21.0.12.1_1.tar.gz
curl -LO https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip
cd ~/tools && tar xzf dl/OpenJDK21U-*.tar.gz && unzip -q dl/ghidra_12.1.4_PUBLIC_20260921.zip

# full pilot (~2 min, one agent A call per target)
cd quake-decompile
./scripts/run_pilot.sh configs/pilot_O0.json
./scripts/run_pilot.sh configs/pilot_O2.json

./scripts/run_pilot.sh configs/control_O0.json    # contamination control set
./scripts/run_pilot.sh configs/stateful_O0.json   # stateful game functions
./scripts/run_pilot.sh configs/game_all_O0.json   # whole game module (~1,000 calls, ~$50 list price)
./scripts/resume_run.sh experiments/pilot/runs/<run>   # finish targets an interrupted run missed

# one repair round over a run's failures (compiler errors / dev mismatches fed back)
./scripts/repair_run.sh experiments/pilot/runs/<run>

# re-test an existing run (no agent A calls), e.g. after changing drivers
./scripts/retest_run.sh experiments/pilot/runs/<run>

# harness sanity checks (original must pass, mutant must fail); match the last build's config
PILOT_CONFIG=configs/pilot_O2.json python3 -m pytest -q
```

To continue an interrupted run with agent B, use the existing run directory:

```bash
python3 scripts/status.py experiments/pilot/runs/20261013-095717-game_all_O2
AGENT=agent_b JOBS=6 ./scripts/resume_run.sh experiments/pilot/runs/20261013-095717-game_all_O2
AGENT=agent_b JOBS=6 ./scripts/repair_run.sh experiments/pilot/runs/20261013-095717-game_all_O2
```

`AGENT=agent_a|agent_b` selects the reconstructor. Resume skips every saved
`response.json`, regardless of agent; repair skips saved repair responses and
uses only dev feedback. `status.py` reports answers and repairs by agent plus
pending targets and `STOP_<agent>.txt`. A usage limit creates that STOP file;
resume and repair clear only the selected agent's marker. Failed calls append
`error_<agent>.txt`. The operator may also set a STOP marker to drain workers;
check its contents to distinguish an operator stop from a usage limit.
Both scripts rebuild the selected configuration and require the ground truth to
match the run snapshot. Runs with different configurations must not overlap
because `build/` is shared. agent B uses the isolated `~/.agent-b-home` home;
never substitute the operator's normal agent B home.

Individual stages: `scripts/build_pilot.py`, `src/extraction/run_ghidra.py`,
`src/evaluation/baseline_a.py`, `src/reconstruction/single_pass.py`,
`src/evaluation/difftest.py`, `src/metrics/collect.py`.

## Layout

| Path | Visible to agent? | Contents |
|---|---|---|
| `configs/pilot_O{0,2}.json` | no | compiler flags, sources, pilot function names |
| `third_party/Quake-2/` | no | original source (git-ignored, cloned at pinned commit) |
| `experiments/pilot/c/` | no | link stubs + empty `main` |
| `build/` | no | binaries, objects, Ghidra logs, `eval/ground_truth.json` (git-ignored) |
| `build/agent_inputs/` (+ copy in each run's `_meta/`) | **yes** | Ghidra output per target, nothing else |
| `experiments/pilot/runs/<ts>-<config>/` | output | prompt, raw response + usage, `recon.c`, difftest JSON, `_meta/` (config, build info, ground truth) |
| `tests/difftest/` | no | per-function differential test drivers |
| `results/` | — | per-run CSV/JSON metrics |
| `docs/` | — | setup notes, related work, license |

## Build configuration (pilot)

- Host: Ubuntu 24.04, x86-64 (spec asked for macOS ARM64; this machine is Linux x86-64, so native x86-64 is used).
- `gcc 13.3.0`, `-O0` or `-O2`, plus `-g -fno-stack-protector -fcf-protection=none -fno-pie -ffile-prefix-map=third_party/Quake-2/game/=`, link `-no-pie -lm`.
- Sources compiled **unmodified**: `game/q_shared.c`, `game/g_utils.c`. Stubs only satisfy the linker for non-target functions (`experiments/pilot/c/stubs.c`).
- `strip --strip-all` produces the evaluation binary. Exact commands and SHA-256 land in `build/build_info.json`.

## Evaluation protocol

- Original behaviour = the original object files built with the same flags as the evaluation binary (identical code, pre-strip).
- Driver calls original and candidate on identical inputs; compares return **bit patterns** and the full argument buffer with guard words on each side (catches out-of-bounds writes and side effects).
- `dev` split: edge-case grid (±0, denormals, ±inf, NaN, huge) + 45k random. `heldout` split: 45k random from a different seed. Single-pass B uses no test feedback, so held-out is untouched by design.
- Passing finite tests is not proof of equivalence. Results say "passed N cases", never "equivalent".

## Pilot results (10 functions)

Runs `20261012-224110-pilot_O0` and `20261012-224341-pilot_O2`. Both builds hide the source path in the binary.
"Pass" = bit-identical on every dev and held-out input. "NaN-relaxed" also counts NaN-vs-NaN with a different sign or payload as equal.

| Build | Baseline | Compiles | Pass (strict) | Pass (NaN-relaxed) | agent A calls | Cost |
|---|---|---|---|---|---|---|
| -O0 | A: Ghidra pseudocode | 5/10 | 3/10 | 4/10 | 0 | 0 |
| -O0 | B: single-pass agent A | 10/10 | **10/10** | 10/10 | 10 | $0.41 |
| -O2 | A: Ghidra pseudocode | 4/10 | 4/10 | 4/10 | 0 | 0 |
| -O2 | B: single-pass agent A | 9/10 | **7/10** | 9/10 | 9 | $0.34 |

- -O2 `COM_FileExtension`: **Ghidra never found the function.** It starts with a `jmp` and has no callers, so Ghidra saw no function start. It is counted as a failure for both baselines; we did not force it using the known address, which would leak ground truth.
- -O2 B failures, `LerpAngle` and `VectorNormalize`: NaN sign only (`nan` vs `-nan`), from a different SSE operand order. Both pass NaN-relaxed.
- A failures: mostly `.rodata` constants that Ghidra prints as undeclared `DAT_xxxx` globals. Also `vectoyaw` at -O0 lost its return value.
- Earlier run `20261012-223613` (-O0, source path visible): A 3/10, B 10/10.

### Contamination control (fresh, never-public code)

`experiments/control/c/control.c` holds 10 functions written for this project, each matching the shape of one Quake pilot function (angles, rounding, in-place vectors, struct + switch, strings, static buffer). Same pipeline, same flags.

| Set | Build | A strict | B strict | B NaN-relaxed | B cost |
|---|---|---|---|---|---|
| Quake | -O0 | 3/10 | 10/10 | 10/10 | $0.41 |
| Control | -O0 | 3/10 | 10/10 | 10/10 | $0.42 |
| Quake | -O2 | 4/10 | 7/10 | 9/10 | $0.34 |
| Control | -O2 | 1/10 | 9/10 | 9/10 | $0.40 |

- On this set, scores show no clear advantage for Quake code. n=10 per cell, so small differences mean nothing.
- Control -O2 failure, `clamp_length`: agent A returned `void`, dropping the returned length. The swapped parameter order is irrelevant: a float and a pointer go in separate ABI registers, so both orders compile to identical code.
- Threat: the control code was written by agent A (same model family as the reconstructor). Memorisation is impossible, but style familiarity is not ruled out. Human-written private code would be the stronger control.

### Test strength (mutation check)

`scripts/mutation_check.py` makes up to 12 single-edit bugs per original function (`<`→`<=`, `+`→`-`, constant +1, `&&`→`||`) and counts how many each driver catches.

- Control -O0: 95/101 caught. All 6 survivors were judged equivalent by hand (unused buffer size, a shifted counter that cancels out, boundary ties no input reaches).
- Quake -O0: 93/94 caught. The one survivor is an unused buffer size. Edits inside comments and `#if 0` blocks are now skipped; the first version of the script counted 10 of those as survivors.
- One real gap was found and fixed: the `BoxOnPlaneSide` driver never hit an exact plane-boundary tie. Exact ties were added; that mutant is now caught, and re-testing both Quake runs changed no result.

### Stateful game functions (whole game module, -O0)

Ten functions that read and write entity, level and engine state: `M_ChangeYaw`, `G_FreeEdict`, `M_CheckGround`, `M_SetEffects`, `range`, `visible`, `infront`, `CanDamage`, `trigger_counter_use`, `G_Spawn`. Harness design: `docs/stateful_harness.md`. 3,000 random worlds per function (1,500 dev + 1,500 held-out).

| Run | Prompt | A: Ghidra | B: agent A | B failure | Cost |
|---|---|---|---|---|---|
| `20261012-232321-stateful_O0` | v1 | 0/10 compile | 9/10 | `G_FreeEdict`: defined its own copies of globals instead of `extern` (prompt said nothing about globals) | $0.66 |
| `20261012-233726-stateful_O0` | v2 | 0/10 compile | 9/10 | `G_Spawn`: free-slot test inverted (real bug) | $0.65 |

- Prompt v2 adds one rule: declare globals `extern` under their Ghidra names. Runs record `prompt_version`.
- **Single-pass output varies:** v1 got `G_Spawn` right, v2 got it wrong.
- **Repeat sampling (prompt v2.1, which is the same text as v2 at -O0):** three more runs (`20261013-094805`, `-094932`, `-095054`) give 4 samples per function with prompt v2. 8 of 10 functions passed all 4. `G_FreeEdict` passed 3/4 (one mismatch). `G_Spawn` passed 2/4 (one mismatch, one answer without code).
- Mean single-sample pass rate 92.5%; every function passed at least once in 4 samples. Cost $1.56 for the 3 extra runs.
- Ghidra pseudocode never compiles here (undeclared `DAT_` globals, `code` pointer types, unknown struct members).
- Mutation check on the stateful harness: 45/53 caught. Of the 8 survivors, 4 are equivalent (`M_ChangeYaw` tie branches assign the same value) and 2 are practically unreachable exact float ties. The other 2 are a real but minor gap: `M_CheckGround`'s vertical velocity at exactly 100.
- Boundary coverage was added to the world generator (grid-snapped angles and origins, exact 80/500/1000 separations) after a first mutation check missed `range` and `M_ChangeYaw` ties. Both runs were re-tested; results did not change.

### Whole files: `g_ai.c`, `g_utils.c`, `m_move.c` (-O0)

Run `20261013-004715-files_ai_utils_move_O0`. Every function in the three files whose signature the harness supports (45 of 46; `tv` returns `float*`). Signatures are derived from the source by `scripts/make_file_config.py`.

| Baseline | Compiles | Pass (3,000 worlds) | agent A calls | Cost |
|---|---|---|---|---|
| A: Ghidra pseudocode | 9/45 | 3/45 | 0 | 0 |
| B: single-pass agent A (prompt v2) | 45/45 | **45/45** | 45 | $2.91 |

- Includes the monster AI core (`ai_run`, `ai_checkattack`, `FindTarget`, `M_CheckAttack`), movement (`SV_movestep`, `SV_NewChaseDir`, `M_walkmove`) and entity management.
- Coverage caveat: for some AI functions the *original* crashes on many random worlds (mostly a NULL `enemy`), and those cases are skipped. The worst is `FoundTarget`: 62% skipped, still 1,138 valid worlds. Every function had at least 1,100 valid worlds.
- The pipeline's first pass reported `KillBox` as a crash because I killed its slow test by hand. The harness now stops a function's test after 50 mismatches and uses a 1 s per-case timeout. The full re-test passes.

### Whole game module (all of `game/`, -O0)

Run `20261013-010856-game_all_O0` (config `game_all_O0.json`, from `make_file_config.py ALL`). 1,022 functions; 3 are not in the binary (one inside `#if 0`, two unused statics the compiler dropped). Of the 1,019 attempted, 85 have a signature the harness cannot call yet (compile-only), so **934 are behaviour-tested**.

| Baseline | Compiles | Pass, 934 tested | agent A calls | Cost |
|---|---|---|---|---|
| A: Ghidra pseudocode | 116/1,019 | 84 | 0 | 0 |
| B: single-pass agent A (prompt v2) | 995/1,019 | **905 (96.9%)** | 1,019 | $51.03 |
| C: B + one repair round on B's 32 failures | 1,019/1,019 | **930 (99.6%)** | +32 | +$2.46 |

- "Pass" means no difference on dev and held-out random worlds; it does not prove equivalence.
- B failures (32): 22 compile errors, 8 behaviour mismatches, 2 answers with two code blocks instead of one.
- Compile errors were mostly mechanical. In 14, a function-pointer type was passed to the model's own field-access macro, which C does not parse. In 6, `NULL` was used without `<stddef.h>`. Two contained junk tokens.
- **Repair round (C):** agent A gets its previous answer plus compiler errors, or, for mismatches, where the first differing byte is in the dev worlds (an edict offset, no names). Held-out results are never shown to it. 25 of 32 now pass on both splits and 3 compile-only targets now compile. 4 still mismatch: `Think_AccelMove`, `InitGame`, `BossExplode`, `ClientBegin`. Script: `src/reconstruction/repair.py`; results: `results/repair_20261013-010856-game_all_O0.json`.
- **Run interruption:** the agent A account usage limit was hit at about $35. 179 calls failed and were re-run 4 hours later with `scripts/resume_run.sh` on the identical build.
- 4 first-attempt answers with no code block were overwritten by that resume, so B counts their second attempt. B is therefore slightly optimistic (see `_meta/notes.md` in the run).
- **Test strength (sampled):** mutation check on 100 random tested functions, up to 6 mutants each. 269 of 329 mutants caught (82%), lower than on the hand-picked sets.
- 56 functions caught every mutant. 23 had no mutable code (empty bodies, animation stubs). 7 caught none: `Weapon_Machinegun`, `ClientCommand`, `SP_info_player_start`, `soldier_attack6_refire`, `G_SetClientFrame`, `Think_CalcMoveSpeed`, `IsFemale`.
- Those 7 depend on state the random worlds rarely produce: coop mode, command arguments, userinfo strings, exact weapon or animation frames. A pass on them is weak evidence. Results: `results/mutation_game_all_O0_sample100.{json,log}`.
- In some functions the original crashes on most random worlds, so few cases remain. For example, `Weapon_Grenade` at -O2 had 70 valid dev worlds out of 1,500.
- **Memorisation signal:** 154 of 1,017 reconstructions (15%) name at least one real Quake II function that appears nowhere in their prompt, usually as comments on callees. For example, `SP_item_health_mega` came back labelled `SpawnItem`, `FindItem`, `G_FreeEdict` and `/* SP_item_health_mega */` with zero leaks. Some of these could be guesses from strings, but most could not.
- 12 prompts contained the target's own name through a string in the binary; 8 of those passed. Excluding them, B passes 897 of 928 tested targets.

### Whole game module (-O2)

Run `20261013-095717-game_all_O2`, prompt v2.1 (states `-O2`). 1,015 functions are in the binary; Ghidra found no function start for 8, leaving 1,007 answered. 84 of those are compile-only.

**Two models, one run.** agent A hit its session limit, agent B took over, agent B hit its usage limit, and agent A finished. A function answered by one model was never redone by the other.
- Each answer records its model, and results are reported per model.
- The split is by run order, not random, so these two columns are **not a model comparison**.

| | agent A (`agent-a-model`) | agent B (`agent-b-model`) |
|---|---|---|
| First attempts answered | 634 (84 compile-only) | 373 (0 compile-only) |
| B: first-attempt pass, of tested | 509 / 550 (92.5%) | 361 / 373 (96.8%) |
| C: after one repair round (all repairs by agent A) | 537 / 550 (97.6%) | 371 / 373 (99.5%) |
| Still failing | 13 | 2 (`BossExplode`, `ClientBegin`) |
| Cost | $32.12 + $6.97 repair (list price) | not priced (subscription); tokens recorded |

- A (Ghidra pseudocode): 71 pass, 902 of 1,015 do not compile.
- **Isolation:** 0 agent B answers used a tool (every response records its event types). For agent A, see "Agent context" under validity threats.
- **Memorisation signal:** agent A's reconstructions named real Quake functions that were absent from the prompt in 114 of 631 (18%); agent B's in 0 of 373.
  - These are different functions, and agent B may simply write fewer comments, so this does not show that agent B memorised less.
- **Service interruptions**, all logged in the run's `_meta/notes.md`:
  - agent A session limit at 10:36.
  - agent B capacity / HTTP 429 errors at 6 and 4 parallel calls; 2 parallel calls ran cleanly.
  - agent B usage limit at 13:25.
- **Harness bug found and fixed in this run.** At -O2, GCC keeps tables of function pointers in read-only data. The harness rebuilt those constants from the original binary's raw bytes, but in the test binary the functions sit at different addresses. Correct reconstructions therefore stored wrong pointers and were marked mismatches. Ghidra's `_UNK_` names were also not mapped, which caused false link errors.
  - Fixed in `difftest.py`: pointer-valued constants are re-bound to the same function in the test binary. The whole run was then re-tested.
  - Before the fix, agent B's first attempts showed 47 failures; after it, 12.
  - Repairs requested before the fix were partly fed these false failures; they are kept as they are.

### Playable demo: Quake II running AI-decompiled game code

`scripts/build_ai_gameso.py` builds a real `game.so` in which **930 of the 1,019 -O0 game functions run AI-reconstructed code**: every function whose reconstruction passed both test splits. The other 89 keep the original code.
- It is loaded by the unmodified open-source engine (Yamagi Quake II) with the official free demo data, run headless.
- `scripts/playable_demo.py` plays a scripted fight against five soldiers and infantry. Both versions complete it with no crash: the monsters attack, take damage, die and gib.
- This is a demonstration, not an equivalence test, because frame timing varies between runs. Setup and caveats: `docs/playable_demo.md`.
- Game data and videos are not in the repo, because they are copyrighted.

**Portable source tree (`scripts/make_ai_source.py`).** The jump-patch build only works on x86 Linux. The source tree is plain C that any compiler can build:
- `ai/FUN_<addr>.c` holds the AI code unchanged. An assembler alias gives each function its real name, and the replaced original body is renamed `<name>__orig`.
- The addresses the AI code uses for data become aliases in the original file that defines the object, so file-local and function-local statics work too.
- With `--include-untested`, the 84 compile-only functions are included as well: **1,014 of 1,019 functions run AI code**. Four keep the original (not in the binary or no code), and one is excluded after failing in game (below).
- Built and played on Linux: the fight, the save/load test and the soak test all pass.

**Failures found only by playing** (harness tests passed or could not run):
- **Hardcoded addresses.** `WriteField1`, `ReadLevel` and `Use_Invulnerability` contain raw evaluation-binary addresses as integers (for example `InitGame`'s address, which the save format uses as a base). Loading a save crashed. The generator now rewrites integer literals that equal a symbol address into references to that symbol; these 3 functions are the only hits.
- **`Use_Weapon`** (compile-only, untested): it assumes a 120-byte item record (the real one is 136 bytes) and segfaults on `use chaingun`. It keeps the original code; the list is in `experiments/playable/ingame_failures.json`.

**Save/load and level change (`scripts/saveload_test.py`).** Play, save, load, save again, change level demo1 → demo2 → demo1, save. Original and AI builds both pass.
- The two saves are not byte-identical, even with the original: loading runs a few server frames and the engine adds the client address to the saved userinfo. Both builds differ in the same places (about 4,400 bytes of the level save, 15 bytes of the game save).
- Saves store function pointers relative to `InitGame`, so a save from one build cannot be loaded by another. The check is within one build.

**Soak test (`scripts/soak_test.py`).** All three demo maps back to back, 5 minutes each, in one engine process: running, turning, jumping, firing, cycling all weapons and saving every few seconds.
- Run once per build, original and AI side by side, 5.5 real minutes per map (16.5 minutes in all).
- **AI build: passed.** All three maps were played, 360 screenshots and saves were written, and the engine exited normally with no console errors.
- **Original build: all three maps were played, then the run aborted at shutdown** with glibc "double free or corruption", right after the game module shut down. Shorter runs of the same build exit normally. The cause is not investigated: it could be in id's game code, the engine, or the test setup. One run each is not evidence that the AI build is more stable.
- The input is scripted with no navigation, so the player often walks into walls. This shows stability over time, not coverage of every monster or weapon.

**macOS (Apple Silicon).** Not run on a Mac yet. Cross-checked here by building the tree for arm64 macOS with the clang inside zig (`docs/mac.md`):
- It builds and links as an arm64 Mach-O library, and all 1,762 name aliases resolve to the right address.
- The only undefined symbols are standard macOS C library functions.
- Fixed on the way: clang names function-local statics differently from gcc; two glibc-internal functions (`__isoc99_sscanf` in the entity parser, `__assert_fail`) now have a fallback; and 1997-style C that newer compilers reject stays a warning.
- Apple arm64 passes variadic arguments differently, so a non-variadic declaration of a print function would break there. `scripts/varargs_scan.py` found none in the AI code.

### Contamination evidence
- `BoxOnPlaneSide`: `assert` puts its name in the binary, so it is in the prompt (`prompt_leak` column). The output reuses Quake's `vec3_t`, `cplane_t` and `signbits`. Contaminated.
- `vectoangles` at -O2: **no leak in the prompt**, but agent A wrote "follows the classic Quake vectoangles routine". The model recognised the code from its structure alone. This is direct evidence of memorisation; a non-public control set is required before any claim.
- So any number on Quake code is an upper bound, not a clean decompilation result.

### Input domains (documented in each driver)
- `Q_log2`: val >= 0 only. The original loops forever on negatives.
- `BoxOnPlaneSide`: only valid planes (signbits consistent with the normal, no NaN). Other inputs can trip the original's assert.
- `COM_FileExtension`: the returned string content is compared, not the pointer (static buffer).

## Validity threats (tracked)

- **Contamination:** Quake II source is public since 2001 and widely mirrored; the model may have memorised it. Pilot output used neither the original name nor original identifiers (`yaw`, `PITCH`, `M_PI`), but that does not rule it out. Plan: compare against a non-public control codebase.
- **String leaks:** `assert` in `q_shared.c` keeps `"BoxOnPlaneSide"` and `"q_shared.c"` in the stripped binary (as it would in a real release built without `NDEBUG`). Logged by `build_pilot.py` as `pilot_names_found_in_stripped_binary`.
- **Agent context (agent A):**
  - Each call is `agent_a -p --tools "" --setting-sources "" --no-session-persistence --system-prompt <fixed>`, run from an empty temp dir.
  - Audit of all 1,663 saved agent A responses: 0 web searches, 0 web fetches, 0 permission denials (no tool was even attempted).
  - 1,659 are single-turn. 4 report 2 turns with no tool activity; the cause is not determined.
  - A probe call with identical flags (2026-10-13) reports no tools, no project instruction files and no memory. The only injected context is the CLI's environment block (temp working dir, platform, date) and the account e-mail.
  - Its total input was 674 tokens. The user's global project instruction files alone is about 2.9 kB (roughly 700 tokens), so it was not loaded.
  - Auto-memory is keyed to the working directory, and the temp dir has none.
  - `--bare` was not used. Future runs could add it for a stricter guarantee.
- **Agent context (agent B, from 2026-10-13):**
  - `agent_b exec` with a read-only sandbox, from an empty temp dir.
  - Clean `AGENT_B_HOME`: no AGENTS.md, memories or skills; login shared by symlink.
  - Memories and web search are disabled by flag. A probe confirmed no injected instructions and no web tool.
  - Each response records its event item types. Any tool or command use marks `isolation_violation`, and that answer is not used.
- **Cost figures** come from the CLI's `total_cost_usd` (list-price estimate). On a subscription login, no per-call charge occurs.
- **Wrong optimisation level in early -O2 prompts:** prompts v1/v2 always said "-O0". The pilot -O2 and control -O2 runs were therefore told the wrong level. Fixed in prompt v2.1, which takes the level from the config; the full-game -O2 run uses v2.1.
- **Harness false failures (found and fixed 2026-10-13):**
  - -O2 pointer constants were copied as raw bytes; fixed, with all stateful runs re-tested. -O0 first-attempt results did not change.
  - **An operator mistake corrupted some re-test results:** a re-test believed killed kept running for an hour, while `build/` was switched to a different build. It also shared scratch folders with the other re-tests (work dirs were named per function, not per run). The result was false link errors and crashes, including 3 that briefly looked like "parallel flakiness".
  - Fixes: each candidate now gets its own work dir, and `retest_run.sh` re-runs every failure alone as a safety net.
  - Both whole-game runs were then re-tested from scratch with nothing else running. Their numbers in this README come from that clean re-test.
- **64-bit port:** `g_local.h`'s `FOFS` macro truncates pointers on x86-64 (compiler warning). Affects `G_Find` callers only, not pilot targets.

## License

Quake II source: GPL v2 (`docs/QUAKE2_LICENSE_GPLv2.txt`). Binaries built here link GPL code, so this project is GPL-2.0-or-later. No game data files are used or downloaded.
