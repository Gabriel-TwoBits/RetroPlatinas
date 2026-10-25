# Crash Bandicoot 1 — Advanced Achievements (Clear Gems, Bosses)

> **Addresses:** `apps/games/code-notes/crash-bandicoot-1.md` (RetroAchievements code notes for game 10434,
> corrected and extended by measurement). Engine globals, level ids and the respawn code: the **wurlyfox/c1**
> decompilation of Crash Bandicoot, <https://github.com/wurlyfox/c1> (`src/globals.h`, `src/common.h`,
> `src/level.c`). The gem bit layout matches DuckStation's all-gems cheat for SCUS-94900,
> <https://github.com/duckstation/chtdb/blob/master/cheats/SCUS-94900.cht>.
> **Condition syntax:** the vendored `ra-developer-docs/` in this directory.
> **Validated** in the headless harness (`tools/achievement-harness/`) against `SCUS-94900 — Crash
> Bandicoot (USA)`; see **Validation** for exactly what, how, and what still needs the in-game check.

The clear gems and the bosses, created as `official` in the core set: both are part of the game's own 100%.
Titles and descriptions are our own.

| Title | Points | Unlocks when |
| --- | --- | --- |
| Shoreline Sparkle | 10 | the Stage Clear screen hands out the clear gem of N. Sanity Beach |
| Rolled Clean | 10 | … of Jungle Rollers |
| Gatekeeper's Gem | 15 | … of The Great Gate |
| Rock-Solid Gem | 25 | … of Boulders |
| Against the Current | 15 | … of Upstream |
| Rubble Rouser | 15 | … of Rolling Stones |
| Hog-Tied Treasure | 15 | … of Hog Wild |
| Fortress Plundered | 25 | … of Native Fortress |
| Creek Clearer | 15 | … of Up the Creek |
| Verdant Relic | 25 | … of The Lost City: the green gem |
| Relic Hunter | 15 | … of Temple Ruins |
| Somewhere After All | 25 | … of Road to Nowhere |
| Outran the Rock | 25 | … of Boulder Dash |
| Dusk Collector | 25 | … of Sunset Vista |
| Chief Toppled | 10 | the fight won against Papu Papu returns to the map |
| Kangaroo Court | 10 | the fight won against Ripper Roo returns to the map |
| Koala Kayo | 10 | the fight won against Koala Kong returns to the map |
| Suit Pressed | 10 | the fight won against Pinstripe returns to the map |

**One achievement per stage, not two.** The roadmap asked for an "all boxes in one pass" achievement and a
"gem: all boxes without dying" one. Each stage gets one, on the game's own gem, which is the "one pass" rule:
after a death past a checkpoint the game skips the Stage Clear screen altogether, so no gem; a death before any
checkpoint restarts the stage with every box back and the count at 0, and the game still hands out the gem
for a full clear after it (see **The mechanics**). A stricter "no death at all" achievement cannot ride on the
gem bit: once the game hands out a gem after an early death, the bit never rises again on that save, so the
achievement would be locked out for good. The descriptions say "without dying past a checkpoint".

## Seeding

`python manage.py seed_crash1_advanced_achievements` is idempotent and behaves like the other Crash seeds
(`crash-bandicoot-1-level-achievements.md`): a missing title is created in the core set (`official`, author
`ra-import`), an existing one, matched by title in the core set or the bonus subset, moves to the core set and
gets the current `mem_addr`, description and type (standard, `""`, for the gems; `progression` for the boss)
and keeps its id, status, points, author and unlocks; two rows with one title fail the command without writing
anything. The conditions are built by the command's `build_gem_mem_addr` and `build_boss_mem_addr`; the
harness imports them.

## The mechanics, as measured

