# Crash Bandicoot 1 — Level-Completion Achievements (Batch 1)

> **Addresses:** `apps/games/code-notes/crash-bandicoot-1.md` (RetroAchievements code notes for game 10434,
> corrected and extended). Level ids and engine globals: the **wurlyfox/c1** decompilation of Crash
> Bandicoot, <https://github.com/wurlyfox/c1> (`src/common.h` `LID_*`, `src/globals.h`, `src/main.c`).
> **Condition syntax:** the vendored `ra-developer-docs/` in this directory.
> **Validated** in the headless harness (`tools/achievement-harness/`) against `SCUS-94900 — Crash
> Bandicoot (USA)`; see **Validation** for exactly what, and what still needs the in-game check.

The "finish the level" achievements, 5 points each, created as `official` in the core set.

## Seeding

`python manage.py seed_crash1_level_achievements` is idempotent:

- a missing achievement is created in the core set (`official`, 5 points, type `progression`, author
  `ra-import`);
- an existing one, **matched by title** in the core set or the bonus subset (another subset of the game is
  left alone), moves to the core set and gets the current `mem_addr`, description and type, so a fixed
  condition reaches databases seeded earlier; its id, status, points, author and unlocks are left alone;
- two achievements with the same title make the command fail without writing anything.

Every Crash seed command (this one, `seed_crash1_collectible_achievements`,
`seed_crash1_advanced_achievements`, `seed_crash1_code_notes`, `seed_crash1_rich_presence` and
`seed_crash1_leaderboards`) first gets or creates the game with the hash of its only supported disc, so
`gameid` recognises it on a fresh database:

| MD5 (rcheevos PlayStation hash) | Label |
| --- | --- |
| `35386fd0891e594c9b6d8a4a5baa0027` | Crash Bandicoot (USA) — SCUS-94900 |

## Achievements

Every condition is `build_mem_addr(level_id)`; only the stage's level id changes.

| Title | Level id (`0x6188d`) | Map cursor (`0x619c5`) | `mem_addr` |
| --- | --- | --- | --- |
| N. Sanity Beach | `09` | `00` | `d0xH6188d=h09S0xH6188d=h2dS0xH6188d=h19_0xH618d1=3` |
| Jungle Rollers | `0c` | `01` | `d0xH6188d=h0cS0xH6188d=h2dS0xH6188d=h19_0xH618d1=3` |
| The Great Gate | `12` | `02` | `d0xH6188d=h12S0xH6188d=h2dS0xH6188d=h19_0xH618d1=3` |
| Boulders | `0e` | `03` | `d0xH6188d=h0eS0xH6188d=h2dS0xH6188d=h19_0xH618d1=3` |
| Upstream | `0f` | `04` | `d0xH6188d=h0fS0xH6188d=h2dS0xH6188d=h19_0xH618d1=3` |
| Rolling Stones | `15` | `06` | `d0xH6188d=h15S0xH6188d=h2dS0xH6188d=h19_0xH618d1=3` |
| Hog Wild | `11` | `07` | `d0xH6188d=h11S0xH6188d=h2dS0xH6188d=h19_0xH618d1=3` |
| Native Fortress | `1a` | `08` | `d0xH6188d=h1aS0xH6188d=h2dS0xH6188d=h19_0xH618d1=3` |
| Up the Creek | `18` | `09` | `d0xH6188d=h18S0xH6188d=h2dS0xH6188d=h19_0xH618d1=3` |
| The Lost City | `20` | `0b` | `d0xH6188d=h20S0xH6188d=h2dS0xH6188d=h19_0xH618d1=3` |
| Temple Ruins | `1c` | `0c` | `d0xH6188d=h1cS0xH6188d=h2dS0xH6188d=h19_0xH618d1=3` |
| Road to Nowhere | `14` | `0d` | `d0xH6188d=h14S0xH6188d=h2dS0xH6188d=h19_0xH618d1=3` |
| Boulder Dash | `13` | `0e` | `d0xH6188d=h13S0xH6188d=h2dS0xH6188d=h19_0xH618d1=3` |
| Sunset Vista | `23` | `0f` | `d0xH6188d=h23S0xH6188d=h2dS0xH6188d=h19_0xH618d1=3` |

