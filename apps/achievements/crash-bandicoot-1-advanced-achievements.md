# Crash Bandicoot 1 — Advanced Achievements (Clear Gems, Papu Papu)

> **Addresses:** `apps/games/code-notes/crash-bandicoot-1.md` (RetroAchievements code notes for game 10434,
> corrected and extended by measurement). Engine globals, level ids and the respawn code: the **wurlyfox/c1**
> decompilation of Crash Bandicoot, <https://github.com/wurlyfox/c1> (`src/globals.h`, `src/common.h`,
> `src/level.c`). The gem bit layout matches DuckStation's all-gems cheat for SCUS-94900,
> <https://github.com/duckstation/chtdb/blob/master/cheats/SCUS-94900.cht>.
> **Condition syntax:** the vendored `ra-developer-docs/` in this directory.
> **Validated** in the headless harness (`tools/achievement-harness/`) against `SCUS-94900 — Crash
> Bandicoot (USA)`; see **Validation** for exactly what, how, and what still needs the in-game check.

Six achievements for completionist play, published as `community`. Titles and descriptions are our own.

| Title | Points | Unlocks when |
| --- | --- | --- |
| Shoreline Sparkle | 10 | the Stage Clear screen hands out the clear gem of N. Sanity Beach |
| Rolled Clean | 10 | … of Jungle Rollers |
| Gatekeeper's Gem | 15 | … of The Great Gate |
| Rock-Solid Gem | 25 | … of Boulders |
| Against the Current | 15 | … of Upstream |
| Chief Toppled | 10 | Papu Papu takes his last hit |

**One achievement per stage, not two.** The roadmap asked for an "all boxes in one pass" achievement and a
"gem: all boxes without dying" one. On the USA disc they are the same event: a death restarts the box count,
and after a death past a checkpoint the game skips the Stage Clear screen altogether (see **The mechanics**),
so every box has to go in one life, and the game hands out the gem exactly then. The gem bit is the game's own
verdict on that run.

## Seeding

`python manage.py seed_crash1_advanced_achievements` is idempotent and behaves like the other Crash seeds
(`crash-bandicoot-1-level-achievements.md`): a missing title is created (`community`, author `ra-import`), an
existing one, matched by title, gets the current `mem_addr` and description and keeps its status, points,
author and unlocks; two rows with one title fail the command without writing anything. The conditions are
built by the command's `build_gem_mem_addr` and `build_boss_mem_addr`; the harness imports them.

## The mechanics, as measured

| Thing | Where | Behaviour |
| --- | --- | --- |
| Box count | `0x61984` (24.8, integer at `0x61985`), c1 `box_count` | `+1` per box broken in the stage. **A death sets it back to 0** (after a checkpoint the checkpoint crate then counts again: 9 → 0 → 1 on the committed N. Sanity Beach route). A quit or a new level load also zeroes it. On the Stage Clear screen (`2d`) it is reused to count the missed boxes up, one per 18 frames |
| Boxes per stage | Stage Clear screen | N. Sanity Beach **49** (8 broken by the clearing plan + 41 missed), Jungle Rollers **38** (12 + 26). The other stages were not measured |
| Gem bits | `0x61988`… (c1 `item_pool1`) | Bit *n* + 1 is map stage *n* (`0x619c5`): N. Sanity Beach bit 1, Jungle Rollers bit 2, The Great Gate bit 3, Boulders bit 4, Upstream bit 5. The **Stage Clear screen** sets the bit about 280 frames after it loads, when the box count reached the stage's boxes ("PERFECT"); one short leaves it clear. It persists through the map and the next stages |
| Boss health | `0x60ddc` pointer, `+0x105` (24.8 at `+0x104`) | The boss object of a boss fight. Papu Papu starts at **3** and loses one per hit (3 → 2 → 1 → 0, then `ff` as the object winds down). A respawn allocates a new object at 3 (the pointer reads `0` for two frames). On other levels the pointer names other objects |
| A clear after a death past a checkpoint | `0x618d1`, `0x6188d` | The game state turns `03` instead of `05` and the stage goes **straight to the island map** (`09` → `19`, no Stage Clear screen, so no gem); the stage still counts as cleared (`0x61948` 1 → 2 on N. Sanity Beach). A death before any checkpoint restarts the stage (every box back, the count at 0, the respawn count `0x618a1` at 1 through Stage Clear), and its clear shows Stage Clear as usual and hands out the gem for every box (seen with the count poked) |
| Papu Papu's exit | `0x6188d`, `0x618d1` | After the last hit the game state turns `03` and the fight goes **straight to the island map** (`0a` → `19`, no Stage Clear screen), the cursor moving on to Rolling Stones |

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

