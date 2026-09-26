# Crash Bandicoot 1 — Memory Map (Code Notes)

> **Source:** RetroAchievements code notes for *Crash Bandicoot* (PlayStation), game id 10434 — <https://retroachievements.org/codenotes.php?g=10434>  
> **Community authors:** matheus2653, CySlaytor, Alfex, msdmario, TheJediSonic.

RetroAchievements maps system memory at `$00000000` immediately followed by cartridge memory, so the addresses below may not correspond to real-hardware addresses. The `Type` column is inferred from each note's text and is best-effort. Seed these notes into the database as `CodeNote` rows with `python manage.py seed_crash1_code_notes` (idempotent).

Target ROM: **NTSC-US, SCUS-94900**.

## Scope

- **The set (game 10434) supports exactly one hash:** *Crash Bandicoot (USA)*, md5
  `35386fd0891e594c9b6d8a4a5baa0027`. There is no registered EU/PAL hash. The 46 official achievements were
  written and tested against the USA ROM only, so every address the set actually uses is, by definition, a
  USA address.
- **Untagged notes = the canonical USA map.** This is where the `0x619xx` block lives — the block validated
  in-game, whose four addresses the code notes agree with.
- **`(EU)`-tagged notes are out of scope.** They are annotations for a different ROM left in the shared
  code-note file; they are not our target (NTSC-US, SCUS-94900) and are **not addresses to validate** —
  rechecking them makes no sense. They are kept in the raw dump below only as a record that they exist and
  why they were excluded.
- **Timing / region note (future).** PAL runs at 50 Hz and NTSC at 60 Hz. Because leaderboards count
  **frames**, times from ROMs of different regions are not comparable. Out of scope today (USA only),
  recorded here for when the catalogue grows.

## Read this before trusting anything below

- **The public API does not expose achievement conditions.** `API_GetGameExtended` returns `MemAddr` as an
  **MD5 hash** for non-authors, so no address here is inferred from the working RA condition logic — every
  entry is sourced from a **code note**, from the **c1 decompilation**, or from **validation** (in game or in
  the headless harness), never from the set's `MemAddr`.
- **Only untagged notes describe the USA target.** `(EU)`-tagged notes belong to another ROM and are out of
  scope (see **Scope** above); the canonical USA map is the untagged `0x619xx` family.
