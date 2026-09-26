# Achievement harness (headless PS1 + real rcheevos)

A scriptable, headless PlayStation that boots the real *Crash Bandicoot (USA)* disc and evaluates
the repo's achievement conditions **frame by frame with the rcheevos runtime**, the same library
DuckStation runs. It exists so a `mem_addr` is proven against real game RAM before anyone boots
the game by hand: every scenario states which achievements must fire and which must not.

- **Emulation:** a libretro core loaded by a small C frontend (`src/harness.c`), driven from
  Python through `ctypes`. `pcsx_rearmed` (default) runs with its HLE BIOS in interpreter mode,
  which is deterministic, so input plans replay frame-exactly. `swanstation` (a DuckStation fork)
  needs a real BIOS and is the closest to the user's emulator.
- **Achievements:** the shim is compiled with the repo's `vendor/rcheevos`. After every
  `retro_run` it calls `rc_runtime_do_frame` with a peek callback that maps RA addresses
  `$000000-$1FFFFF` onto the 2 MiB main RAM; the scratchpad (`$200000+`) reads as 0. DuckStation's
  `rc_client_do_frame` does the same memref update and trigger evaluation per achievement.
- **Definitions:** `achievements.py` imports the seed commands and calls their builders
  (`build_mem_addr`), so the harness tests exactly the strings the server serves. Nothing is
  copied.

The harness runs **inside the project container**, like everything else. Nothing it downloads or
produces is committed: cores, the compiled shim, states, traces and screenshots live in
`.cache/achievement-harness/` (gitignored). The disc and the BIOS are never downloaded.

## Configuration

| Variable | Required | Meaning |
| --- | --- | --- |
| `CRASH1_CUE` | yes | Path, inside the container, of the *Crash Bandicoot (USA)* `.cue` (SCUS-94900) |
| `CRASH1_BIOS_DIR` | swanstation only | Directory holding an NTSC-U BIOS (`scph5501.bin`, `scph1001.bin`, `scph7001.bin`, `scph101.bin`, or the PS2 `scph39001.bin`) |

On first use the harness needs network access:

- **Cores** come from `https://buildbot.libretro.com/nightly/linux/x86_64/latest/<core>_libretro.so.zip`
  into `.cache/achievement-harness/cores/`, once. Delete the file to fetch a newer build.
- **`libretro.h`** is fetched by `build.sh` from a pinned libretro-common commit and checked
  against its SHA-256. `build.sh` then compiles `src/harness.c` + `vendor/rcheevos` into
  `.cache/achievement-harness/build/libharness.so`; `harness.py` rebuilds it whenever a source is
  newer.

Versions are printed by `python tools/achievement-harness/harness.py` and at the top of every
session log: the core build (e.g. `PCSX-ReARMed r26 ff81ed1`) and the rcheevos version with the
vendored upstream commit (`vendor/rcheevos/UPSTREAM-COMMIT`). The trigger results of the attract,
death and quit scenarios were measured identical on the vendored 12.3 and on upstream 12.4.0.

## Running it in the container

`podman-compose exec` cannot add a mount to the running `web` container, so mount the disc into a
one-off container with `run -v` (the harness needs neither the database nor Redis):

```bash
podman-compose --in-pod=false run --rm --no-deps \
  -v "/path/to/Crash Bandicoot (USA)":/roms:ro \
  -e CRASH1_CUE="/roms/Crash Bandicoot (USA).cue" \
  web python tools/achievement-harness/scenarios.py all
```

Add `-v /path/to/bios:/bios:ro -e CRASH1_BIOS_DIR=/bios` for swanstation. Every command below is
`python tools/achievement-harness/<script>.py ...` run that way.

| Command | What it does |
| --- | --- |
| `harness.py` | Boots the disc and prints the core, rcheevos and disc in use |
| `achievements.py` | Lists the repo's achievements as the harness activates them (id, title, `mem_addr`) |
| `states.py [--core C] [--fresh] [NAME ...]` | Derives the named states from a cold boot (all by default) and prints their digests |
| `scenarios.py [--core C] NAME ... \| all` | Plays scenarios; prints `OK`/`FAIL` per scenario and exits non-zero on any `FAIL` |
| `nav.py [--from STATE] "cmd; cmd"` | Drives the emulator by hand (see *Navigation DSL*) |
| `explore.py START OUT.json [--iterations N] [--seed N]` | Searches an input plan that clears a stage |
| `analyze.py TRACE.csv [PROBE ...] [--timeline]` | Summarises a trace, or prints the frames where the probes changed |
| `sheet.py OUT.png SHOT.png ...` | Tiles screenshots into one contact sheet |

