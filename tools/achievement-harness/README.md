# Achievement harness (headless PS1 + real rcheevos)

A scriptable, headless PlayStation that boots the real *Crash Bandicoot (USA)* disc and evaluates
the repo's achievement conditions, leaderboards and rich presence script **frame by frame with the
rcheevos runtime**, the same library DuckStation runs. It exists so a `mem_addr` is proven against
real game RAM before anyone boots the game by hand: every scenario states which achievements must
fire and which must not, how every leaderboard attempt it plays must end, and which rich presence
strings the game must show.

- **Emulation:** a libretro core loaded by a small C frontend (`src/harness.c`), driven from
  Python through `ctypes`. `pcsx_rearmed` (default) runs with its HLE BIOS in interpreter mode,
  which is deterministic, so input plans replay frame-exactly. `swanstation` (a DuckStation fork)
  needs a real BIOS and is the closest to the user's emulator.
- **Achievements:** the shim is compiled with the repo's `vendor/rcheevos`. After every
  `retro_run` it calls `rc_runtime_do_frame` with a peek callback that maps RA addresses
  `$000000-$1FFFFF` onto the 2 MiB main RAM; the scratchpad (`$200000+`) reads as 0. DuckStation's
  `rc_client_do_frame` does the same memref update and trigger evaluation per achievement.
  The leaderboards are activated in the same runtime (`rc_runtime_activate_lboard`), which reports
  their `LBOARD_STARTED`/`UPDATED`/`CANCELED`/`TRIGGERED` events with the value, as DuckStation's
  client does per frame.
  The rich presence script is activated in the same runtime (`rc_runtime_activate_richpresence`),
  updated by the same `rc_runtime_do_frame` and read back after every frame
  (`rc_runtime_get_richpresence`), where DuckStation reads it once per ping.
- **Definitions:** `achievements.py` imports the seed commands and calls their builders
  (`build_mem_addr`, `collectible_achievements`, `advanced_achievements`, `leaderboards`,
  `build_rich_presence`), so the harness tests exactly the strings the server serves. Nothing is
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
  into `.cache/achievement-harness/cores/`, once. Delete the file to fetch a newer build. The
  buildbot keeps only the latest nightly of each core, so the build is whatever is current on
  first use; a plan replays frame-exactly only on the build it records (see *Caveats*).
- **`libretro.h`** is fetched by `build.sh` from a pinned libretro-common commit and checked
  against its SHA-256. `build.sh` then compiles `src/harness.c` + `vendor/rcheevos` into
  `.cache/achievement-harness/build/libharness.so`; `harness.py` rebuilds it whenever a source is
  newer.

Versions are printed by `python tools/achievement-harness/harness.py` and at the top of every
session log: the core build (e.g. `PCSX-ReARMed r26 ff81ed1`) and the rcheevos version with the
vendored upstream commit (`vendor/rcheevos/UPSTREAM-COMMIT`). The vendored runtime is 12.3;
DuckStation ships 12.4.0, so the in-game check still runs the conditions on a newer runtime.

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
| `achievements.py` | Lists the repo's achievements and leaderboards as the harness activates them (id, title, `mem_addr`), then the rich presence script |
| `states.py [--core C] [--fresh] [NAME ...]` | Derives the named states from a cold boot (all by default) and prints their digests |
| `scenarios.py [--core C] NAME ... \| all` | Plays scenarios; prints `OK`/`FAIL` per scenario and exits non-zero on any `FAIL` |
| `nav.py [--from STATE] "cmd; cmd"` | Drives the emulator by hand (see *Navigation DSL*) |
| `explore.py STAGE [--goal G] [--from STATE] [--out PLAN] [--minutes M] [--seed N]` | Searches an input plan that reaches a goal in a stage: its clear by default |
| `analyze.py TRACE.csv [PROBE ...] [--timeline]` | Summarises a trace, or prints the frames where the probes changed |
| `sheet.py OUT.png SHOT.png ...` | Tiles screenshots into one contact sheet |