- **The `0x6188c`–`0x61a67` block is the engine's GOOL globals array** (`gool_globals` at `0x8006188C` in the
  [wurlyfox/c1](https://github.com/wurlyfox/c1) decompilation, `src/globals.h`): global *n* lives at
  `0x6188c + 4n`, and most counters are 24.8 fixed point, so the integer is the second byte. That is why the
  notes point at odd addresses (`0x618ed` lives, `0x61985` boxes, `0x619c5` stage).
- **Console RAM is zeroed at reset,** so `0` means "not initialised yet" as often as it means "state 0". The
  level id at `0x6188d` is the reliable context: it names the level file the engine has loaded, from the boot
  logos to the Stage Clear screen. The Aku Aku pointer at `0x618cc` is **not** a "game running" guard (see
  below).

## Validated addresses

Validated on SCUS-94900, in game (DuckStation, by the maintainer) or in the headless harness
(`tools/achievement-harness/`: the real disc on a libretro core with the rcheevos runtime judging every frame).
The c1 name is the global's name in the decompilation.

| Address (rcheevos) | Size | Meaning | Source | Status |
| --- | --- | --- | --- | --- |
| `0xH6188d` | 8-bit | Level id (c1 `cur_lid`, `LID_*` in `src/common.h`): `19` title, menus and island map · `09` N. Sanity Beach · `0c` Jungle Rollers · `12` The Great Gate · `0e` Boulders · `0f` Upstream · `15` Rolling Stones · `2d` Stage Clear screen (`LID_LEVELEND`). A clear moves it from the stage's id to `2d`; a death respawns in place; a game over and a pause → quit move it to `19`; the attract demos go stage id → `19` | c1 + harness | **VALIDATED** (harness) |
| `0xH618d1` | 8-bit | Game state (c1 `game_state >> 8`): `00` cutscene / menus · `01` playing · `02` game over · `03` leaving the Stage Clear screen · `04` quitting from the pause menu · `05` stage cleared (c1 `GAME_STATE_NEW_GEM`, set on every clear, gem or not) · `06` title / demo ending. On a clear it reads `05` for about 90 frames, then `01` from the frame `0x6188d` becomes `2d` | c1 + harness | **VALIDATED** (harness) |
| `0xH61a30` | 8-bit | Attract-demo playback (c1 `pbak_state`): `03` demo picked · `02` demo playing · `00` in normal play. Drops back to `00` about 35 frames **before** a demo's level switches back to `19` | c1 + harness | **VALIDATED** (harness) |
| `0xH618a1` | 8-bit | Respawn counter (c1 `respawn_count`, 24.8): `+1` on every in-stage respawn; back to `0` when a game over resets the globals | c1 + harness | **VALIDATED** (harness) |
| `0xH61948` | 8-bit | Stages unlocked on the island map (c1 `levels_unlocked`): the map spawns the paths and stage markers up to this count when it loads; `1` on a new game, `2` once N. Sanity Beach is cleared | c1 + harness | **VALIDATED** (harness) |
| `0xH61994` | 8-bit | Overworld status (c1 `island_cam_state`): `00` in a stage (and before the map first shows) · `01` on the map · `05` going to prev world · `06` going to next world. `ff` for one frame when the map appears; deaths do not change it | code note + harness | **VALIDATED** (notes agree) |
| `0xH619c5` | 8-bit | Stage under the map cursor (`00`=N. Sanity Beach … `20`=Whole Hog; table below). Stays set inside the stage; `00` until the cursor first moves and in every attract demo | code note + harness | **VALIDATED** (notes agree) |
| `0xH61998` | 8-bit | c1 `is_first_zone`, **not** a results flag: `0→1` on every level-file load (boot logos, title, demos, stages, map, Stage Clear) and on every respawn; back to `0` when Crash leaves the first zone | c1 + harness | **CORRECTED** (the note says "On Results Screen") |
| `0xW618cc` | 24-bit ptr | Aku Aku object pointer (shield level at `+0x189`). `0` only until the first level or demo loads after power-on, **never cleared** afterwards: it means "something loaded since power-on", not "a stage is loaded" | code note + harness | **CORRECTED** (not a "game running" guard) |

## Key addresses (code note only — NOT yet validated in game)

Same `0x619xx` block as the validated addresses, so high confidence for NTSC-US, but each still needs a check
before shipping a condition against it.

| Address | Size | Meaning | Notes |
| --- | --- | --- | --- |
| `0x61988`–`0x6198b` | bitfield ×4 | Gems collected: bit *n*+1 counted from `0x61988` is stage *n* of the `0x619c5` table | Core of the 26-gem tracking |
| `0x619ad` | bitfield | Key/Gem pt1: bit0 Fumbling-in-the-Dark gem, bit2 Jaws-of-Darkness **key** | Secret / key-gated |
| `0x619ae` | bitfield | Key/Gem pt2: bit2 Whole Hog gem, bit4 Sunset Vista **key** | Secret / key-gated |
| `0x61985` | 8-bit | Boxes destroyed/missed (running counter, per stage); counts the missed boxes on the Stage Clear screen | The USA note; its `(EU)` twin `0x61665` is out of scope |
| `0x6197c` | 8-bit | Current bonus stage id (Tawna/Brio/Cortex) | Bonus-round identity, not token count |
| `0x61974` | 8-bit | Game progress — **updates only while the progress screen is shown** | Laggy; not a live counter |
| `0x61a10` | 8-bit | Gems total — **updates only while the progress screen is shown** | Laggy aggregate |
| `0x618a4` | 24-bit ptr | Wumpa fruit count (deref `+0x6c → +0xe4 → +0x0c`) | In-stage Wumpa |
| `0x618a8` | 24-bit ptr | Lives counter (deref `+0x6c → +0xe4 → +0x0c`) | The note's `+0x06` first hop always reads 2 (harness); `+0x6c` reads the lives |
| `0x618ed` / `0x618f1` / `0x618f5` | 8-bit | Lives / Aku Aku / Wumpas — committed copies, synced only on stage entry and exit (harness) | Map-side mirror |
| `0x60ddc` | 24-bit ptr | Boss health (Papu/Ripper/Pinstripe/Cortex/Brio via offsets) | Hit-counter semantics, see raw dump |
| `0x61898` | 24-bit ptr | Koala Kong health (deref `+0x6c → +0x105`) | |
| `0x54b84` | 8-bit | Frame counter; keeps counting while paused (harness) | For the timed-boss achievements |
| `0x56400` | 8-bit | `01` = game paused | Pause guard for timed runs |
| `0x5e720` / `0x5e721` | bitfield | Controller inputs pt1/pt2 (buttons + dpad); during a demo they show the recorded inputs (harness) | For "without jumping / without pressing up" achievements |

`0x61a68` ("FF = finished/quit a level" in the notes) is **not usable**: it is sound-library data
(`_svm_okof1` in c1), not a game flag.

The boss-specific and per-stage `0x9xxxx` notes below (Aku-Aku-per-stage, per-stage lives counters, boss "First
Try" health) are **untagged USA addresses but unvalidated** — check them in game before building against them.
Their `(EU)`-tagged siblings in the same dump are out of scope (see **Scope**), kept only as a record.

### Stage id table (`0xH619c5`)

`00` N.Sanity Beach · `01` Jungle Rollers · `02` The Great Gate · `03` Boulders · `04` Upstream ·
`05` Papu Papu · `06` Rolling Stones · `07` Hog Wild · `08` Native Fortress · `09` Up The Creek ·
`0A` Ripper Roo · `0B` The Lost City · `0C` Temple Ruins · `0D` Road To Nowhere · `0E` Boulder Dash ·
`0F` Sunset Vista · `10` Koala Kong · `11` Heavy Machinery · `12` Cortex Power · `13` Generator Room ·
`14` Toxic Waste · `15` Pinstripe · `16` The High Road · `17` Slippery Climb · `18` Lights Out ·
`19` Jaws of Darkness · `1A` Castle Machinery · `1B` Nitrus Brio · `1C` The Lab · `1D` The Great Hall ·
`1E` Dr. Neo Cortex · `1F` Fumbling In The Dark · `20` Whole Hog.

This is the map cursor, **not** the level id: `0x6188d` uses the engine's `LID_*` numbering (N. Sanity Beach is
`09` there, `00` here). The code note calls `1D` "The Great Wall"; the stage is The Great Hall.

## Traps

- **`0x61998` is `is_first_zone`, not a results flag.** It rises `0→1` on every level load and every respawn, so
  any condition built on its edge fires on a death (the original bug of the level-completion achievements),
  on a pause → quit, and on the title screen when an attract demo hands back to it. A stage clear is the level
  id `0x6188d` changing from the stage's id to `2d` — see `apps/achievements/crash-bandicoot-1-level-achievements.md`.
- **`0x618cc` is not a "stage loaded" guard.** It is null only until the first level loads after power-on, so
  `0xW618cc!=0` separates the boot sequence from everything else and nothing more; `R:0xW618cc=0` never fires
  once the game has started.
- **Load-out vs. map.** `0xH61994` passes through `05`/`06` ("going to prev/next world") during the map
  transition, and stage RAM is unloaded/reloaded across it. A timer or counter read during this window sees
  stale/zeroed RAM — pause any timing and don't sample stage addresses until `0xH61994` settles to `01` (map)
  or `00` (in stage).
- **Demo mode / attract loop.** From the title screen the game replays demos of real stages (measured over 15
  minutes: Jungle Rollers, The Great Gate, Boulders, Papu Papu, The Lost City, Jaws of Darkness, The Lab) with
  no player: `0x6188d` holds the stage id, `0x61994` reads `00` and `0x619c5` reads `00`. `0x61a30` is
  non-zero while a demo plays, but drops to `00` before the demo's level switches back to the title, so it
  cannot guard that switch; demos never load the Stage Clear level `2d`.

## 100% (secret ending) — what the data covers

Achievement set target: **26 gems + secret ending** (`A Shining Ending`), plus per-stage "all boxes + gem",
both **keys**, and the three bonus rounds.

"Destroy all boxes and collect the gem" is stored as the stage's **gem bit** (the game only awards the gem when
every box is broken and you reach the end without dying after the first checkpoint), so the per-stage box
achievements map onto these bits — there is no need for a separate per-stage box total.