The level ids are the c1 `LID_*` constants; the harness measured each one by entering the stage from the
map (`states.py` refuses a stage whose level id differs).

## Logic

`0x6188d` is byte 1 of GOOL global 0, c1 `cur_lid_ro` (`lid << 8`, written by `GoolInitLid`): the level file
the engine has loaded. Crash Bandicoot loads a separate level, `LID_LEVELEND` (`2d`), for the Stage Clear
screen that tallies the boxes. c1's `CoreLoop` forces `LID_TITLE` (`19`) on a game over, a continue and a
pause → quit; any other switch is requested by the level's own GOOL objects (`next_lid`), and the only one
ever seen loading `2d` is a stage's exit. A death respawns inside the same level.

A clear leaves the stage one of two ways. Normally the stage loads Stage Clear. After a death past a checkpoint
the game skips Stage Clear and loads the island map with game state `03` (c1 `GAME_STATE_CONTINUE`), the
stage still counted as cleared (`0x61948` rises; measured on N. Sanity Beach,
`crash-bandicoot-1-advanced-achievements.md`). A death before any checkpoint restarts the stage, and its clear
shows Stage Clear as usual. The condition has one alt group per way out:

| Group | Part | Meaning |
| --- | --- | --- |
| core | `d0xH6188d=h<id>` | on the previous frame the loaded level was this stage |
| alt 1 | `0xH6188d=h2d` | on this frame it is the Stage Clear screen |
| alt 2 | `0xH6188d=h19_0xH618d1=3` | on this frame it is the title/map level, and the game state says the level was won |

Each is true on exactly one frame: the one where the level switches from this stage to Stage Clear, or
straight to the map on a won stage (`ra-developer-docs/why-delta.md`: describe the moment the event happens,
not a state). Neither frame can occur on:

| Look-alike | What `0x6188d` does | Game state `0x618d1` |
| --- | --- | --- |
| Power-on (RAM zeroed) | `00` → `19` | `00` |
| Attract demos | `19` → demo stage → `19`; measured over 15 minutes, no demo ever loads `2d` | `06` on the way back |
| Death / respawn | unchanged | |
| Game over | stage → `19` | `02` |
| Pause → SELECT quit | stage → `19` | `04` |
| Stage Clear → map | `2d` → `19`, not from a stage | `03` |
| Papu Papu beaten | `0a` → `19`, not a stage of this set | `03` |
| Entering another stage | `19` → that stage's id | |

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
- **`0x618d1`** (game state) on alt 1: it reads `05` ("stage cleared") for about 90 frames before a real
  clear switches to `2d`. It would only guard a stage → `2d` switch that is not a clear, for which no path is
  known. Alt 2 needs it: a stage → `19` switch is also a game over or a quit.
- **`0x61a68`** ("finished/quit a level" in the code notes) is sound-library data.

## Validation

Syntax: `scripts/check-mem-addr.sh` (the vendored rcheevos parser) accepts every condition; `pytest`
runs it over every generated condition.

Behaviour: the harness plays the real disc on `pcsx_rearmed` (interpreter, deterministic) with every
achievement active in the vendored rcheevos runtime, and judges every trigger: an expected achievement must
fire exactly once, while the game shows the Stage Clear level `2d` (the map level `19` on a clear that skips
it), and nothing else may fire anything.
Each scenario is a test in `tools/achievement-harness/test_achievement_harness.py` (skipped without the disc).

Runs on `PCSX-ReARMed r26 ff81ed1` with the vendored rcheevos 12.3. Jungle Rollers to Rolling Stones are
reached by poking the map's unlocked-stage count (`0x61948`) and walking the map cursor there. Hog Wild to
Sunset Vista are reached with no write at all: the harness types the community's password for the
Koala Kong save point, `XOOOXSXS` (the map up to Koala Kong, no gem, no key; measured in
`crash-bandicoot-1-completion-inventory.md`), and walks the cursor back. Nothing writes a clear, a level id or
a game state.