`python -m pytest` includes `test_achievement_harness.py`: it boots the disc to the island map with
every achievement active and asserts none fired, then plays every scenario (one process each) and
asserts it passed. It is skipped when `CRASH1_CUE` is unset or names no file, so the suite stays
green without the disc.

## States

No save state is hand-made or committed. Each is a recipe in `states.py`: a parent state (or a cold
boot) plus scripted navigation from `navigation.py`, which waits on RAM values, never on fixed
delays. `states.load(emu, name)` restores the cached file or derives the whole chain, so every
scenario and plan replays on a fresh checkout that downloads the core build the plan records. A
derived state is saved and loaded back before use, so a run behaves the same whether its state
came from the cache or was derived moments earlier.

| State | Parent | Where |
| --- | --- | --- |
| `map` | cold boot | Island map after NEW GAME, cursor on N. Sanity Beach |
| `map-unlocked` | `map` | Island map with the stages up to Rolling Stones unlocked (see below) |
| `map-password` | cold boot | Island map up to Koala Kong, loaded by typing the password `XOOOXSXS` (see below) |
| `<stage>-start` | `map` (N. Sanity Beach), `map-password` (Hog Wild on, and Ripper Roo), `map-unlocked` (the others) | The stage, 30 frames after the player gains control |
| `<stage>-clear` | `<stage>-start` | Stage Clear screen after `plans/<stage>-clear.json`; only for a stage with a committed plan |
| `nsanity-beach-two-masks` | `nsanity-beach-start` | N. Sanity Beach re-entered with 2 Aku Aku masks: twice, the clearing plan up to the first Aku Aku crate, then a quit and a re-entry |
| `nsanity-beach-farmed-wumpa` | `nsanity-beach-start` | N. Sanity Beach re-entered with 36 Wumpa: twice, the clearing plan up to its 20th fruit, then a quit and a re-entry |
| `<stage>-checkpoint-respawn` | `<stage>-start` | The stage after `plans/<stage>-checkpoint.json` (a route that breaks a checkpoint crate) and a death by seeded random play: the player back in control at the checkpoint; only for a stage with that plan |
| `<stage>-early-death-restart` | `<stage>-start` | The stage after a death by seeded random play before any checkpoint (derivation fails otherwise): the stage restarted, every box back; only for a stage given a seed known to die there (`Stage.early_death_seed`, N. Sanity Beach) |

`<stage>` is each level achievement's stage, in `states.STAGES` with its level id, map cursor and
the direction it runs on screen: `nsanity-beach`, `jungle-rollers`, `the-great-gate`, `boulders`,
`upstream`, `rolling-stones`, `hog-wild`, `native-fortress`, `up-the-creek`. `states.BOSS_FIGHTS` adds
`papu-papu` (map cursor 5, on the way to Rolling Stones) and `ripper-roo` (map cursor 10), which only
get a `-start` state.

`map-password` makes no write: from the title menu it opens PASSWORD (title state `0e`), types the
community's password for the Koala Kong save point and continues to the map, which then holds the
stages up to Koala Kong, no gem and no key, with the cursor on Koala Kong (measured in
`apps/achievements/crash-bandicoot-1-completion-inventory.md`). `navigation.move_cursor_to` walks
back from there: Wumpa Island's screen runs right to left, so RIGHT moves the cursor back on it.

`map-unlocked` is the only RAM write a state makes: it sets c1 `levels_unlocked` (`0x61948`) to 7,
then enters and quits N. Sanity Beach so the map reloads with the paths to the later stages, which
the recipes walk the cursor along. The poke only *reaches* a stage; nothing writes a clear, a
level id or a game state, so every clear in a scenario is played. The farmed states are real play:
a quit commits the Wumpa and masks collected and the re-entry brings the crates back, as for a
player farming them; a recipe fails when its replay diverges from the count it expects. The only
other writes are the pokes of the `-poked` scenarios (lives, box count), which are secondary
evidence only (see *Scenarios*).

