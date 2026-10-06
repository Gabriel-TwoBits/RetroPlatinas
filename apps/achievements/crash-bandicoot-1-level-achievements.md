# Crash Bandicoot 1 — Level-Completion Achievements (Batch 1)

> **Addresses:** `apps/games/code-notes/crash-bandicoot-1.md` (RetroAchievements code notes for game 10434,
> corrected and extended). Level ids and engine globals: the **wurlyfox/c1** decompilation of Crash
> Bandicoot, <https://github.com/wurlyfox/c1> (`src/common.h` `LID_*`, `src/globals.h`, `src/main.c`).
> **Condition syntax:** the vendored `ra-developer-docs/` in this directory.
> **Validated** in the headless harness (`tools/achievement-harness/`) against `SCUS-94900 — Crash
> Bandicoot (USA)`; see **Validation** for exactly what, and what still needs the in-game check.

The first six "finish the level" achievements, 5 points each, published as `community`.

## Seeding

`python manage.py seed_crash1_level_achievements` is idempotent:

- a missing achievement is created (`community`, 5 points, author `ra-import`);
- an existing one, **matched by title** within the Crash game, gets the current `mem_addr` and description,
  so a fixed condition reaches databases seeded earlier; its status, points, author and unlocks are left
  alone;
- two achievements with the same title make the command fail without writing anything.

Every Crash seed command (this one, `seed_crash1_collectible_achievements`,
`seed_crash1_advanced_achievements`, `seed_crash1_code_notes` and `seed_crash1_rich_presence`) first gets or
creates the game with the hash of its only supported disc, so `gameid` recognises it on a fresh database:

| MD5 (rcheevos PlayStation hash) | Label |
| --- | --- |
| `35386fd0891e594c9b6d8a4a5baa0027` | Crash Bandicoot (USA) — SCUS-94900 |

## Achievements

Every condition is `build_mem_addr(level_id)`; only the stage's level id changes.

| Title | Level id (`0x6188d`) | Map cursor (`0x619c5`) | `mem_addr` |
| --- | --- | --- | --- |
| N. Sanity Beach | `09` | `00` | `0xH6188d=h2d_d0xH6188d=h09` |
| Jungle Rollers | `0c` | `01` | `0xH6188d=h2d_d0xH6188d=h0c` |
| The Great Gate | `12` | `02` | `0xH6188d=h2d_d0xH6188d=h12` |
| Boulders | `0e` | `03` | `0xH6188d=h2d_d0xH6188d=h0e` |
| Upstream | `0f` | `04` | `0xH6188d=h2d_d0xH6188d=h0f` |
| Rolling Stones | `15` | `06` | `0xH6188d=h2d_d0xH6188d=h15` |

The level ids are the c1 `LID_*` constants; the harness measured each one by entering the stage from the
map (`states.py` refuses a stage whose level id differs).

## Logic

`0x6188d` is byte 1 of GOOL global 0, c1 `cur_lid_ro` (`lid << 8`, written by `GoolInitLid`): the level file
the engine has loaded. Crash Bandicoot loads a separate level, `LID_LEVELEND` (`2d`), for the Stage Clear
screen that tallies the boxes. c1's `CoreLoop` forces `LID_TITLE` (`19`) on a game over, a continue and a
pause → quit; any other switch is requested by the level's own GOOL objects (`next_lid`), and the only one
ever seen loading `2d` is a stage's exit. A death respawns inside the same level.

| Part | Meaning |
| --- | --- |
| `0xH6188d=h2d` | the loaded level is the Stage Clear screen on this frame |
| `d0xH6188d=h<id>` | and on the previous frame it was this stage |

Together they are true on exactly one frame: the one where the level switches from this stage to Stage
Clear (`ra-developer-docs/why-delta.md`: describe the moment the event happens, not a state). That frame
cannot occur on:

| Look-alike | What `0x6188d` does |
| --- | --- |
| Power-on (RAM zeroed) | `00` → `19` |
| Attract demos | `19` → demo stage → `19`; measured over 15 minutes, no demo ever loads `2d` |
| Death / respawn | unchanged |
| Game over | stage → `19` |
| Pause → SELECT quit | stage → `19` |
| Stage Clear → map | `2d` → `19` |
| Entering another stage | `19` → that stage's id |

The constants carry rcheevos' `h` prefix: a bare `0x2d` is a memory read, not the number `0x2d`.

### Signals left out on purpose

