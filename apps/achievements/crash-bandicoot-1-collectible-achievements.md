# Crash Bandicoot 1 — Collectible Achievements (Wumpa, Lives, Aku Aku)

> **Addresses:** `apps/games/code-notes/crash-bandicoot-1.md` (RetroAchievements code notes for game 10434,
> corrected and extended by measurement). Engine globals and game states: the **wurlyfox/c1** decompilation of
> Crash Bandicoot, <https://github.com/wurlyfox/c1> (`src/globals.h`, `src/level.c`).
> **Condition syntax:** the vendored `ra-developer-docs/` in this directory.
> **Validated** in the headless harness (`tools/achievement-harness/`) against `SCUS-94900 — Crash
> Bandicoot (USA)`; see **Validation** for exactly what, how, and what still needs the in-game check.

Four achievements about the things Crash picks up, created as `official`. Titles and descriptions are our
own.

| Title | Set | Points | Unlocks when |
| --- | --- | --- | --- |
| Fruit Into Life | core | 5 | the Wumpa count passes 100 and turns into an extra life |
| Mask Stack | core | 10 | Aku Aku gets his third mask at once (Crash turns invincible) |
| Bandicoot Reserve | Bonus subset | 10 | the lives reach 99, the most the game holds |
| Beach Diet | Bonus subset | 10 | N. Sanity Beach is finished without picking up a single Wumpa |

**Sets.** The core set holds what any player meets on the way to the game's own 100%: Wumpa turn into lives
and Aku Aku stacks up by themselves. `Bandicoot Reserve` (a grind) and `Beach Diet` (a self-imposed restriction)
are challenges beyond it, so they live in the `bonus` subset titled `Bonus` (the game
`Crash Bandicoot [Subset - Bonus]`), which a player opts into on the game page. Every subset is off until then.

## Seeding