`states.py --fresh` re-derives every state and prints a digest per state; two runs on the same core
build print the same digests. Deriving a `<stage>-clear` state is the end-to-end reproducibility
check: cold boot, map, the stage, its clearing plan, Stage Clear. States are cached under
`states/<core>/<build>/recipes-<digest>/`, the digest covering every file that derives them
(`states.RECIPE_SOURCES`: the recipes, the navigation moves, the probes, plan replay, the emulator
wrapper and shim, every committed plan). A new core build or an edited source therefore derives
afresh instead of reusing a stale state; `--fresh` re-derives anyway.

## Scenarios

Each scenario starts from a derivable state, activates every repo achievement and leaderboard,
records a trace and judges every trigger against its expectation: an expected achievement must fire
exactly once, while the game shows its expected level (lid), and nothing else may fire. A trigger on another level fails
even when its title was expected, so a completion that fires on a zone load or a death is caught. The
`OK`/`FAIL` line lists each trigger with its frame and lid. Between attempts, `Session.rearm()`
resets only the achievements that fired, so one run judges several deaths or quits on their own
while the others keep their hits, as in a live session.

| Scenario | Start | Must fire | Guards against |
| --- | --- | --- | --- |
| `cold-boot` | cold boot | nothing | Boot-time RAM noise (zeroed RAM reads as "stage 0") |
| `attract` | cold boot | nothing | 15 minutes of attract-mode demos, which play real stages with no player |
| `game-over` | `nsanity-beach-start` | nothing | Deaths down to the game over and the title screen it returns to |
| `attract-then-new-game` | cold boot | nothing | The first attract demo, then a new game into N. Sanity Beach: the attract game state must not leak into play |
| `<stage>-deaths` | `<stage>-start` | nothing | Three deaths: the first, one re-armed right after the respawn, one after idling where the player respawned (no idling in Hog Wild, whose hog runs on by itself); each replays the stage's route first when it has one |
| `<stage>-quit` | `<stage>-start` | nothing | Pause -> SELECT quits: right after control, after running and standing, after standing |
| `<stage>-clear` | `<stage>-start` | the stage's achievement, once, on Stage Clear (lid `0x2D`) | Replays the clearing plan (a real completion); after a re-arm, Stage Clear -> map, the next stage and a quit fire nothing |
| `<boss>-quit` | `<boss>-start` | nothing | Standing in the boss fight, then pause -> SELECT |
| `<boss>-boss` | `<boss>-start` | the boss achievement, once, on the last hit (lid of the fight) | Replays `plans/<boss>-boss.json`; then a state saved after the hit is loaded, the fight returns to the map, and the fight is entered again and quit |
| `<boss>-deaths` | `<boss>-start` | nothing | The boss plan replayed until the boss has one health left, then a death; another death right after the respawn, which brings the boss back at full health |
| `<stage>-no-wumpa` | `<stage>-start` | the stage's achievement on Stage Clear and `Beach Diet` on the clear (lid of the stage) | Replays `plans/<stage>-no-wumpa.json`, a clear without a Wumpa; then as `<stage>-clear`. Only for the stage `Beach Diet` names |
| `<stage>-aku` | the plan's start | `Mask Stack`, once, on the third mask (lid of the stage) | Replays `plans/<stage>-aku.json`; then a state saved after the event is loaded, and the stage is quit, re-entered with the masks committed and quit |
| `<stage>-wumpa` | the plan's start | `Fruit Into Life`, once, on the wrap past 100 (lid of the stage) | Replays `plans/<stage>-wumpa.json`; then the same state load, quit, re-entry and quit |
| `<stage>-lives-poked` | the Wumpa plan's start | `Bandicoot Reserve` on the route's first extra life, then `Fruit Into Life` on the wrap | **Secondary evidence (RAM poke):** lives set to 98 (player and lives HUD), then the Wumpa route; later extra lives leave 99 |
| `<stage>-lives-cap-poked` | the Wumpa plan's start | `Fruit Into Life` only | **Secondary evidence (RAM poke):** lives set to 99; every extra life of the route leaves 99 |
| `<stage>-gem` | `<stage>-start` | the stage's achievement and its gem achievement, on Stage Clear (lid `0x2D`) | Replays `plans/<stage>-gem.json`, a clear with every box in one run; then as `<stage>-clear` |
| `<stage>-gem-poked` | `<stage>-start` | the stage's achievement and its gem achievement, on Stage Clear | **Secondary evidence (RAM poke):** the clearing plan with the box count set to the stage's boxes (`scenarios.STAGE_BOXES`, measured) before its last segment; the Stage Clear screen hands out the gem; then as `<stage>-clear` |
| `<stage>-one-box-short-poked` | `<stage>-start` | the stage's achievement only | **Secondary evidence (RAM poke):** the same with one box fewer: no gem |
| `<stage>-early-death-gem-poked` | `<stage>-early-death-restart` | the stage's achievement and its gem achievement, on Stage Clear | **Secondary evidence (RAM poke):** `plans/<stage>-early-death-clear.json`, a clear searched from the restart after a death before any checkpoint, with the box count set to the stage's boxes before its last segment: the game still hands out the gem; then as `<stage>-clear` |
| `<stage>-checkpoint-death` | `<stage>-start` | the stage's achievement on the switch to the map (lid `0x19`); `Beach Diet` on the clear (lid of the stage) for its stage, whose route picks up no Wumpa; never the gem | `plans/<stage>-checkpoint.json`, the death of `<stage>-checkpoint-respawn`, then `plans/<stage>-checkpoint-clear.json` from the checkpoint: the game skips Stage Clear after that death and goes straight to the map (game state `0x300`) |
| `<stage>-checkpoint-death-fruit-poked` | `<stage>-start` | the stage's achievement only | **Secondary evidence (RAM poke):** the same with one Wumpa set (player and Wumpa HUD) after the respawn, which the clear commits. Only for the stage `Beach Diet` names |
| `<stage>-timed-pause-quit` | `map` / `map-unlocked` | nothing; the stage's leaderboard canceled | The stage entered holding its heading from the frame its level loads: the leaderboard must start once, with Crash still on the ground until then and moving within 4 frames after; then the pause menu open 300 frames (left out of the time) and a quit. Only for a stage with a leaderboard |
| `<stage>-timed-clear` | `map` / `map-unlocked` | the stage's achievement on Stage Clear; its leaderboard submitted | The stage entered from the map, then as `<stage>-clear`: the submitted time must be the frames from the start to the win; the next stage's leaderboard, if any, canceled by its quit |
| `<stage>-timed-checkpoint-death` | `map` | as `<stage>-checkpoint-death`; the leaderboard submitted on the map | The stage entered from the map, then as `<stage>-checkpoint-death` without the state reload after the death, so the death stays in the timed run |
| `nsanity-beach-timed-game-over` | `map` | nothing; the leaderboard canceled | N. Sanity Beach entered from the map, then as `game-over`: one attempt through every death, canceled only by the game over |

