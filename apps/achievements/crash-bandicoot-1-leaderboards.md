# Crash Bandicoot 1 — Fastest-Clear Leaderboards

> **Addresses:** `apps/games/code-notes/crash-bandicoot-1.md` (RetroAchievements code notes for game 10434,
> corrected and extended by measurement). Engine globals, level ids, the game states and the GOOL object
> layout: the **wurlyfox/c1** decompilation of Crash Bandicoot, <https://github.com/wurlyfox/c1>
> (`src/globals.h`, `src/common.h`, `src/gool.h`, `src/main.c`).
> **Leaderboard syntax and runtime:** the vendored `ra-developer-docs/` in this directory (`leaderboards.md`,
> `value-definition.md`, `flags/pauseif.md`) and rcheevos' `rc_evaluate_lboard` (`vendor/rcheevos`,
> `src/rcheevos/lboard.c`).
> **Validated** in the headless harness (`tools/achievement-harness/`) against `SCUS-94900 — Crash
> Bandicoot (USA)`; see **Validation** for exactly what, and what still needs the in-game check.

Two time trials, one per stage whose clear the harness plays. Titles and descriptions are our own.

| Title | Stage | Level id (`0x6188d`) | Format | Lower is better |
| --- | --- | --- | --- | --- |
| N. Sanity Beach — Fastest Clear | N. Sanity Beach | `09` | `FRAMES` | yes |
| Jungle Rollers — Fastest Clear | Jungle Rollers | `0c` | `FRAMES` | yes |

The other first-island stages are left out: the harness has no clear of them (see
`crash-bandicoot-1-level-achievements.md`), so their submit could not be measured.

## Seeding

`python manage.py seed_crash1_leaderboards` is idempotent:

- a missing leaderboard is created on the core set (`FRAMES`, lower is better, author `ra-import`); the
  bonus subset has no leaderboards;
- an existing one, **matched by title** in any set of the Crash game, moves to the core set and gets the whole
  current definition (description, `mem_addr`, format, lower is better): the format and the order only mean something with the value its
  condition counts. Its author and entries are left alone;
- two leaderboards with the same title make the command fail without writing anything.

Like every Crash seed, it first gets or creates the game with the hash of its only supported disc. The titles
are those of the two leaderboards an earlier seed created and PR 18 removed unvalidated, so a database seeded
back then gets their conditions replaced in place; entries submitted under the old conditions stay.

## Timing rules