| Thing | Where | Behaviour |
| --- | --- | --- |
| Box count | `0x61984` (24.8, integer at `0x61985`), c1 `box_count` | `+1` per box broken in the stage. **A death sets it back to 0** (after a checkpoint the checkpoint crate then counts again: 9 → 0 → 1 on the committed N. Sanity Beach route). A quit or a new level load also zeroes it. On the Stage Clear screen (`2d`) it is reused to count the missed boxes up, one per 18 frames |
| Boxes per stage | Stage Clear screen | N. Sanity Beach **49** (8 broken by the clearing plan + 41 missed), Jungle Rollers **38** (12 + 26). The other stages were not measured |
| Gem bits | `0x61988`… (c1 `item_pool1`) | Bit *n* + 1 is map stage *n* (`0x619c5`): N. Sanity Beach bit 1, Jungle Rollers bit 2, The Great Gate bit 3, Boulders bit 4, Upstream bit 5, Rolling Stones bit 7; then `0x61989` bit 0 Hog Wild, bit 1 Native Fortress, bit 2 Up the Creek, bit 4 The Lost City (green), bit 5 Temple Ruins, bit 6 Road to Nowhere, bit 7 Boulder Dash; `0x6198a` bit 0 Sunset Vista. The **Stage Clear screen** sets the bit about 280 frames after it loads, when the box count reached the stage's boxes ("PERFECT"); one short leaves it clear. It persists through the map and the next stages |
| Boss health | `0x60ddc` pointer: Papu Papu's object, `+0x104` (24.8); Ripper Roo's is two pointers further (`+0x6c`, `+0x68`, then `+0x104`) | Papu Papu starts at **3** and loses one per hit (3 → 2 → 1 → 0, then `ff` as the object winds down). Ripper Roo starts at 3 too; his word holds `0x002` for one frame on each hit that does not end him. A death after his last health is lost, before the fight leaves (as when the arena's TNT catches Crash), restarts the fight at 3 (scenario `ripper-roo-death-after-last-hit`). A respawn allocates a new object. Koala Kong starts at **4**, read from `0x61898` → `+0x6c` → `+0x104` (code notes); his object reads `0` for a frame as Crash dies. Pinstripe starts at **6**, the `0x60ddc` object's `+0x104`. On other levels the pointers name other objects |
| A clear after a death past a checkpoint | `0x618d1`, `0x6188d` | The game state turns `03` instead of `05` and the stage goes **straight to the island map** (`09` → `19`, no Stage Clear screen, so no gem); the stage still counts as cleared (`0x61948` 1 → 2 on N. Sanity Beach). A death before any checkpoint restarts the stage (every box back, the count at 0, the respawn count `0x618a1` at 1 through Stage Clear), and its clear shows Stage Clear as usual and hands out the gem for every box (seen with the count poked) |
| A boss fight's exit | `0x6188d`, `0x618d1` | After the last hit the game state turns `03` and the fight goes **straight to the island map** (no Stage Clear screen; Papu Papu: last hit at frame 1066, game state `03` at 1354, `0a` → `19` at 1543; Ripper Roo: 1778, 2122, `17` → `19` at 2298; Pinstripe: 2712, 3084, `08` → `19` at 3275), the cursor moving on to the next stage |

## Logic

### Clear gems

```
0xH6188d=h2d_d0xH6188d=h2d_0xN61988=1_d0xN61988=0        (N. Sanity Beach, bit 1)
```

| Part | Meaning |
| --- | --- |
| `0xH6188d=h2d_d0xH6188d=h2d` | the Stage Clear level is loaded on this frame and the previous one |
| `0x<bit>addr=1_d0x<bit>addr=0` | the stage's gem bit rises on this frame (`0xN`…`0xR` are rcheevos' bit 1 to bit 5 reads) |

The bit is the event, so the condition fires once, on the frame the game awards the gem
(`ra-developer-docs/why-delta.md`). The level guard keeps every other way of setting gem bits out: a memory
card load and a password restore the gems on the title level (`19`).

### Bosses

```
d0xH6188d=h0a_0xH6188d=h19_0xH618d1=3        (Papu Papu, level 0a; Ripper Roo is 17)
```

| Part | Meaning |
| --- | --- |
| `d0xH6188d=h<fight>` | on the previous frame the loaded level was this boss fight |
| `0xH6188d=h19_0xH618d1=3` | on this frame it is the title/map level, and the game state says the level was won (c1 `GAME_STATE_CONTINUE`) |