- **`0x61998`** is the engine's `is_first_zone`, not a results flag: it rises on every level load and every
  respawn. Its edge fired the achievements on deaths, on pause → quit and on the title screen when an attract
  demo handed back to it.
- **`0x618cc`** (Aku Aku pointer) is null only until the first level loads after power-on and is never
  cleared afterwards, so it cannot tell a stage from the map, and a `ResetIf` on it never fires.
- **`0x61a30`** (attract-demo playback, c1 `pbak_state`) is non-zero while a demo plays but is back to `00`
  about 15–18 frames **before** the demo's level switches back to the title, so it would be `00` on any
  switch frame; and no demo loads `2d`.
- **`0x618d1`** (game state) reads `05` ("stage cleared") for about 90 frames before a real clear switches to
  `2d`. It would only guard a stage → `2d` switch that is not a clear, for which no path is known, at the
  cost of a second address per condition.
- **`0x61a68`** ("finished/quit a level" in the code notes) is sound-library data.

## Validation

Syntax: `scripts/check-mem-addr.sh` (the vendored rcheevos parser) accepts all six conditions; `pytest`
runs it over every generated condition.

Behaviour: the harness plays the real disc on `pcsx_rearmed` (interpreter, deterministic) with all six
achievements active in the vendored rcheevos runtime, and judges every trigger: an expected achievement must
fire exactly once, while the game shows the Stage Clear level `2d`, and nothing else may fire anything.
Each scenario is a test in `tools/achievement-harness/test_achievement_harness.py` (skipped without the disc).

Runs on `PCSX-ReARMed r26 ff81ed1` with the vendored rcheevos 12.3. Stages other than N. Sanity Beach are
reached by poking the map's unlocked-stage count (`0x61948`) and walking the map cursor there; nothing
writes a clear, a level id or a game state.

| Scenario | What is played | Result |
| --- | --- | --- |
| `cold-boot` | 3 minutes from power-on, no input | nothing fires |
| `attract` | 15 minutes of attract demos from power-on (Jungle Rollers, The Great Gate, Boulders, Papu Papu, The Lost City, Jaws of Darkness, The Lab, and again) | nothing fires |
| `game-over` | N. Sanity Beach: deaths down to the game over and the title screen | nothing fires |
| `<stage>-deaths`, all six stages | a death, a death with the achievements re-armed right after the respawn, a death after idling where the player respawned; each replays a plan first where one leads mid-stage | nothing fires |
| `<stage>-quit`, all six stages | pause → SELECT right after control, after running and standing, after standing | nothing fires |
| `nsanity-beach-clear` | a real clear (`plans/nsanity-beach-clear.json`), then Stage Clear → map, Jungle Rollers entered and quit | N. Sanity Beach fires once, on the switch to `2d`; nothing else fires |
| `jungle-rollers-clear` | a real clear (`plans/jungle-rollers-clear.json`), then Stage Clear → map, The Great Gate entered and quit | Jungle Rollers fires once, on the switch to `2d`; nothing else fires |

The same scenarios, except the clears and `the-great-gate-deaths` (plans replay only on the core they were
searched on), also pass on `SwanStation 1.0.0 b6c30a7`, the DuckStation fork, with a real NTSC-U BIOS.

The Go-Explore search (`explore.py`) found no clear of The Great Gate, Boulders, Upstream or Rolling Stones
within its time box of about 45 minutes of wall-clock search per stage or more, over two or three seeds. The
deepest route kept, 383 segments of 16 frames into The Great Gate, is `plans/the-great-gate-deepest.json`; the
search logs are not kept. For those four stages everything but the clear is validated: the level id the
condition names is measured on entry, and deaths and quits fire nothing.

### Still for the in-game check (DuckStation)

- **The Great Gate, Boulders, Upstream, Rolling Stones:** finish each stage and confirm its achievement
  pops on the Stage Clear screen, once. The harness never produced these clears.
- **All six, on DuckStation:** the popup appears on the Stage Clear screen (not earlier, on the stage's
  exit), and a death, a pause → quit, a game over and leaving Stage Clear for the map unlock nothing.
  DuckStation runs rcheevos 12.4.0 against its own CD timing; the harness ran 12.3 on libretro cores.
- **Load a save state taken inside a stage (softcore) and finish it:** the edge needs the stage's level id
  on the previous frame, which a state load inside the stage keeps; not exercised in the harness.
- **Bonus rounds:** c1 has separate bonus levels (`LID_BONUS*`), so entering and leaving a Tawna/Brio bonus
  round should switch the level id to the bonus level and back, firing nothing; the searches never entered
  one.