| Byte | Bit → stage (gem) |
| --- | --- |
| `0x61988` | b1 N.Sanity Beach · b2 Jungle Rollers · b3 The Great Gate · b4 Boulders · b5 Upstream · b7 Rolling Stones · *(b0 = no stage, b6 Papu Papu = NO GEM)* |
| `0x61989` | b0 Hog Wild · b1 Native Fortress · b2 Up The Creek · b4 The Lost City **(Green)** · b5 Temple Ruins · b6 Road To Nowhere · b7 Boulder Dash · *(b3 Ripper Roo = NO GEM)* |
| `0x6198a` | b0 Sunset Vista · b2 Heavy Machinery · b3 Cortex Power · b4 Generator Room **(Orange)** · b5 Toxic Waste **(Blue)** · b7 The High Road · *(b1 Koala Kong, b6 Pinstripe = NO GEM)* |
| `0x6198b` | b0 Slippery Climb **(Red)** · b1 Lights Out **(Purple)** · b2 Jaws of Darkness · b3 Castle Machinery · b5 The Lab **(Yellow)** · *(b4 Nitrus Brio = NO GEM)* |
| `0x619ad` | b0 Fumbling in the Dark gem · **b2 Jaws of Darkness KEY** |
| `0x619ae` | **b2 Whole Hog gem** · **b4 Sunset Vista KEY** |