The win is the fight's exit, the same alt 2 the stage clears use for a clear that skips Stage Clear. The boss's
health reaching 0 is not enough: on Ripper Roo the first searched win had Crash die near an exploding TNT
about 260 frames after the last hit, and a death after the health is gone, before the fight leaves, restarts
the fight (`ripper-roo-death-after-last-hit`); a condition on the health would fire on that lost fight. A quit
leaves with game state `04`, a game over with `02`, an attract demo of the fight with `06`; a death respawns
inside the fight.

### Look-alikes

| Look-alike | Why nothing fires |
| --- | --- |
| Power-on, title, map, attract demos | gems need the Stage Clear level; a boss needs its fight's level on the previous frame, and a demo returns to the title with game state `06` |
| A clear with boxes missed | the Stage Clear screen leaves the gem bit clear |
| A death after a checkpoint, then the clear | the clear skips the Stage Clear screen: no gem, and the death reset the box count anyway |
| A stage whose gem is already won | the bit is already set: no edge |
| A memory card load or a password | gem bits change on the title level |
| A death in a boss fight, the boss at 1 or taken down with Crash | the respawn stays in the fight: no level change |
| Pause → quit or game over in a boss fight | the fight leaves for the map with game state `04` or `02`, not `03` |
| A save state loaded after the event | every trigger is an edge |

## Validation

Syntax: `scripts/check-mem-addr.sh` accepts every condition; `pytest` runs it over every seeded condition.

Behaviour: the harness plays the real disc on `PCSX-ReARMed r26 ff81ed1` with every repo achievement active
in the vendored rcheevos 12.3 and judges every trigger: an expected achievement fires exactly once, on its
level; nothing else fires.

**Real play.**

