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

Requirements: Linux x86-64, gcc, Python 3.10+, JDK 21, Ghidra 12.1.4, agent A CLI (logged in).

```bash
# one-time, user-local, no sudo (~1.2 GB)
mkdir -p ~/tools/dl && cd ~/tools/dl
curl -LO https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/OpenJDK21U-jdk_x64_linux_hotspot_21.0.12.1_1.tar.gz
curl -LO https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip
cd ~/tools && tar xzf dl/OpenJDK21U-*.tar.gz && unzip -q dl/ghidra_12.1.4_PUBLIC_20260921.zip

# full pilot (~2 min, one agent A call per target)
cd quake-decompile
./scripts/run_pilot.sh

# harness sanity checks (original must pass, mutant must fail)
python3 -m pytest -q
```

Individual stages: `scripts/build_pilot.py`, `src/extraction/run_ghidra.py`,
`src/evaluation/baseline_a.py`, `src/reconstruction/single_pass.py`,
`src/evaluation/difftest.py`, `src/metrics/collect.py`.

## Layout

| Path | Visible to agent? | Contents |
|---|---|---|
| `configs/pilot.json` | no | compiler flags, sources, pilot function names |
| `third_party/Quake-2/` | no | original source (git-ignored, cloned at pinned commit) |
| `experiments/pilot/c/` | no | link stubs + empty `main` |
| `build/` | no | binaries, objects, Ghidra logs, `eval/ground_truth.json` (git-ignored) |
| `experiments/pilot/agent_inputs/` | **yes** | Ghidra output per target, nothing else |
| `experiments/pilot/runs/<ts>/` | output | prompt, raw response + usage, `recon.c`, difftest JSON |
| `tests/difftest/` | no | per-function differential test drivers |
| `results/` | — | per-run CSV/JSON metrics |
| `docs/` | — | setup notes, related work, license |

## Build configuration (pilot)

- Host: Ubuntu 24.04, x86-64 (spec asked for macOS ARM64; this machine is Linux x86-64, so native x86-64 is used).
- `gcc 13.3.0`, `-O0 -g -fno-stack-protector -fcf-protection=none -fno-pie`, link `-no-pie -lm`.
- Sources compiled **unmodified**: `game/q_shared.c`, `game/g_utils.c`. Stubs only satisfy the linker for non-target functions (`experiments/pilot/c/stubs.c`).
- `strip --strip-all` produces the evaluation binary. Exact commands and SHA-256 land in `build/build_info.json`.

## Evaluation protocol

- Original behaviour = the original object files built with the same flags as the evaluation binary (identical code, pre-strip).
- Driver calls original and candidate on identical inputs; compares return **bit patterns** and the full argument buffer with guard words on each side (catches out-of-bounds writes and side effects).
- `dev` split: edge-case grid (±0, denormals, ±inf, NaN, huge) + 45k random. `heldout` split: 45k random from a different seed. Single-pass B uses no test feedback, so held-out is untouched by design.
- Passing finite tests is not proof of equivalence. Results say "passed N cases", never "equivalent".

## Pilot results (10 functions, -O0, run 20261012-223613)

| Baseline | Compiles | Dev pass | Held-out pass | agent A calls | Cost (list price) |
|---|---|---|---|---|---|
| A: Ghidra pseudocode + typedefs | 5/10 | 3/10 | 3/10 | 0 | 0 |
| B: single-pass agent A | 10/10 | 10/10 | 10/10 | 10 | $0.43 |

- A failures: 5 compile errors (all are `.rodata` constants that Ghidra prints as undeclared `DAT_xxxx` globals), 2 behaviour mismatches (`vectoyaw`: return value lost; `CrossProduct`: aliasing/order differs).
- B: 6–23 s per function. Most expensive was `BoxOnPlaneSide` (405 instructions): $0.15.
- Per-function rows: `results/20261012-223613.csv`. Tests per function: 45k–150k inputs per split.
- **`BoxOnPlaneSide` counts as contaminated.** Its `assert` strings put `"BoxOnPlaneSide"` and `third_party/Quake-2/game/q_shared.c` in the binary, and from there into the prompt. The output used Quake's own `vec3_t`, `cplane_t`, `emins`, `emaxs` and `signbits`. Without it, B is 9/9 clean.
- `vectoangles` output uses `yaw`/`pitch`/`roll`. These are natural names for an angle function, so this is a weak contamination signal.
- n=10, -O0, small leaf functions. No generalisation claimed.

### Input domains (documented in each driver)
- `Q_log2`: val >= 0 only. The original loops forever on negatives.
- `BoxOnPlaneSide`: only valid planes (signbits consistent with the normal, no NaN). Other inputs can trip the original's assert.
- `COM_FileExtension`: the returned string content is compared, not the pointer (static buffer).

## Validity threats (tracked)

- **Contamination:** Quake II source is public since 2001 and widely mirrored; the model may have memorised it. Pilot output used neither the original name nor original identifiers (`yaw`, `PITCH`, `M_PI`), but that does not rule it out. Plan: compare against a non-public control codebase.
- **String leaks:** `assert` in `q_shared.c` keeps `"BoxOnPlaneSide"` and `"q_shared.c"` in the stripped binary (as it would in a real release built without `NDEBUG`). Logged by `build_pilot.py` as `pilot_names_found_in_stripped_binary`.
- **Agent context:** agent A runs with tools disabled, no user/project settings or hooks, custom system prompt, empty working dir. The CLI still injects the working dir path and the account e-mail; neither carries source information.
- **Cost figures** come from the CLI's `total_cost_usd` (list-price estimate). On a subscription login, no per-call charge occurs.
- **64-bit port:** `g_local.h`'s `FOFS` macro truncates pointers on x86-64 (compiler warning). Affects `G_Find` callers only, not pilot targets.

## License

Quake II source: GPL v2 (`docs/QUAKE2_LICENSE_GPLv2.txt`). Binaries built here link GPL code, so this project is GPL-2.0-or-later. No game data files are used or downloaded.