| Event | Clock | Why |
| --- | --- | --- |
| The stage hands Crash to the player | **starts** | The run is the player's; the stage's opening is not (see **How a stage opens**) |
| A death, the respawn | **keeps running** | A speedrun timer: a death costs the time it takes. Cancelling would turn the board into a deathless challenge |
| The pause menu | **stops** | The game is frozen while it is open |
| The clear | **stops** on the frame the stage is won; **submits** when the stage hands over to Stage Clear, or to the map | The fade and the Stage Clear load after the win are not played |
| A clear after a death past a checkpoint | **submits** too | The game skips Stage Clear and goes to the map, the stage still won |
| Pause → quit, a game over | **cancels** on the frame the game state turns quit (`04`) or game over (`02`), still in the stage | No clear |
| A trip through the title/map level that returns to the stage (a Tawna bonus round's save screen) | **keeps running**, not counting on that level | Only a quit or a game over loses the run; a cancel there would let the stage's opening start a second run mid-stage |
| A console reset | **cancels** through the emulator: `rc_client_reset` puts every leaderboard back to waiting | The condition cannot tell it from a title screen: RAM is zeroed and the game state reads `00` |

The clock counts emulator frames (60 per second on NTSC), not the game's own ticks, so a load inside the run
(a respawn, a bonus round) counts; an emulator option that speeds up CD reads can shorten those.

## How a stage opens

Measured in the harness by holding the stage's direction from the frame its level loads and watching Crash's
position (`<stage>-timed-pause-quit`):

| Opening | Stage | What happens | The run starts |
| --- | --- | --- | --- |
| `intro` | N. Sanity Beach | A cutscene with the game state `00`; it hands over (game state `01`) with Crash lying on the sand, in a state (GOOL state `22`) he leaves on the first button | when the game state turns `01`: Crash answers the pad from then on (a held direction moves him 3 frames later) |
| `spin-in` | Jungle Rollers | The game state is `01` from the frame the level loads, but Crash spins in (GOOL state `28`) and ignores the pad for 83 frames | when the spin-in ends: bit 15 of the player's state flags falls, and a held direction moves him on that frame |

Both opening states set bit 15 of the player's state flags, but the beach's keeps it until a button is
pressed: a start on that bit would wait for the player there. `TIMED_STAGES` in the seed command names each
stage's opening; a new stage needs its own measured.

## Conditions

`build_leaderboard_mem(level_id, opening)` in the seed command builds every leaderboard; the stage's level id
and its opening change. N. Sanity Beach (`intro`):

```
STA:0xH6188d=h09_0xH618d1=1_0xH61a30=0_0xH618a1=0_d0xH618d1!=1
::CAN:S0xH618d1=4S0xH618d1=2
::SUB:d0xH6188d=h09S0xH6188d=h2dS0xH6188d=h19_0xH618d1=3
::VAL:P:0xH618d1!=1_P:0xH6188d=h2d_P:0xH6188d=h19_P:0xH56400=1_M:1=1
```

Jungle Rollers (`spin-in`) differs in the level id and in the end of its start:

```
STA:0xH6188d=h0c_0xH618d1=1_0xH61a30=0_0xH618a1=0_0xW566b4=d0xW566b4_I:0xW566b4_d0xT121=1_I:0xW566b4_0xT121!=1
```

(each one line in the database; split here at the `::` separators).

| Part | Condition | Meaning |
| --- | --- | --- |
| STA | `0xH6188d=h09` | the loaded level is this stage |
| | `0xH618d1=1` | the game state is playing (c1 `GAME_STATE_PLAYING >> 8`) |
| | `0xH61a30=0` | no attract demo plays (c1 `pbak_state`): the demos play Jungle Rollers with the game state playing |
| | `0xH618a1=0` | no respawn yet (c1 `respawn_count`, back to `0` whenever the title/map level loads): a respawn replays an opening state, and would start a run mid-stage on a leaderboard not already timing |
| | `d0xH618d1!=1` (`intro`) | the game state was not playing on the previous frame: the intro just handed over |
| | `0xW566b4=d0xW566b4` (`spin-in`) | the player object is the one of the previous frame, so the next delta reads the same object (the pointer is null on the map, and the object new on the frame the level loads) |
| | `I:0xW566b4_d0xT121=1`, `I:0xW566b4_0xT121!=1` (`spin-in`) | bit 15 of the player's state flags (c1 `state_flags`, `+0x120`) falls: the spin-in is over |
| CAN | `S0xH618d1=4S0xH618d1=2` | an empty core and one alternative per game state: pause → quit picked (`04`) or the game over (`02`), each set in the stage before the title/map level loads |
| SUB | the stage's level achievement condition | the frame the level switches from this stage to Stage Clear (`2d`), or to the map with game state `03`; `crash-bandicoot-1-level-achievements.md` |
| VAL | `M:1=1` | one hit per frame while the attempt runs, submitted as the value (`value-definition.md`, "Value from HitCount") |
| | `P:0xH618d1!=1` | not counting once the game state leaves playing: the win (`05`, or `03` after a death past a checkpoint), a quit, a game over |
| | `P:0xH6188d=h2d` | not counting on the Stage Clear level, where the game state reads playing again on the submit frame |
| | `P:0xH6188d=h19` | not counting on the title/map level, which a run only crosses through a bonus round's save screen |
| | `P:0xH56400=1` | not counting while the pause menu is open (c1 `paused`) |

rcheevos evaluates the value on the start frame (it counts) and once more on the submit frame (paused), so a run
counts the frames from the start up to the last one before the win.

### Signals left out on purpose

- **The game state alone** for every stage: on Jungle Rollers it turns to playing on the frame the level loads,
  83 frames before Crash can move.
- **Bit 15 of the state flags** for N. Sanity Beach: it falls on the first button, not when Crash can move.
- **The level id switch from the map** (`19` → the stage): the level loads before the opening.
- **Cancel on any title/map level load without a win:** a Tawna bonus round won leads to the save screen
  (c1 `title_state` `0d`/`0e`, on the title level) and back to the stage through the bonus return, which
  replays the spin-in with `respawn_count` back to `0`. A cancel there would start a second run at the bonus
  platform, and the clear would submit only the rest of the stage. The game over's own game state is not
  read on the title level either: it turns `00` on the frame the level loads (harness).
- **Cancel on any level other than the stage:** a Tawna or Brio bonus round loads its own level (c1
  `LID_BONUS*`) and returns to the stage; the run goes on through it.
- **`0x618a1`** (respawn counter) as a cancel: a death keeps the run (see **Timing rules**); it only
  keeps a respawn from starting one.

## Validation

Syntax: `scripts/check-mem-addr.sh` (the vendored rcheevos parser, `rc_lboard_size`) accepts both
leaderboards; `pytest` runs it over every seeded one.

Behaviour: the harness activates both leaderboards in the vendored rcheevos runtime next to every achievement,
records their `LBOARD_*` events, and judges every scenario's attempts: each must start on a frame where its
stage's opening hands Crash to the player (before any respawn, no demo), the value it shows or submits must
equal the frames of play since then (stage loaded, game state playing, pause menu closed), a submitted one
must also equal the frames from its start to the frame the stage is won (game state `05`, or `03` on the map
path), a cancel must come with the game state quit or game over and a submit on Stage Clear or the map; and
each scenario lists how many attempts of each leaderboard it plays and how each ends (submitted, canceled, cut
short by a state load, or still running). A submit, a start or a cancel anywhere else fails it. The
independent evidence of the start frame is Crash's position in the `-timed-pause-quit` scenarios.

Runs on `PCSX-ReARMed r26 ff81ed1` with the vendored rcheevos 12.3.

| Scenario | What is played | Result |
| --- | --- | --- |
| `nsanity-beach-timed-pause-quit` | From the map, N. Sanity Beach entered holding UP from the frame the level loads; the pause menu open 300 frames; pause → quit | Starts at frame 759, when the intro hands over; Crash still on the ground before, first moves 3 frames later; 142 frames on the clock at the quit, the pause menu left out; canceled when the quit is picked |
| `jungle-rollers-timed-pause-quit` | The same on Jungle Rollers | The level loads at frame 365 with the game state playing; starts at 448, when the spin-in ends, and Crash moves on that frame; 140 frames at the quit; canceled when the quit is picked |
| `nsanity-beach-timed-clear` | From the map, N. Sanity Beach entered and cleared by `plans/nsanity-beach-clear.json`; Stage Clear → map; Jungle Rollers entered and quit | Submits **7065** frames (1:57.75) on the switch to `2d`: the plan starts at frame 789 and the stage is won at its frame 7035, 7824 − 759; Jungle Rollers' attempt starts after its spin-in and is canceled on `19` |
| `jungle-rollers-timed-clear` | The same with `plans/jungle-rollers-clear.json`; then The Great Gate entered and quit | Submits **12394** frames (3:26.56): the plan starts at 395 and wins at its frame 12447, 12842 − 448 |
| `nsanity-beach-timed-checkpoint-death` | From the map: the checkpoint route, a death, and the clear from the checkpoint, no state load in between | Submits **8518** frames on the switch to the map (`19`, game state `03`): won at 9277, 9277 − 759, the death and the respawn included |
| `nsanity-beach-timed-game-over` | From the map, deaths down to the game over | One attempt through every death, canceled on the game over |
| `jungle-rollers-*` from `jungle-rollers-start` | Deaths, quits, the clear, the gem runs | That state is saved inside the spin-in, so an attempt starts 53 frames in, when it ends: still running after the deaths, canceled by the first quit, and the clear submits 12394 frames, as from the map |
| the farming routes (`nsanity-beach-aku`, `-wumpa`, `-lives-*`) | Plans that quit and re-enter N. Sanity Beach to farm, then a state load and a re-entry | One attempt per re-entry, each canceled by the next quit; the one open at the state load is cut short by it |
| every other scenario | Cold boot, 15 minutes of attract demos (Jungle Rollers among them), a demo then a new game, deaths, quits, clears, the boss | Nothing submits; an attempt starts only when a timed stage hands Crash over, and ends canceled by a quit or still runs when the scenario ends (the new game) |

The plans replay the same from a live entry as from the `-start` states they were searched from (checked:
the same win frame), which is what lets a timed scenario start on the map.

### Still for the in-game check (DuckStation)

- **Hardcore mode:** rcheevos' client runs leaderboards only in hardcore unless the emulator allows them in
  softcore (`rc_client.c`, `allow_leaderboards_in_softcore`); test with hardcore on.
- **Both leaderboards, on DuckStation:** the timer appears when Crash can move (when the intro hands over on
  N. Sanity Beach, with Crash still lying on the sand; after the spin-in on Jungle Rollers), keeps running
  through a death, stops while paused, and the time is submitted on the Stage Clear screen; a pause → quit
  and a game over cancel it, and so should a console reset (through `rc_client_reset`, not the condition).
- **A clear after a death past a checkpoint:** submitted when the island map loads. Seen in the harness on
  N. Sanity Beach only.
- **The Tawna bonus round of Jungle Rollers:** collect the 3 Tawna tokens, win the bonus round, save or
  continue on the save screen, and check that the attempt is neither canceled nor restarted when the stage
  comes back, and that the clear submits the time from the original start (the save screen not counted). The
  harness never played a bonus round, and the game state on that save screen is not measured: if it reads
  quit (`04`), the run is canceled there and the spin-in on the return starts a second one, a short time
  that must not ship. A lost bonus round returns straight to the stage and should keep the run too.
- **CD read speed:** DuckStation's CD-ROM read speed-up may shorten the loads inside a run (a respawn).
  DuckStation runs rcheevos 12.4.0 against its own CD timing; the harness ran 12.3 on a libretro core.