`python manage.py seed_crash1_collectible_achievements` is idempotent and behaves like the level seed
(`crash-bandicoot-1-level-achievements.md`). It first gets or creates the bonus subset (`seed_crash1_bonus_subset`
in `apps/achievements/management/crash1.py`: parent the core game, type `bonus`, title `Bonus`, no disc hash
of its own; the emulator loads it with the core game's disc). A missing title is then created in its set
(`official`, author `ra-import`); an existing one, matched by title in any set of the game, moves to its set
and gets the current `mem_addr`, description and type (standard, `""`), keeping its id, status, points, author
and unlocks, so a database seeded before the split gets the two challenges moved, not duplicated; their
unlockers get a play record of the subset, as an award records one, so its rarity counts them. Two rows
with one title in the game's sets fail the command without writing anything. Every Crash achievement seed
shares `upsert_achievements` in `apps/achievements/management/crash1.py`; `BONUS_SUBSET_TITLES` in the command
picks the set. The conditions are built by the command's
`build_*_mem_addr` functions; the harness imports them, so it tests the strings the server serves.

## The mechanics, as measured

Every number below was measured in the harness on the real disc, not taken from a wiki.

| Thing | Where | Behaviour |
| --- | --- | --- |
| Wumpa | player object `+0x160` (24.8), read as `I:0xW566b4_0xH161` | Counts up as fruit lands, several on one frame (+6 from one crate). Passing 100 subtracts 100 (95 + 6 → 1) and an extra life lands about 110 frames later. Deaths and checkpoints never lower it. The HUD digits (`0x618a4` chain) only count up towards it, one fruit per 8 frames |
| Lives | player object `+0x164` (24.8), read as `I:0xW566b4_0xH165` | **Capped at 99**: an extra life at 99 leaves 99, and the next extra life clamps a value above 99 back to 99 (measured with a RAM poke, see **Validation**). 100 lives cannot be reached |
| Aku Aku | Aku object `+0x188` (24.8), read as `I:0xW618cc_0xH189` | `0` no mask, `1`–`3` masks. The first mask spawns him at `1`; the third turns Crash invincible. A death clears every mask |
| Committed counts | `0x618ed` lives · `0x618f1` masks · `0x618f5` Wumpa | Written from the player when a stage is cleared (the frame game state `0x618d1` becomes `05`, or `03` on a clear after a death past a checkpoint) and on a pause → quit, and handed to the player when the next stage starts. So a quit keeps the fruit and masks collected, and the stage's crates come back on re-entry |
| Game state | `0xH618d1` | `01` while the player plays a stage, but also while an attract demo plays (with `0x61a30` non-zero); `05` from the frame a stage is cleared; `03` instead when a death past a checkpoint makes the clear skip Stage Clear and go straight to the map |

**Why "Bandicoot Reserve" and not "100 lives":** the roadmap asked for 100 lives, which the counter cannot hold.
99 is the game's own ceiling, so the achievement asks for it and fires on the rise to 99.

## Logic

### The in-play guard

`Fruit Into Life`, `Mask Stack` and `Bandicoot Reserve` read counters of the player and Aku Aku objects, which are
reallocated on every level load and hold leftovers of the previous level for a few frames (a re-entered stage
showed `0x3f0017` Wumpa on its first frame, and Aku Aku at 3 masks for 21 frames before the committed 2). They
share one guard, `in_play()`:

| Part | Excludes |
| --- | --- |
| `0xH618d1=1` | menus, cutscenes, the game over, a clear in progress, a demo's last frames (`06`) |
| `0xH61a30=0` | an attract demo, which plays real stages with game state `01` |
| `0xH6188d!=h19_0xH6188d!=h2d` | the title / island map level and the Stage Clear screen, where the player pointer names other objects |
| `0xW566b4!=0_0xW566b4=d0xW566b4` | a freed player object (pause → quit, the end of a stage), and the frame the pointer moves, so a delta through it compares one object with itself |
| `R:0xH6188d!=d0xH6188d_0xH6188d=0xH6188d.60.` | the first 60 frames of any level: every hit resets on a level change, and the level must then hold 60 frames (the rich presence counts use the same settle) |

TRADEOFF: an event in the first 60 frames of a level (a stage, a bonus round, back from one) does not count; the
next one does.

### The triggers

Each fires on the single frame its event happens (`ra-developer-docs/why-delta.md`); AddAddress applies the
pointer to both sides of a comparison, so `d` reads the same object's previous value.

| Title | Trigger after `in_play()` | Event |
| --- | --- | --- |
| Fruit Into Life | `I:0xW566b4_0xH161<d0xH161` | the Wumpa count went down: it passed 100. Nothing else lowers it |
| Bandicoot Reserve | `I:0xW566b4_0xH165=99_I:0xW566b4_d0xH165<99` | the lives rose to 99. At the cap an extra life changes nothing, so it cannot fire twice in a row |
| Mask Stack | `0xW618cc=d0xW618cc_I:0xW618cc_0xH189=3_I:0xW618cc_d0xH189<3` | Aku Aku reached three masks from fewer (two can land on one game tick), the Aku object unchanged |

TRADEOFF: a 99th life that lands after the guard closes at the end of a stage (a wrap's extra life lands about
110 frames after the wrap, and the player pointer is freed before Stage Clear) is missed, and the next stage starts
at 99, so `Bandicoot Reserve` waits for a life lost and earned back. Accepting the committed lives (`0x618ed`)
rising to 99 as an alternative trigger would cover it, once measured.

`Beach Diet` needs no object: the clear commits the player's Wumpa into `0x618f5` on the very frame the game
state becomes `05`, or `03` on a clear that skips Stage Clear after a death past a checkpoint (both measured),
so comparing the committed count with its previous frame compares the count at the clear with the count the
stage started with.

```
0xH61a30=0_0xH6188d=h09_d0xH618d1=1_0xH618f5=d0xH618f5S0xH618d1=5S0xH618d1=3
```

| Group | Part | Meaning |
| --- | --- | --- |
| core | `0xH61a30=0` | not an attract demo (no demo was ever seen clearing a stage; kept as a guard) |
| core | `0xH6188d=h09` | the stage is N. Sanity Beach |
| core | `d0xH618d1=1` | the player was playing on the previous frame |
| core | `0xH618f5=d0xH618f5` | the clear committed the same Wumpa count the stage started with |
| alt 1 | `0xH618d1=5` | the stage is cleared, Stage Clear next |
| alt 2 | `0xH618d1=3` | the stage is cleared after a death past a checkpoint, the map next (inside a stage, `03` means nothing else: a quit is `04`, a game over `02`) |

TRADEOFF: exactly 100 Wumpa collected in one run also commits an unchanged count; telling it apart would need the
lives, which a death on the same run changes too. A quit commits the fruit collected so far, so a run counts from
the last entry: quitting and finishing a fresh run without fruit earns it, as it should.

### Look-alikes

| Look-alike | Why nothing fires |
| --- | --- |
| Power-on, boot logos, title, map | game state is not `01`, or the level is `19` |
| Attract demos | `0x61a30` is non-zero for every demo frame with game state `01` |
| Level load (leftover counters) | the 60-frame settle |
| Death / respawn | Wumpa and lives never rise on a death, masks only fall; `Beach Diet` needs game state `05` or `03` |
| Pause → quit, game over | game state leaves `01`, the player pointer is freed, the level changes |
| Loading a save state after the event | every trigger is an edge: the loaded frame repeats nothing |
| Stage Clear screen | the level is `2d` |

## Validation

Syntax: `scripts/check-mem-addr.sh` accepts all four conditions; `pytest` runs it over every seeded condition.

Behaviour: the harness plays the real disc on `PCSX-ReARMed r26 ff81ed1` with every repo achievement (the six
level ones and these four) and the rich presence active in the vendored rcheevos 12.3, and judges every trigger:
an expected achievement fires exactly once, on its level; nothing else fires.

**Real play.** The routes were found by the harness's Go-Explore search (`explore.py --goal`), which may also
quit from the pause menu and re-enter the stage, the way a player farms crates; the plans record the inputs.

| Scenario | What is played | Result |
| --- | --- | --- |
| `nsanity-beach-no-wumpa` | `plans/nsanity-beach-no-wumpa.json`: N. Sanity Beach finished without a Wumpa (8704 frames, the player's count 0 throughout), then Stage Clear → map, Jungle Rollers entered and quit | `Beach Diet` fires once, on the clear (frame 8700, lid `09`); `N. Sanity Beach` fires on Stage Clear (lid `2d`) |
| `nsanity-beach-clear` | the level achievement's clear, 20 Wumpa collected | `Beach Diet` does not fire |
| `nsanity-beach-checkpoint-death` | the checkpoint route, a death, and the clear from the checkpoint, which skips Stage Clear (`crash-bandicoot-1-advanced-achievements.md`); no Wumpa picked up | `Beach Diet` fires once, on the clear (frame 3690, game state `03`, lid `09`); `N. Sanity Beach` fires on the switch to the map (lid `19`) |
| `nsanity-beach-aku` | from `nsanity-beach-two-masks` (two masks farmed from the stage's first Aku Aku crate by replaying the clearing route to it, quitting and re-entering, twice), `plans/nsanity-beach-aku.json` breaks the crate a third time; then a state saved after the event is loaded, and the stage is quit, re-entered with the three masks committed, and quit | `Mask Stack` fires once, on the frame Aku Aku goes 2 → 3 (lid `09`); the state load and the re-entry (Aku Aku back to 2 after holding 3 for 21 frames) fire nothing |
| `nsanity-beach-wumpa` | from `nsanity-beach-farmed-wumpa` (36 Wumpa: twice, the clearing route up to its 20th fruit, a quit and a re-entry), `plans/nsanity-beach-wumpa.json` farms the stage with 46 more quits and re-entries (104367 frames) until the count goes 99 → 0 → 2; then the state load, the quit and the re-entry | `Fruit Into Life` fires once, on the wrap (frame 104352, lid `09`); the extra life lands 106 frames later; nothing fires after |

**Secondary evidence (RAM poke).** 99 lives are out of a searched run's reach, so two scenarios set the player's
lives (and the lives HUD, so the run keeps its timing; it replays to the same wrap frame) before replaying the
Wumpa route. Only the starting count is poked; the extra lives are the real ones the route earns: a life crate at
frame 4249 and the wrap's.

| Scenario | Poke | Result |
| --- | --- | --- |
| `nsanity-beach-lives-poked` | 98 lives | `Bandicoot Reserve` once, on the life crate (98 → 99, frame 4249); the wrap's extra life leaves 99 and fires nothing; `Fruit Into Life` on the wrap |
| `nsanity-beach-lives-cap-poked` | 99 lives | `Fruit Into Life` only: both extra lives leave 99 |
| `nsanity-beach-checkpoint-death-fruit-poked` | 1 Wumpa, after the respawn at the checkpoint | the clear commits it (`0x618f5` 0 → 1 on the frame game state turns `03`); `Beach Diet` does not fire; `N. Sanity Beach` does |

The cap itself was measured the same way, before writing the condition, on the clearing route of N. Sanity Beach
with its Wumpa poked to 95: lives poked to 99 stayed 99 through the wrap's extra life, and lives poked to 150
dropped to 99 on it.

**No-fire scenarios**, every one with these four achievements active: `cold-boot`, `attract` (15 minutes of
demos), `attract-then-new-game`, `game-over`, `<stage>-deaths` and `<stage>-quit` for the six level-achievement
stages, the two level clears and `papu-papu-quit`. None fires a collectible achievement.

### Still for the in-game check (DuckStation)

- **Bandicoot Reserve** was only seen firing from poked lives: reach 99 lives (or poke 98 in softcore) and earn
  one more; then earn another at 99 and see nothing more.
- **All four on DuckStation**, which runs rcheevos 12.4.0 with its own timing; the harness ran 12.3 on a libretro
  core.
- **Beach Diet must not fire with fruit:** clear N. Sanity Beach after picking up Wumpa and see nothing. The
  condition needs the clear's game state and Wumpa commit on one evaluated frame, as they are on PCSX-ReARMed;
  a different frame split on DuckStation would unlock it falsely, which a check for the unlock alone cannot see.
- **Beach Diet after a death past the checkpoint:** break the checkpoint crate without fruit, die, finish
  without fruit (no Stage Clear screen) and see it pop; the harness saw it with no fruit, and saw the fruit case
  only from a poked Wumpa count.
- **Fruit and masks in other stages, bonus rounds and boss fights:** only N. Sanity Beach was played. A bonus
  round loads its own level, so an event in its first 60 frames does not count; whether entering or leaving one
  commits the counts was not measured (N. Sanity Beach has no bonus round, so `Beach Diet` is unaffected).
- **The end of invincibility** (Aku Aku 3 → 2 inside a stage) was not reached in the harness runs; it is a fall
  and cannot fire anything.
- **A memory card load** with 99 lives or masks: the edges need a rise during play, so nothing should fire.