The code note puts Fumbling In The Dark at `0x6198b` bit2. By the bit-per-stage rule (bit *n*+1 from `0x61988`
is stage *n*) that bit is stage `19`, Jaws of Darkness; Fumbling In The Dark's gem is only `0x619ad` bit0. The
DuckStation all-gems cheat for SCUS-94900 writes `0x2FBDF7BE` at `0x61988` and `0x00140500` at `0x619ac`, which
is exactly the 26 gems with this mapping.

Colored gems (6 named in notes): Green (Lost City), Orange (Generator Room), Blue (Toxic Waste), Red (Slippery
Climb), Purple (Lights Out), Yellow (The Lab). **Keys:** Sunset Vista → `0x619ae` bit4; Jaws of Darkness →
`0x619ad` bit2.

### What the data does NOT cover — discovery required

1. **Bonus-round token count.** Achievements need "collect 3 Tawna / 3 Brio tokens". `0x6197c` gives the
   bonus-stage **identity** but **no note documents the token counter**. c1 names a `tawna_count` global at
   `0x61900` (24.8); Cortex and Brio have `0x618f8` / `0x618fc`. Unvalidated.
2. **Per-stage box totals.** Only a single running "boxes destroyed/missed" counter (`0x61985`) exists — no
   per-stage "X of Y" totals. Fine for standard 100% (gem bit = all boxes); any "N of M boxes" achievement needs
   the per-stage total discovered in game.
3. **Which frame the gem bit is set** (during the stage or on the Stage Clear screen) — measure before
   building a gem achievement on its edge.
4. **The 26-gem completion mask.** `0x61a10` ("gems total") only updates on the progress screen, so it is not a
   reliable live "26/26" trigger. A robust all-gems condition has to AND the individual bits above — build the
   exact mask and verify the total lands at 26 in game.
5. **Generator Room's Tawna bonus id.** The note lists `0B` for both Up the Creek and Generator Room; research
   against the c1 decompilation and the CBHacks map gives `02` for Generator Room. Unvalidated.
6. **Boss hit counts.** The `0x60ddc` note caps Nitrus Brio at 5 hits; the Crash wiki says 9. Unvalidated.

## All code notes (113)

The 108 RetroAchievements code notes, verbatim, with a *RetroPlatinas correction* appended where research or
validation contradicts them, plus five addresses marked *RetroPlatinas* that the notes do not cover.