| Scenario | What is played | Result |
| --- | --- | --- |
| `papu-papu-boss` | `plans/papu-papu-boss.json`, found by the harness's search (`explore.py papu-papu --goal boss`): three hits on Papu Papu (frames 258, 606, 1066), the fight leaving for the map; then a state saved on the map is loaded, and the fight is entered again and quit | `Chief Toppled` fires once, on the switch to the map (lid `19`); nothing else fires |
| `ripper-roo-boss` | `plans/ripper-roo-boss.json`, found by `explore.py ripper-roo --goal boss --seed 1` from `ripper-roo-start` (the map reached by the password `XOOOXSXS`, no RAM write): three hits (frames 206, 939, 1778), game state `03` at 2122, the switch to the map at 2298; then a state saved on the map is loaded, and the fight is entered again and quit | `Kangaroo Court` fires once, on the switch to the map (lid `19`); nothing else fires |
| `ripper-roo-deaths` | the same plan up to Ripper Roo's last health, then a death; a second death right after the respawn | nothing fires |
| `pinstripe-boss` | `plans/pinstripe-boss.json`, found by `explore.py pinstripe --goal boss --seed 1` from `pinstripe-start` (the map reached by the community's "skip to the third island" password, no RAM write): six hits (frames 120, 422, 796, 1286, 2106, 2712), game state `03` at 3084, the switch to the map at 3275; then the state load on the map, a re-entry and a quit | `Suit Pressed` fires once, on the switch to the map (lid `19`); nothing else fires |
| `pinstripe-deaths` | the same plan up to Pinstripe's last health, then a death; a second death right after the respawn | nothing fires |
| `ripper-roo-death-after-last-hit` | the same plan until Ripper Roo's health is 0 (frame 1778), then seeded random play dies before the fight leaves (frame 1906): the respawn restarts the fight, Ripper Roo back at 3 | nothing fires (a condition on the health would have fired at 1778) |
| `papu-papu-deaths` | the same plan up to Papu Papu's last health (frame 606), then a death; a second death right after the respawn | nothing fires |
| `nsanity-beach-checkpoint-death` | `plans/nsanity-beach-checkpoint.json` breaks the checkpoint crate (9 boxes counted), a death by seeded random play, then `plans/nsanity-beach-checkpoint-clear.json`, a clear searched from the checkpoint respawn (`explore.py nsanity-beach --from nsanity-beach-checkpoint-respawn`) | the stage ends on game state `03` and goes straight to the map, no Stage Clear screen, gem bit clear; no gem or boss achievement fires (the level achievement and `Beach Diet` do, through their alt groups for this exit) |

**Secondary evidence (RAM poke).** No search reached every box of a stage: the box-aware search of
N. Sanity Beach (`explore.py nsanity-beach --goal gem`, which scores the boxes broken alive and wins only on a
clear the game rewards with the gem) peaked at 24 of 49 boxes in a 120-minute run (seed 3) and at 28 in a
36-minute one (seed 1). So the box count is poked, never the gem: the clearing plan of the stage is replayed,
the count is set before its last segment, and the Stage Clear screen decides.

| Scenario | Poke | Result |
| --- | --- | --- |
| `nsanity-beach-gem-poked` | 49 boxes | `Shoreline Sparkle` once, when the Stage Clear screen sets bit 1 (frame 7407, lid `2d`, 280 frames after it loads); `N. Sanity Beach` on the switch to `2d` |
| `jungle-rollers-gem-poked` | 38 boxes | `Rolled Clean` once, when the screen sets bit 2 (frame 12816, lid `2d`) |
| `nsanity-beach-one-box-short-poked`, `jungle-rollers-one-box-short-poked` | 48, 37 | no gem, no gem achievement |
| `nsanity-beach-early-death-gem-poked` | 49 boxes, on `plans/nsanity-beach-early-death-clear.json`, a clear searched from the restart after a death before any checkpoint (`explore.py nsanity-beach --from nsanity-beach-early-death-restart --seed 5`) | `Shoreline Sparkle` once, on the Stage Clear screen (lid `2d`): the early death does not stop the gem |

**No-fire scenarios**, every one with these achievements active: `cold-boot`, `attract` (15 minutes of demos, Papu
Papu's among them), `attract-then-new-game`, `game-over`, `<stage>-deaths` and `<stage>-quit` for every
level-achievement stage, the level clears, the collectible scenarios, `password-all-gems` (the 100% password typed
from the title menu sets all 26 gem bits on the title level) and `<boss>-quit` for every boss and `<boss>-deaths`
for every boss with a searched win: none of them fires a gem or a boss. Every scenario above is a test in
`tools/achievement-harness/test_achievement_harness.py`.

### Still for the in-game check (DuckStation)

- **A real gem run**, on N. Sanity Beach at least: break all 49 boxes in one life and see `Shoreline Sparkle`
  pop on the Stage Clear screen with the gem, once. The harness only saw the gem from a poked box count.
- **A gem after a death before the first checkpoint**: die before any checkpoint crate, then break all 49
  boxes and finish; the game hands out the gem and `Shoreline Sparkle` pops (the harness saw it with the box
  count poked).
- **A death after the checkpoint**: break boxes, break the checkpoint crate, die, finish from the checkpoint;
  the stage goes straight to the map, no gem achievement pops, and the stage's level achievement does (the
  harness saw it on N. Sanity Beach).
- **The Great Gate to Sunset Vista** (every gem stage but N. Sanity Beach and Jungle Rollers) were never
  cleared in the harness: their gem bits come from the bit-per-stage rule, which the 100% password confirms
  (it sets exactly these bits among the 26), and agree with the measured bits 1 and 2. Rolling Stones, Native
  Fortress, Road to Nowhere and Boulder Dash need a coloured gem's path first (blue, red, red, purple). Win each
  gem and see its achievement, and only its achievement, pop.
- **Papu Papu, Ripper Roo, Koala Kong and Pinstripe on DuckStation**: beat each and see the achievement pop when
  the map appears; die with the boss at one health left (on Ripper Roo, also after his last hit, before the map
  appears) and see nothing.
- **Bonus rounds inside a gem stage**: Jungle Rollers, The Great Gate and Upstream each have a Tawna bonus
  round (code notes, `0x6197c`), which no harness route entered. Win a gem through the bonus round and see its
  achievement pop; fall out of the bonus round, finish the stage, and see the achievement pop only if the
  Stage Clear screen still hands out the gem.
- **All of them on DuckStation**, which runs rcheevos 12.4.0 with its own timing; the harness ran 12.3 on a
  libretro core.