| Scenario | What is played | Result |
| --- | --- | --- |
| `cold-boot` | 3 minutes from power-on, no input | nothing fires |
| `attract` | 15 minutes of attract demos from power-on (Jungle Rollers, The Great Gate, Boulders, Papu Papu, The Lost City, Jaws of Darkness, The Lab, and again) | nothing fires |
| `game-over` | N. Sanity Beach: deaths down to the game over and the title screen | nothing fires |
| `<stage>-deaths`, all fourteen stages | a death, a death with the achievements re-armed right after the respawn, a death after idling where the player respawned; each replays a plan first where one leads mid-stage | nothing fires |
| `<stage>-quit`, all fourteen stages | pause → SELECT right after control, after running and standing, after standing | nothing fires |
| `nsanity-beach-clear` | a real clear (`plans/nsanity-beach-clear.json`), then Stage Clear → map, Jungle Rollers entered and quit | N. Sanity Beach fires once, on the switch to `2d`; nothing else fires |
| `jungle-rollers-clear` | a real clear (`plans/jungle-rollers-clear.json`), then Stage Clear → map, The Great Gate entered and quit | Jungle Rollers fires once, on the switch to `2d`; nothing else fires |
| `nsanity-beach-checkpoint-death` | the checkpoint crate broken, a death, and a real clear from the checkpoint, which skips Stage Clear (game state `03`, `09` → `19`) | N. Sanity Beach fires once, on the switch to `19` (alt 2); no gem |

The same scenarios, except the clears and `the-great-gate-deaths` (plans replay only on the core they were
searched on), also pass on `SwanStation 1.0.0 b6c30a7`, the DuckStation fork, with a real NTSC-U BIOS.

The Go-Explore search (`explore.py`) found no clear of The Great Gate, Boulders, Upstream or Rolling Stones
within its time box of about 45 minutes of wall-clock search per stage or more, over two or three seeds. The
deepest route kept, 383 segments of 16 frames into The Great Gate, is `plans/the-great-gate-deepest.json`; the
search logs are not kept. For those four stages everything but the clear is validated: the level id the
condition names is measured on entry, and deaths and quits fire nothing. Hog Wild to Sunset Vista were not
searched for a clear (the user's decision: a stage clear ships on the builder proven on the first stages,
its measured level id and the look-alike scenarios); the same holds for them. Native Fortress, The Lost City and
Sunset Vista get their deaths mid-stage from a failed clear search's deepest route (`plans/<stage>-deepest.json`):
random play from their start dies too rarely.

### Still for the in-game check (DuckStation)

- **The Great Gate, Boulders, Upstream, Rolling Stones, Hog Wild, Native Fortress, Up the Creek, The Lost
  City, Temple Ruins, Road to Nowhere, Boulder Dash, Sunset Vista:** finish each stage and confirm its achievement pops on the Stage Clear screen, once. The harness never produced
  these clears.
- **All fourteen, on DuckStation:** the popup appears on the Stage Clear screen (not earlier, on the stage's
  exit), and a death, a pause → quit, a game over and leaving Stage Clear for the map unlock nothing.
- **A clear after a death past a checkpoint:** break a checkpoint crate, die, finish the stage; there is no
  Stage Clear screen, and the popup appears when the island map loads (alt 2). Seen in the harness on
  N. Sanity Beach only.
  DuckStation runs rcheevos 12.4.0 against its own CD timing; the harness ran 12.3 on libretro cores.
- **Load a save state taken inside a stage (softcore) and finish it:** the edge needs the stage's level id
  on the previous frame, which a state load inside the stage keeps; not exercised in the harness.
- **Bonus rounds:** c1 has separate bonus levels (`LID_BONUS*`), so entering and leaving a Tawna/Brio bonus
  round should switch the level id to the bonus level and back, firing nothing; the searches never entered
  one.