`python -m pytest` includes `test_achievement_harness.py`: it boots the disc to the island map with
every achievement active and asserts none fired. It is skipped when `CRASH1_CUE` is unset or names
no file, so the suite stays green without the disc.

## States

No save state is hand-made or committed. Each is a recipe in `states.py`: a parent state (or a cold
boot) plus scripted navigation from `navigation.py`, which waits on RAM values, never on fixed
delays. `states.load(emu, name)` restores the cached file or derives the whole chain, so every
scenario and plan replays on a fresh checkout. A derived state is saved and loaded back before use,
so a run behaves the same whether its state came from the cache or was derived moments earlier.

| State | Parent | Where |
| --- | --- | --- |
| `map` | cold boot | Island map after NEW GAME, cursor on N. Sanity Beach |
| `nsanity-beach-start` | `map` | N. Sanity Beach, 30 frames after the player gains control |
| `nsanity-beach-clear` | `nsanity-beach-start` | Stage Clear screen, after `plans/nsanity-beach-clear.json` |

`states.py --fresh` re-derives every state and prints a digest per state; two runs on the same core
build print the same digests. Deriving `nsanity-beach-clear` is the end-to-end reproducibility
check: cold boot, map, N. Sanity Beach, the clearing plan, Stage Clear. States are cached per core
build, so a new core starts from an empty cache; after changing a recipe or `navigation.py`, pass
`--fresh` (or delete `.cache/achievement-harness/states/`).

## Scenarios

Each scenario starts from a derivable state, activates every repo achievement, records a trace and
compares the set of achievements that fired with its expectation. Between attempts,
`Session.rearm()` resets only the achievements that fired, so one run judges several deaths or
quits on their own while the others keep their hits, as in a live session.

| Scenario | Start | Must fire | Guards against |
| --- | --- | --- | --- |
| `cold-boot` | cold boot | nothing | Boot-time RAM noise (zeroed RAM reads as "stage 0") |
| `attract` | cold boot | nothing | The attract-mode demos, which play real stages with no player |
| `beach-deaths` | `nsanity-beach-start` | nothing | Deaths: after leaving the spawn zone, right after a respawn, after idling |
| `beach-quit` | `nsanity-beach-start` | nothing | Pause -> SELECT quits, armed or not |
| `beach-clear` | `nsanity-beach-start` | N. Sanity Beach | Replays the clearing plan (a real completion), then enters Jungle Rollers and quits |

A new achievement needs a scenario that reaches its event and the look-alike events that must not
fire it; add it to `SCENARIOS` with its expectation.

Outputs, per scenario (`<core>-` prefixed when not on pcsx_rearmed):

- `traces/<name>.csv`: one row per frame, the input mask and every probe, plus `achN_state` and
  `achN_hits` (`current/required` of every condition with a hit target).
- `traces/<name>.events.log`: every probe change, every rcheevos event (`ACTIVATED`, `PRIMED`,
  `TRIGGERED`, ...) and the scenario's notes, by frame.
- `shots/<name>/<frame>-<what changed>.png`: automatic screenshots on key probe changes and on
  every trigger.

Frames count from the scenario's start state (a state load restarts the counter at 0).

## Input plans and the Go-Explore search

A plan (`plans/*.json`) is a list of `[frames, button_mask]` inputs (the source of truth for the
replay) with the 16-frame macro names that produced them, the named start state, and the core and
core build it was searched on. `plan.replay()` refuses another core and warns on another build.

`explore.py` keeps an archive of player-position cells, each with a compressed save state, and
plays random macros from rarely chosen cells until the stage is left alive. With the default seed it
cleared N. Sanity Beach in about 16 minutes (1608 rollouts). To re-search a plan that stopped
replaying (a new core build, a changed recipe):

```bash
python tools/achievement-harness/explore.py nsanity-beach-start tools/achievement-harness/plans/nsanity-beach-clear.json
python tools/achievement-harness/states.py --fresh nsanity-beach-clear   # proves it replays
```

## Navigation DSL

`nav.py` runs a `;`-separated script, optionally from a derivable state (`--from map`):
`wait N`, `hold BTN[+BTN] N`, `press BTN[+BTN]` (4 frames + 12 released), `shot NAME`
(`shots/nav/NAME.png`), `save NAME` / `load NAME` (scratch states in
`states/<core>/<build>/scratch/`, for exploring only), `peek` (key probes). Buttons:
`CROSS SQUARE CIRCLE TRIANGLE START SELECT UP DOWN LEFT RIGHT L1 R1 L2 R2`.