### Papu Papu

```
<in_play()>_0xH6188d=h0a_0xW60ddc!=0_0xW60ddc=d0xW60ddc_I:0xW60ddc_0xH105=0_I:0xW60ddc_d0xH105=1
```

| Part | Meaning |
| --- | --- |
| `in_play()` | the collectible achievements' guard (`crash-bandicoot-1-collectible-achievements.md`): the player in control, no attract demo (Papu Papu has one), the level settled for 60 frames |
| `0xH6188d=h0a` | the level is the Papu Papu fight (c1 `LID_PAPUPAPU`) |
| `0xW60ddc!=0_0xW60ddc=d0xW60ddc` | a boss object exists and is the same one as on the previous frame, so a respawn's new object never compares with the old one |
| `I:0xW60ddc_0xH105=0_I:0xW60ddc_d0xH105=1` | its health went from 1 to 0: the last hit. AddAddress applies the pointer to both sides, so `d` reads the same object's previous value |

The win is the hit itself, not the exit: the exit to the map (`0a` → `19`) looks like a quit or a game over
apart from the game state, while the health reaching 0 happens nowhere else.

### Look-alikes

| Look-alike | Why nothing fires |
| --- | --- |
| Power-on, title, map, attract demos | gems need the Stage Clear level; the boss needs `in_play()` and the Papu Papu level |
| A clear with boxes missed | the Stage Clear screen leaves the gem bit clear |
| A death after a checkpoint, then the clear | the clear skips the Stage Clear screen: no gem, and the death reset the box count anyway |
| A stage whose gem is already won | the bit is already set: no edge |
| A memory card load or a password | gem bits change on the title level |
| A death in the boss fight with Papu Papu at 1 | the respawn brings a new boss object at 3 |
| A save state loaded after the event | every trigger is an edge |

## Validation

Syntax: `scripts/check-mem-addr.sh` accepts all six conditions; `pytest` runs it over every seeded condition.

Behaviour: the harness plays the real disc on `PCSX-ReARMed r26 ff81ed1` with every repo achievement active
in the vendored rcheevos 12.3 and judges every trigger: an expected achievement fires exactly once, on its
level; nothing else fires.

**Real play.**

| Scenario | What is played | Result |
| --- | --- | --- |
| `papu-papu-boss` | `plans/papu-papu-boss.json`, found by the harness's search (`explore.py papu-papu --goal boss`): three hits on Papu Papu (frames 258, 606, 1066); then a state saved after the hit is loaded, the fight returns to the map, and the fight is entered again and quit | `Chief Toppled` fires once, on the last hit (frame 1066, lid `0a`); nothing else fires |
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

**No-fire scenarios**, every one with these six achievements active: `cold-boot`, `attract` (15 minutes of demos,
Papu Papu's among them), `attract-then-new-game`, `game-over`, `<stage>-deaths` and `<stage>-quit` for the six
level-achievement stages, the level clears, the collectible scenarios and `papu-papu-quit`: none of them fires a
gem or the boss. Every scenario above is a test in `tools/achievement-harness/test_achievement_harness.py`.

### Still for the in-game check (DuckStation)

- **A real gem run**, on N. Sanity Beach at least: break all 49 boxes in one life and see `Shoreline Sparkle`
  pop on the Stage Clear screen with the gem, once. The harness only saw the gem from a poked box count.
- **A gem after a death before the first checkpoint**: die before any checkpoint crate, then break all 49
  boxes and finish; the game hands out the gem and `Shoreline Sparkle` pops (the harness saw it with the box
  count poked).
- **A death after the checkpoint**: break boxes, break the checkpoint crate, die, finish from the checkpoint;
  the stage goes straight to the map, no gem achievement pops, and the stage's level achievement does (the
  harness saw it on N. Sanity Beach).
- **The Great Gate, Boulders and Upstream** were never cleared in the harness: their gem bits (3, 4, 5) come
  from the code notes and DuckStation's all-gems cheat, which agree with the measured bits 1 and 2. Win each
  gem and see its achievement, and only its achievement, pop.
- **Papu Papu on DuckStation**: beat him and see `Chief Toppled` on the last hit; die with him at one health
  left and see nothing.
- **Bonus rounds inside a gem stage**: Jungle Rollers, The Great Gate and Upstream each have a Tawna bonus
  round (code notes, `0x6197c`), which no harness route entered. Win a gem through the bonus round and see its
  achievement pop; fall out of the bonus round, finish the stage, and see the achievement pop only if the
  Stage Clear screen still hands out the gem.
- **All six on DuckStation**, which runs rcheevos 12.4.0 with its own timing; the harness ran 12.3 on a
  libretro core.