| Address | Type | Note |
| --- | --- | --- |
| `0x54b84` | 8-bit | Frames |
| `0x56400` | enum/flag | 01 - Game Paused |
| `0x5e720` | bitfield | Controller Inputs Part 1:<br>Bit0 - L2<br>Bit1 - R2<br>Bit2 - L1<br>Bit3 - R1<br>Bit4 - Triangle<br>Bit5 - Circle<br>Bit6 - Cross<br>Bit7 - Square |
| `0x5e721` | bitfield | Controller Inputs Part 2:<br>Bit0 - Select<br>Bit1 - L3<br>Bit2 - R3<br>Bit3 - Start<br>Bit4 - DPAD Up<br>Bit5 - DPAD Right<br>Bit6 - DPAD Down<br>Bit7 - DPAD Left |
| `0x60ddc` | pointer | [24-bit Pointer]<br>+0x105 \| Papu Papu<br>0x03 = Max Health<br>-------------------------<br>+0x6c \|<br>.+0x68 \|<br>..+0x105 \| [8bit] Ripper Roo Health<br>0x03 = Max Health<br>-------------------------<br>+0x105 \| Pinstripe Potoroo Health<br>0x06 = Max Health<br>-------------------------<br>+0x105 \| [8bit] Dr. Neo Cortex and Nitrus Brio Health<br>0x05 = Max Health<br><br>Note: this variable increments with each hit, up to a maximum of 5. It functions as a hit counter rather than a countdown.<br>+6c \|<br>.+0x105 \| [8bit] Actual Cortex Health - This pointer correctly reflects Cortex's logical health, but it breaks as soon as the fight with Crash begins. It only updates again when Crash dies, then immediately breaks once the fight restarts. |
| `0x60e1a` | 8-bit | Big TNT moving pattern (left column moves down, ?) |
| `0x61665` | 8-bit | Number of crates broken/missed (EU) |
| `0x61678` | enum/flag | 01: On results screen/you died after first checkpoint (EU) |
| `0x6188d` | 8-bit | Level id (RetroPlatinas; c1 cur_lid, validated in the headless harness):<br>19 - Title, menus and island map<br>09 - N. Sanity Beach<br>0C - Jungle Rollers<br>0E - Boulders<br>0F - Upstream<br>12 - The Great Gate<br>15 - Rolling Stones<br>2D - Stage Clear screen<br>A stage clear changes it from the stage's id to 2D. |
| `0x61898` | pointer | [24-bit Pointer]<br>+0x6c \|<br>.+0x105 \| Koala Kong Health |
| `0x618a1` | 8-bit | Respawn counter (RetroPlatinas; c1 respawn_count, validated in the headless harness): +1 on every in-stage respawn, back to 0 after a game over. |
| `0x618a4` | pointer | [24-bit Pointer]<br>+0x6c \|<br>.+0xe4 \|<br>..+0x0c \| [8-bit] Wumpa Fruits |
| `0x618a8` | pointer | [24-bit Pointer]<br>+0x06 \|<br>.+0xe4 \|<br>..+0x0c \| [8-bit] Live Counter<br><br>RetroPlatinas correction: the first hop is +0x6c, not +0x06 (+0x06 always reads 2; validated in the headless harness). |
| `0x618cc` | pointer | [24-bit Pointer]<br>+0x80 \| [32-bit] Aku Aku's X Position<br>+0x84 \| [32-bit] Aku Aku's Y Position<br>+0x88 \| [32-bit] Aku Aku's Z Position<br><br>+0x189 \| Aku Aku Shield Level<br>0x01 = Level 1<br><br>----- Debug -----<br>+0xe0 \| [32-bit] Invincible Crash (freeze this value after acquiring Aku Aku shield, unfreeze upon finishing the level)<br><br>RetroPlatinas correction: null only until the first level loads after power-on and never cleared afterwards, so it is not a "stage loaded" guard (validated in the headless harness). |
| `0x618d1` | enum/flag | Game state (RetroPlatinas; c1 game_state, validated in the headless harness):<br>00 - Cutscene / menus<br>01 - Playing<br>02 - Game over<br>03 - Leaving the Stage Clear screen<br>04 - Quitting from the pause menu<br>05 - Stage cleared<br>06 - Title / demo ending |
| `0x618ed` | 8-bit | Lives Countrer (Map) |
| `0x618f1` | 8-bit | Aku Aku (Map) |
| `0x618f5` | 8-bit | Wumpas (Map) |
| `0x61920` | 32-bit | Camera Position X (32-Bit) |
| `0x61924` | 32-bit | Camera Position Y (32-Bit) |
| `0x61930` | 8-bit | Something Cutscene Related? |
| `0x61948` | 8-bit | Stages unlocked on the island map (RetroPlatinas; c1 levels_unlocked, validated in the headless harness): the map spawns the stages up to this count when it loads. |
| `0x61974` | 8-bit | Game Progress (Value only changes when Game Progress is show on screen) |
| `0x6197c` | enum/flag | Current Bonus Stage:<br>00 - Tawna Bonus Stage 1 (Jungle Rollers)<br>04 - Tawna Bonus Stage 2 (The Great Gate)<br>0A - Tawna Bonus Stage 3 (Upstream)<br>08 - Tawna Bonus Stage 4 (Rolling Stones)<br>01 - Tawna Bonus Stage 5 (Native Fortress)<br>0B - Tawna Bonus Stage 6 (Up the Creek)<br>0C - Tawna Bonus Stage 7 (The Lost City)<br>0D - Tawna Bonus Stage 8 (Road To Nowhere)<br>05 - Tawna Bonus Stage 9 (Sunset Vista)<br>12 - Tawna Bonus Stage 10 (Heavy Machinery)<br>0B - Tawna Bonus Stage 11 (Generator Room)<br>06 - Tawna Bonus Stage 12 (Toxic Waste)<br>03 - Tawna Bonus Stage 13 (The High Road)<br>11 - Tawna Bonus Stage 14 (Jaws of Darkness)<br>13 - Tawna Bonus Stage 15 (The Lab)<br><br>0E - Brio Bonus Stage 1 (Rolling Stones)<br>07 - Brio Bonus Stage 2 (The Lost City)<br>15 - Brio Bonus Stage 3 (Heavy Machinery)<br>14 - Brio Bonus Stage 4 (Slippery Climb)<br><br>09 - Cortex Bonus Stage 1 (Sunset Vista)<br>0F - Cortex Bonus Stage 2 (Jaws Of Darkness)<br><br>RetroPlatinas correction: 0B is Up the Creek; Generator Room is 02 (c1 decompilation and CBHacks research, not validated). |
| `0x61985` | 8-bit | Ammount of boxes destroyed/missed |
| `0x61988` | bitfield | Gems Collected Part 1:<br>Bit0 - ???<br>Bit1 - N. Sanity Beach<br>Bit2 - Jungle Rollers<br>Bit3 - The Great Gate<br>Bit4 - Boulders<br>Bit5 - Upstream<br>Bit6 - Papu Papu (NO GEM)<br>Bit7 - Rolling Stones |
| `0x61989` | bitfield | Gems Collected Part 2:<br>Bit0 - Hog Wild<br>Bit1 - Native Fortress<br>Bit2 - Up The Creek<br>Bit3 - Ripper Roo (NO GEM)<br>Bit4 - The Lost City (Green Gem)<br>Bit5 - Temple Ruins<br>Bit6 - Road To Nowhere<br>Bit7 - Boulder Dash |
| `0x6198a` | bitfield | Gems Collected Part 3:<br>Bit0 - Sunset Vista<br>Bit1 - Koala Kong (NO GEM)<br>Bit2 - Heavy Machinery<br>Bit3 - Cortex Power<br>Bit4 - Generator Room (Orange Gem)<br>Bit5 - Toxic Waste (Blue Gem)<br>Bit6 - Pinstripe (NO GEM)<br>Bit7 - The High Road |
| `0x6198b` | bitfield | Gems Collected Part 4:<br>Bit0 - Slippery Climb (Red)<br>Bit1 - Lights Out (Purple)<br>Bit2 - Flumbling In The Dark<br>Bit3 - Castle Machinery<br>Bit4 - Nitrus Brio (NO GEM)<br>Bit5 - The Lab (Yellow)<br><br>RetroPlatinas correction: Bit2 is Jaws of Darkness; the Fumbling In The Dark gem is 0x619ad Bit0. |
| `0x61994` | enum/flag | Overworld Status:<br>00 - In a Stage<br>01 - On the Map<br>05 - Going To The Previous World<br>06 - Going To The Next World |
| `0x61998` | 8-bit | On Results Screen<br><br>RetroPlatinas correction: this is the engine's is_first_zone flag (c1): 0 -> 1 on every level load and every respawn, 0 once Crash leaves the first zone. Not a results flag (validated in the headless harness). |
| `0x619ad` | bitfield | Key/Gem Collected Part 1:<br>Bit0 - Fumbling in the Dark Gem<br>Bit2 - Jaws Of Darkness Key |
| `0x619ae` | bitfield | Key/Gem Collected Part 2:<br>Bit 2 - Whole Hog Gem<br>Bit4 - Sunset Vista Key |
| `0x619c5` | enum/flag | Stage Select/Current Stage:<br>00 - N. Sanity Beach<br>01 - Jungle Rollers<br>02 - The Great Gate<br>03 - Boulders<br>04 - Upstream<br>05 - Papu Papu<br>06 - Rolling Stones<br>07 - Hog Wild<br>08 - Native Fortress<br>09 - Up The Creek<br>0A - Ripper Roo<br>0B - The Lost City<br>0C - Temple Ruins<br>0D - Road To Nowhere<br>0E - Boulder Dash<br>0F - Sunset Vista<br>10 - Koala Kong<br>11 - Heavy Machinery<br>12 - Cortex Power<br>13 - Generator Room<br>14 - Toxic Waste<br>15 - Pinstripe<br>16 - The High Road<br>17 - Slippery Climb<br>18 - Lights Out<br>19 - Jaws of Darkness<br>1A - Castle Machinery<br>1B - Nitrus Brio<br>1C - The Lab<br>1D - The Great Wall<br>1E - Dr. Neo Cortex<br>1F - Flumbling In The Dark<br>20 - Whole Hog<br><br>RetroPlatinas correction: 1D is The Great Hall. |
| `0x61a10` | 8-bit | Gems (Value only changes when Game Progress is show on screen) |
| `0x61a30` | enum/flag | Attract-demo playback (RetroPlatinas; c1 pbak_state, validated in the headless harness):<br>00 - Normal play<br>02 - Demo playing<br>03 - Demo picked<br>Back to 00 before the demo's level switches to the title. |
| `0x61a68` | enum/flag | FF - Finished/Quited a Level (Kinda)<br><br>RetroPlatinas correction: sound-library data (c1 _svm_okof1), not a game flag. |
| `0x90501` | 8-bit | Pinstripe's health (EU) |
| `0x9069d` | 8-bit | Papu Papu's health (EU) |
| `0x9080d` | 8-bit | Pinstripe Potoroo Gun Shoots Thing (First Try) |
| `0x9081d` | 8-bit | Pinstripe Potoroo Health (First Try) |
| `0x90820` | 8-bit | Pinstripe Potoroo Animations (First Try) |
| `0x909b9` | 8-bit | Papu Papu Health (First Try) |
| `0x909bc` | 8-bit | Papu Papu Animation (First Try) |
| `0x91162` | 8-bit | Aku Aku level (Dr. Nitrus Brio) (EU) |
| `0x9119d` | 8-bit | Nitru Brio Health (First Try) |
| `0x9147d` | 8-bit | Aku Aku (Nitrus Brio) |
| `0x914d5` | 8-bit | Ripper Roo's health (uneditable) (EU) |
| `0x914e9` | 8-bit | Cortex's health (uneditable) (EU) |
| `0x91615` | 8-bit | Aku Aku level (Koala Kong) (EU) |
| `0x9164d` | 8-bit | Koala Kong Health (First Try) |
| `0x917f1` | 8-bit | Ripper Roo Health (First Try) |
| `0x91809` | 8-bit | Dr. Neo Cortex Health (First Try) |
| `0x91865` | 8-bit | Aku Aku (Papu Papu) |
| `0x9192d` | 8-bit | Aku Aku (Koala Kong) |
| `0x91a11` | 8-bit | Aku Aku level (Ripper Roo) (EU) |
| `0x91a94` | 8-bit | Lives Countrer (N. Sanity Beach) |
| `0x91ad5` | 8-bit | Aku Aku (Jungle Rollers) |
| `0x9203d` | 8-bit | Aku Aku (Temple Ruins) |
| `0x92485` | 8-bit | Aku Aku (Upstream) |
| `0x92579` | 8-bit | Aku Aku level (N. Sanity Beach) (EU) |
| `0x92679` | 8-bit | Aku Aku (Native Fortress) |
| `0x926e9` | 8-bit | Aku Aku level (Up the creek)(EU) |
| `0x927a5` | 8-bit | Aku Aku (Up The Creek) |
| `0x92899` | 8-bit | Aku Aku (N. Sanity Beach) |
| `0x92ab1` | 8-bit | Aku Aku (The Great Gate) |
| `0x92b6d` | 8-bit | Aku Aku (Dr. Neo Cortex) |
| `0x93699` | 8-bit | Koala Kong's health (EU) |
| `0x939f5` | 8-bit | Aku Aku (Rolling Stones) |
| `0x93ebd` | 8-bit | Aku Aku (Road To Nowhere) |
| `0x9456d` | 8-bit | Aku Aku (Sunset Vista) |
| `0x95ded` | 8-bit | Aku Aku (The Lost City) |
| `0x973f5` | 8-bit | Brio's health (uneditable) (EU) |
| `0x9ddc1` | 8-bit | Wumpa fruit (Ripper Roo) (EU) |
| `0x9ddc5` | 8-bit | Lives (Ripper Roo) (EU) |
| `0x9de7d` | 8-bit | Wumpa fruit (Koala Kong) (EU) |
| `0x9de81` | 8-bit | Lives (Koala Kong) (EU)<br>Wumpa fruit (Nitrus Brio) (EU) |
| `0x9de85` | 8-bit | Lives (Dr. Nitrus Brio) (EU) |
| `0x9e0d1` | 8-bit | Papu Papu lives counter. |
| `0x9e0e1` | 8-bit | Ripper Roo lives counter. |
| `0x9e0f9` | 8-bit | Dr. Neo Cortex lives counter. |
| `0x9e191` | 8-bit | Pinstripe lives counter. |
| `0x9e199` | 8-bit | Koala Kong lives counter. |
| `0x9e1a1` | 8-bit | Nitrus Brio lives counter. |
| `0x9e215` | 8-bit | Wumpa fruit (EU) |
| `0x9e219` | 8-bit | Lives (EU) |
| `0x9e369` | 8-bit | The Great Hall lives counter. |
| `0x9e4cd` | 8-bit | Toxic Waste lives counter. |
| `0x9e509` | 8-bit | Lights Out lives counter. |
| `0x9e525` | 8-bit | Crash Animations (N. Sanity Beach) |
| `0x9e52d` | 8-bit | The Lab lives counter. |
| `0x9e535` | 8-bit | Wumpas (N. Sanity Beach) |
| `0x9e54d` | 8-bit | Generator Room lives counter. |
| `0x9e585` | 8-bit | Boulders lives counter. |
| `0x9e59d` | 8-bit | Jungle Roller's lives counter. |
| `0x9e5ad` | 8-bit | Fumbling in the Dark lives counter. |
| `0x9e5cd` | 8-bit | The High Road lives counter. |
| `0x9e5dd` | 8-bit | Upstream lives counter. |
| `0x9e5f1` | 8-bit | Slippery Climb lives counter. |
| `0x9e611` | 8-bit | Rolling Stones lives counter. |
| `0x9e615` | 8-bit | Whole Hog lives counter. |
| `0x9e621` | 8-bit | Road to Nowhere lives counter. |
| `0x9e64d` | 8-bit | Hog Wild/Temple Ruins lives counter. |
| `0x9e6a1` | 8-bit | Up the Creek lives counter. |
| `0x9e6a5` | 8-bit | The Lost City lives counter. |
| `0x9e751` | 8-bit | The Great Gate Lives counter. |
| `0x9e779` | 8-bit | Jaws of Darkness lives counter. |
| `0x9e77d` | 8-bit | Cortex Power lives counter. |
| `0x9e7d1` | 8-bit | Native Fortress lives counter. |
| `0x9e809` | 8-bit | Boulder Dash lives counter. |
| `0x9e819` | 8-bit | Sunset Vista lives counter. |
| `0x9e829` | 8-bit | Heavy Machinery lives counter. |
| `0x9e88d` | 8-bit | Castle Machinery lives counter. |