```bash
python tools/achievement-harness/nav.py --from map "press CROSS; wait 900; shot beach; peek"
```

## Python API

```python
from harness import Btn, Emu

emu = Emu(core="pcsx_rearmed").load()  # one emulator per process
emu.step(frames=1, buttons=())  # run N frames holding Btn values; frame hooks run per frame
emu.run(frames, mask)  # same with a raw libretro button mask
emu.step(6, [Btn.START])  # hold START for 6 frames
emu.u8(a) / u24(a) / u32(a) / s32(a) / read(a, n)  # a = RA address (0x000000-0x1FFFFF)
emu.deref(0x618A4, 0x6C, 0xE4, 0x0C)  # RA-style 24-bit pointer chain; None on a null hop
emu.screenshot(path)  # PNG of the last rendered frame
emu.snapshot() / restore(blob) / save_state(path) / load_state(path)  # loads reset triggers
emu.activate(id, mem_addr) / reset_achievement(id)  # reset: WAITING, zeroed hits
emu.achievement_state(id)  # 'waiting' | 'active' | 'primed' | 'triggered' | ...
emu.achievement_hits(id)  # [[(type, required, current, is_true), ...] per condset]
emu.events()  # [(frame, 'ACHIEVEMENT_TRIGGERED', id, value), ...]
emu.frame  # frames since boot or since the last state load
emu.core_version / emu.rcheevos_version / emu.options()
emu.frame_hooks.append(callable)  # called with emu after every frame
```

`states.load(emu, name)` derives or restores a state. `Session(name, state=None, core=...)` in
`session.py` wraps an `Emu` with every repo achievement active and the tracer attached; helpers:
`step`, `press`, `wait_until`, `shot`, `note`, `rearm`, `close` (returns `[(frame, title), ...]`).
`navigation.py` holds the menu moves (`boot_to_map`, `enter_stage`, `pause_and_quit`,
`leave_stage_clear`).

## Probes

`probes.py` is the RAM map the traces record, with every address a named constant. `rXXXXX` /
`wXXXXX` are the raw 8-bit / 24-bit reads the repo's conditions make (`0xH`/`0xW`). `g_*` are the
engine's GOOL globals (global *n* at `0x6188C + 4n`) under their names in the c1 decompilation;
most are 24.8 fixed point, which is why the RA code notes point at odd bytes (`0x618ED` lives,
`0x61985` boxes, `0x619C5` stage). Object probes follow the Aku Aku, HUD and player pointers.

## Caveats

- **One emulator per process.** libretro cores and the rcheevos shim keep global state;
  `scenarios.py` spawns one process per scenario, and a second `Emu()` in a process raises.
- **Determinism is a property of the core build.** Plans replay only on the pcsx_rearmed
  interpreter (`pcsx_rearmed_drc=disabled`, the default): its lightrec dynarec is not bit-exact
  after a state load. A new nightly core may change the emulation: when deriving
  `nsanity-beach-clear` then times out waiting for Stage Clear, re-search the plan.
- **swanstation** derives the navigation states but cannot replay pcsx_rearmed plans, so
  `beach-clear` is pcsx_rearmed only.
- **Re-arming is a harness device.** In DuckStation an achievement fires once per session.
  `rearm()` resets a fired one to WAITING with zeroed hits: the hits it would have carried had it
  not fired are unknowable. Unfired ones are left alone.
- The HLE BIOS draws some cyan artefacts in cutscenes; game logic is unaffected. A screenshot on a
  transition frame is often black (fade). pcsx_rearmed prints a few lightrec lines at start-up
  even in interpreter mode.

## Credits

- Probe names and the GOOL globals layout: the **wurlyfox/c1** decompilation of Crash Bandicoot
  (<https://github.com/wurlyfox/c1>, `src/globals.h`, `gool_globals` at `0x8006188C`) and the
  CBHacks memory map (<https://wiki.cbhacks.com/w/Memory_Map>).
- RetroAchievements code notes for game 10434, mirrored in `apps/games/code-notes/crash-bandicoot-1.md`.
- **rcheevos** (MIT, RetroAchievements), vendored in `vendor/rcheevos/`.
- **libretro** API header (MIT, the RetroArch team, libretro-common) and the **pcsx_rearmed** and
  **swanstation** cores, downloaded from the libretro buildbot at run time.