Every scenario also lists its leaderboard attempts (`leaderboards`: per title, how each attempt
ends, `submitted`, `canceled`, `reset` by a state load, or still `running` at the end; the farming
plans' quit-and-reenter moves each play one, `scenarios.farming_attempts`) and the judge checks each
one: it must start on a frame where its stage's opening hands Crash to the player, before any
respawn and with no demo (`session.handovers`): an intro when the game state turns playing, a
spin-in when the same player object leaves its opening state (state flags bit 15,
`probes.NO_CONTROL_STATE_FLAG`); the value it last showed or submitted must equal the frames of play
since then (in a stage, game state playing, pause menu closed: `session.player_in_play`); a
submitted one must also equal the frames from its start to the frame the stage is won
(`session.wins`: the game state leaves playing for `0x500`, or `0x300` on the map path; no submitted
run opens the pause menu); a cancel must come with the game state quit (`0x400`) or game over
(`0x200`) and a submit on Stage Clear or the map. The verdict prints a line per attempt. The
independent evidence of the start frame is the movement measured by `<stage>-timed-pause-quit`.
`<stage>-start` states are saved inside a spin-in, so a scenario from one plays an attempt that
starts when it ends (`scenarios.opening_attempt`).

Every scenario also lists the rich presence strings the game must show on the way (`presence`,
regular expressions matched in full): the title and demo strings in `cold-boot`, `attract` and
`attract-then-new-game` (never a demo of the stage then played), the stage with a new game's 4
lives and then fewer in `<stage>-deaths`, `Game Over`, the island map, the Stage Clear screen and
the boss fight. Stage names in the patterns come from the level
achievements' titles or are spelled out, never from the script's own lookup. A scenario fails when
an expected string never shows, or when any string shows `[Unknown macro]` or `an unknown level` or
matches one of the scenario's `never` patterns (`0 lives` wherever the last life is never reached).
The verdict prints every change of the display string with its frame.

A `<stage>-clear` scenario exists only for a stage with a committed plan. Deaths come from seeded
random play of the stage's macros; before each one, the harness replays half the stage's clearing
plan, or its deepest plan, when one is committed, so the deaths happen mid-stage. A replay stops at
the death it runs into, and each death after a respawn replays the route again from its start.

The collectible scenarios exist only for a stage with the matching committed plan. The lives poke
writes a starting count, never the event: 99 lives are out of a searched run's reach, so the life
that reaches the cap is a real one the Wumpa route earns, and the scenarios are labelled as
secondary evidence wherever they are reported. The box count poke is the same kind: it writes the
count the Stage Clear screen judges, never the gem bit, which the game sets or not; a stage gets
the gem scenarios when it has a gem achievement and the plans they replay.

A new achievement needs a scenario that reaches its event and the look-alike events that must not
fire it; add it to `SCENARIOS` with the lid its event shows.

Outputs, per scenario (`<core>-` prefixed when not on pcsx_rearmed):

- `traces/<name>.csv`: one row per frame, the input mask and every probe, `rich_presence` (the
  display string on that frame; its changes are in the events log too), plus `achN_state` and
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

`explore.py STAGE` (a stage of `states.STAGES` or a boss fight of `states.BOSS_FIGHTS`) keeps an
archive of cells (the player's position and the goal's score), each with a compressed save state,
and plays random macros from the stage's start state (or `--from` another derivable state): half
of the rollouts start from one of the best cells (the frontier: highest score, then deepest, where
a timed obstacle is passed), the others from rarely chosen cells. The macros are the stage's
`plan.HEADINGS` set (`up`, `down` for Boulders, which runs towards the camera, `right` for The
Great Gate). The goal (`--goal`, `explore.GOALS`) decides when a rollout wins:

| Goal | Wins when | Score | Also |
| --- | --- | --- | --- |
| `clear` (default) | the game reports the stage cleared (`0x618D0` = `0x500`, or `0x300` after a death past a checkpoint, when Stage Clear is skipped; or the Stage Clear level) | none | |
| `no-wumpa` | the stage is cleared | none | collecting a Wumpa ends the rollout |
| `wumpa` | the player's Wumpa count goes down: it wrapped past 100 | the Wumpa count | farms |
| `aku` | Aku Aku holds three masks | the masks | farms |
| `gem` | the stage is cleared and the Stage Clear screen then hands out its gem (the bit of the stage under the map cursor, within 900 frames) | the boxes broken | a clear without the gem ends the rollout |
| `checkpoint` | a checkpoint crate is broken (`0x619A0` leaves -1) | none | |
| `boss` | the fight is won: the game state turns `0x300`, the fight leaving for the map (health 0 is not enough: a blast can take Crash with the boss and restart the fight) | the health lost (`probes.BOSS_HEALTH_CHAINS`) | |

A goal that farms also plays `quit-and-reenter` on about one segment in fifty: stand, pause, SELECT
and enter the stage again, which commits the counts and brings the crates back. The frames it took
are recorded into the plan's inputs, so the replay is still a plain input list. A death, another
level loading (a bonus round) or a quit that never reaches the map ends a rollout. The search stops
at the first win or when `--minutes` (default 45) run out, logging the archive size and the best
cell (with a screenshot) as it goes. A win writes `plans/<stage>-<goal>.json`; a failed `clear`
search writes its deepest alive route as `plans/<stage>-deepest.json` (`done: false`), which the
deaths scenario replays to die mid-stage; another failed goal writes nothing.
To search, or re-search a plan that stopped replaying (a new core build, a changed recipe):

```bash
python tools/achievement-harness/explore.py jungle-rollers
python tools/achievement-harness/states.py --fresh jungle-rollers-clear   # proves it replays
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
emu.write_u32(a, value)  # only to reach a stage (map-unlocked), never to fake an event
emu.deref(0x618A4, 0x6C, 0xE4, 0x0C)  # RA-style 24-bit pointer chain; None on a null hop
emu.screenshot(path)  # PNG of the last rendered frame
emu.snapshot() / restore(blob) / save_state(path) / load_state(path)  # loads reset triggers
emu.activate(id, mem_addr) / reset_achievement(id)  # reset: WAITING, zeroed hits
emu.activate_leaderboard(id, mem_addr)  # its LBOARD_* events come out of emu.events()
emu.achievement_state(id)  # 'waiting' | 'active' | 'primed' | 'triggered' | ...
emu.achievement_hits(id)  # [[(type, required, current, is_true), ...] per condset]
emu.events()  # [(frame, 'ACHIEVEMENT_TRIGGERED', id, value), ...]; LBOARD_* ids are leaderboards
emu.activate_rich_presence(script) / rich_presence()  # the display string of the last frame
emu.frame  # frames since boot or since the last state load
emu.core_version / emu.rcheevos_version / emu.options()
emu.frame_hooks.append(callable)  # called with emu after every frame
```

`states.load(emu, name)` derives or restores a state. `Session(name, state=None, core=...)` in
`session.py` wraps an `Emu` with every repo achievement, leaderboard and the rich presence active
and the tracer attached (`presence` lists every change of the display string; `leaderboard_events`
every `LeaderboardEvent`, with `clock`, a frame count that survives state loads, and `played`, the
frames of play so far; `handovers` the frames where a stage's opening handed Crash to the player;
`wins` the frames a stage was won);
helpers: `step`, `press`, `wait_until`, `shot`, `note`, `rearm`, `close` (returns every `Trigger`:
frame, title and the lid on that frame).
`navigation.py` holds the menu moves (`boot_to_map`, `move_cursor_to`, `enter_stage`,
`pause_and_quit`, `leave_stage_clear`).

## Probes

`probes.py` is the RAM map the traces record, with every address a named constant. `rXXXXX` /
`wXXXXX` are the raw 8-bit / 24-bit reads the repo's conditions make (`0xH`/`0xW`). `g_*` are the
engine's GOOL globals (global *n* at `0x6188C + 4n`) under their names in the c1 decompilation;
most are 24.8 fixed point, which is why the RA code notes point at odd bytes (`0x618ED` lives,
`0x61985` boxes, `0x619C5` stage). Object probes follow the Aku Aku, HUD and player pointers;
`player_fruit` and `player_lives` are the player object's live Wumpa and lives, which the HUD
digits only count up towards; `player_state_flags` its state flags, whose bit 15 marks the states
that open a stage before Crash can move.

## Caveats

- **One emulator per process.** libretro cores and the rcheevos shim keep global state;
  `scenarios.py` spawns one process per scenario, and a second `Emu()` in a process raises.
- **Determinism is a property of the core build.** Plans replay only on the pcsx_rearmed
  interpreter (`pcsx_rearmed_drc=disabled`, the default): its lightrec dynarec is not bit-exact
  after a state load. A new nightly core may change the emulation: when deriving
  a `<stage>-clear` state then times out waiting for Stage Clear, re-search the plan.
- **swanstation** derives the navigation states but cannot replay pcsx_rearmed plans, so
  the `<stage>-clear` scenarios, and `the-great-gate-deaths` (whose deaths need its route), are
  pcsx_rearmed only.
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
