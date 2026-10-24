# Crash Bandicoot 1 — 100% Completion Inventory

> **Sources**, each fact labelled with one of them:
> - **measured**: the headless harness (`tools/achievement-harness/`) on the real `SCUS-94900 — Crash Bandicoot
>   (USA)` disc, `PCSX-ReARMed r26 ff81ed1`.
> - **c1**: the wurlyfox/c1 decompilation of Crash Bandicoot, <https://github.com/wurlyfox/c1> (`src/common.h`
>   `LID_*`, `src/globals.h`, `src/main.c`, `src/title.c`, `src/level.c`).
> - **community**: the Crash Bandicoot Wiki (Fandom), <https://crashbandicoot.fandom.com/wiki/Gem>,
>   [Colored_Gem](https://crashbandicoot.fandom.com/wiki/Colored_Gem),
>   [Gem_path](https://crashbandicoot.fandom.com/wiki/Gem_path), [Key](https://crashbandicoot.fandom.com/wiki/Key),
>   [Password](https://crashbandicoot.fandom.com/wiki/Password),
>   [The_Great_Hall](https://crashbandicoot.fandom.com/wiki/The_Great_Hall),
>   [100%_Completion](https://crashbandicoot.fandom.com/wiki/100%25_Completion), the boss-fight pages; StrategyWiki,
>   <https://strategywiki.org/wiki/Crash_Bandicoot/Secrets>; TCRF,
>   <https://tcrf.net/Crash_Bandicoot/Regional_Differences>; the PSX Data Center page of SCUS-94900,
>   <https://psxdatacenter.com/games/U/C/SCUS-94900.html>; the RetroAchievements code notes mirrored in
>   `apps/games/code-notes/crash-bandicoot-1.md`.
>
> Measured beats c1, which beats community. A community fact is a lead until a scenario measures it.

Everything the USA release asks of a player who finishes it fully: the stages, the bosses, the 26 gems, the two
keys and the two endings. Where each one lives in RAM is in `apps/games/code-notes/crash-bandicoot-1.md`.

## Stages

Map cursor `0x619C5` and level id `0x6188D`, **measured** for all 33 map stages: the 100% password (below) opens
the whole map, and the harness walked the map graph from it, entered every stage and read the level id once the
player had control. Every level id agrees with c1's `LID_*` name. The gem bit follows the bit-per-stage rule (bit
*n* + 1 counted from `0x61988` is map stage *n*); the bits of the two secret stages live in `0x619AC`.

| Cursor | Level id | Stage | Kind | Gem | Gem bit |
| --- | --- | --- | --- | --- | --- |
| `00` | `09` | N. Sanity Beach | stage | clear | `0xN61988` (bit 1) |
| `01` | `0c` | Jungle Rollers | stage | clear | `0xO61988` (bit 2) |
| `02` | `12` | The Great Gate | stage | clear | `0xP61988` (bit 3) |
| `03` | `0e` | Boulders | stage | clear | `0xQ61988` (bit 4) |
| `04` | `0f` | Upstream | stage | clear | `0xR61988` (bit 5) |
| `05` | `0a` | Papu Papu | boss | — | — |
| `06` | `15` | Rolling Stones | stage | clear | `0xT61988` (bit 7) |
| `07` | `11` | Hog Wild | stage | clear | `0xM61989` (bit 0) |
| `08` | `1a` | Native Fortress | stage | clear | `0xN61989` (bit 1) |
| `09` | `18` | Up the Creek | stage | clear | `0xO61989` (bit 2) |
| `0a` | `17` | Ripper Roo | boss | — | — |
| `0b` | `20` | The Lost City | stage | **green** | `0xQ61989` (bit 4) |
| `0c` | `1c` | Temple Ruins | stage | clear | `0xR61989` (bit 5) |
| `0d` | `14` | Road to Nowhere | stage | clear | `0xS61989` (bit 6) |
| `0e` | `13` | Boulder Dash | stage | clear | `0xT61989` (bit 7) |
| `0f` | `23` | Sunset Vista | stage | clear | `0xM6198a` (bit 0) |
| `10` | `21` | Koala Kong | boss | — | — |
| `11` | `06` | Heavy Machinery | stage | clear | `0xO6198a` (bit 2) |
| `12` | `03` | Cortex Power | stage | clear | `0xP6198a` (bit 3) |
| `13` | `05` | Generator Room | stage | **orange** | `0xQ6198a` (bit 4) |
| `14` | `07` | Toxic Waste | stage | **blue** | `0xR6198a` (bit 5) |
| `15` | `08` | Pinstripe | boss | — | — |
| `16` | `16` | The High Road | stage | clear | `0xT6198a` (bit 7) |
| `17` | `2e` | Slippery Climb | stage | **red** | `0xM6198b` (bit 0) |
| `18` | `28` | Lights Out | stage | **purple** | `0xN6198b` (bit 1) |
| `19` | `1d` | Jaws of Darkness | stage | clear | `0xO6198b` (bit 2) |
| `1a` | `37` | Castle Machinery | stage | clear | `0xP6198b` (bit 3) |
| `1b` | `1b` | Nitrus Brio | boss | — | — |
| `1c` | `29` | The Lab | stage | **yellow** | `0xR6198b` (bit 5) |
| `1d` | `2c` | The Great Hall | hall | — | — |
| `1e` | `1f` | Dr. Neo Cortex | boss | — | — |
| `1f` | `2a` | Fumbling in the Dark | secret | clear | `0xM619ad` (bit 0) |
| `20` | `1e` | Whole Hog | secret | clear | `0xO619ae` (bit 2) |

- **Map graph (measured).** The cursor walks the stages in cursor order with RIGHT/LEFT (UP/DOWN mostly the same;
  the direction flips on some screens, so RIGHT from Up the Creek goes back to Native Fortress). The secret
  stages hang off the path: UP from Boulder Dash (`0e`) to Whole Hog (`20`), UP from Lights Out (`18`) to
  Fumbling in the Dark (`1f`), DOWN back. The islands, in the community's words: N. Sanity Island up to Native
  Fortress, Wumpa Island from Up the Creek to Koala Kong, Cortex Island from Heavy Machinery on.
- **Gems (community, matched by measurement).** 26: 20 clear, 6 coloured. No boss and not The Great Hall has a
  gem; both secret stages have a clear gem. The gem bits of the table set by the 100% password are exactly
  `0x61988` = `0x2FBDF7BE` and `0x619AC` = `0x00140500` (**measured**), the mask of DuckStation's all-gems cheat;
  the colours come from the code notes and the community.
- **The Great Hall (c1, measured, community).** c1's `CoreObjectsCreate` loads no box code there; entered with
  26 gems it opens on a clear gem on a pedestal (screenshot). Holding UP from the entrance ended in a game over,
  so neither its exit nor the bridge was reached.
- **Stormy Ascent** (c1 `LID_STORMYASCENT` `22`) is on the disc but on no map path (community: cut from every
  retail release); the map graph above never reaches it.
- **Bonus levels (c1).** `24` Tawna 1, `25` Brio, `26` bonus, `33` Tawna 2, `34` Cortex. Not entered by the
  harness yet.

## Coloured gems and their paths (community)

| Gem | Awarded by | Opens a path in |
| --- | --- | --- |
| Green | The Lost City | Jungle Rollers, Castle Machinery (a shortcut without boxes) |
| Orange | Generator Room | Upstream |
| Blue | Toxic Waste | Rolling Stones, Cortex Power, Jaws of Darkness |
| Red | Slippery Climb | Native Fortress, Road to Nowhere |
| Purple | Lights Out | Boulder Dash |
| Yellow | The Lab | Lights Out, The Great Gate |

Boxes on a path count for the stage's clear gem, so these clear gems need a later coloured gem first: Jungle
Rollers (green), The Great Gate (yellow), Upstream (orange), Rolling Stones (blue), Native Fortress (red), Road to
Nowhere (red), Boulder Dash (purple, itself behind yellow), Cortex Power (blue) and Lights Out's purple gem
(yellow). Jaws of Darkness needs blue, which Toxic Waste awards earlier. The Japanese release moves the green
and red gems; this inventory is the USA layout.

## The gem rule

- **Community (USA):** every box of the stage, without dying past a checkpoint; a death before the first
  checkpoint does not stop it. Bonus-round boxes do not count, and dying in a bonus round does not stop it.
- **Measured** (`crash-bandicoot-1-advanced-achievements.md`): the Stage Clear screen (level `2d`) sets the bit
  about 280 frames after it loads when the box count reached the stage's boxes; a clear after a death past a
  checkpoint skips the screen altogether; an early death still gets the gem. Box totals measured: N. Sanity
  Beach 49, Jungle Rollers 38.

## Keys and secret stages

| Key | Won in | Opens | Bit |
| --- | --- | --- | --- |
| Sunset Vista key | Sunset Vista's Cortex bonus round | Whole Hog (UP from Boulder Dash) | `0xQ619ae` (bit 4) |
| Jaws of Darkness key | Jaws of Darkness' Cortex bonus round | Fumbling in the Dark (UP from Lights Out) | `0xP619ad` (bit 2) |

- **Measured:** the 8-symbol password `SSSOTXXO` loads both keys and no gem: `0x619AC` = `0x00100400`, key count
  `0x61A14` = 2. So the key bits are `0x619AD` bit 2 and `0x619AE` bit 4; which key is which comes from the code
  notes. The secret stages' entry points were measured on the map (above).
- **Community:** three Cortex tokens in a stage open its Cortex bonus round; the key is won in it, and the
  game offers a "key save" there.

## Bosses

| Boss | Level id | Hits (community) | Measured |
| --- | --- | --- | --- |
| Papu Papu | `0a` | 3 | 3: health `0x60DDC` → `+0x105` 3 → 0; the win goes straight to the map (game state `03`) |
| Ripper Roo | `17` | 3 | level id only |
| Koala Kong | `21` | 4 | level id only |
| Pinstripe Potoroo | `08` | 6 | level id only |
| Dr. Nitrus Brio | `1b` | 9 (6 on the blobs, then 3 on the monster; the code notes say 5) | level id only |
| Dr. Neo Cortex | `1f` | 5 | level id only |

The code notes give health reads for each (`0x60DDC` chains, Koala Kong through `0x61898`); c1 puts the
`fog_z` global at `0x61898`, so that chain needs a measurement before use.

## Endings

| Ending | What triggers it (community) | What RAM shows |
| --- | --- | --- |
| Normal | Cortex beaten: he falls from the airship; Crash and Tawna fly off | c1 names `LID_GAMEWIN` (`39`) the ending level and `CoreObjectsCreate` treats it as a cutscene (no HUD); not reached in the harness |
| Secret (100%) | The Great Hall entered with the gems: the clear gems form a bridge to the balcony, where Tawna waits; then the bosses' epilogue and the credits. Cortex is not fought | The hall is level `2c` (measured); the switch to the ending level is not measured |

The in-game percentage tops out at 100%, which the 26th gem forces (community). The 100% password loads
`0x61974` (c1 `percent_complete`) = 100 (**measured**).

## Passwords

The title menu reads START, LOAD GAME, PASSWORD, OPTIONS; PASSWORD opens the "ENTER PASSWORD" screen (title
state `0x618D4` = `0e`), typed with the four face buttons (**measured**).

| Fact | Source |
| --- | --- |
| A password of 8 symbols is checked as soon as the 8th is typed; `XXXXXXXX` shows "INVALID PASSWORD", and CROSS then returns to the main menu | measured |
| A password starting with two triangles is read to 24 symbols; CROSS after a valid one loads the island map | measured |
| The 8-symbol password stores the progress point and the keys; the 24-symbol one adds the 26 gem bits | community, matches every password below |
| The game shows one after a Tawna bonus round, a gem, a key, and on declining the continue at the game over ("final password") | community |
| A loaded password sets c1 `levels_unlocked` `0x61948`, `level_count` `0x61944`, `cur_map_level` `0x618DC`, the gem and key pools `0x61988` / `0x619AC` and their saved copies `0x61A1C` / `0x61A20`, `gem_count` `0x61A10`, `key_count` `0x61A14` and `percent_complete` `0x61974`, all on the title level `19`; the map opens with the cursor on the last unlocked stage and 4 lives | measured |

Passwords typed in the harness (T triangle, S square, O circle, X cross; every one from the community sources
above, none of them generated here):

| Password | Community label | Unlocked | `0x61988` | `0x619AC` | Gems | Keys | % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `XSXOXSTX` | Rolling Stones | 7 | `00000000` | `00000000` | 0 | 0 | 13 |
| `SSSOTXXO` | Hog Wild, 2 keys | 8 | `00000000` | `00100400` | 0 | 2 | 22 |
| `TTSOXOTXSXOSOXSSSOOXTTTO` | N. Sanity Beach gem | 1 | `00000002` | `00000000` | 1 | 0 | 1 |
| `TTTTOXTTXXTOSOXTTOSXXSTT` | skip to the third island | 24 | `00040000` | `00000000` | 1 | 0 | 53 |
| `TTXXSXOTOOSTTXOXOTOXSSSS` | Slippery Climb | 24 | `01357336` | `00000000` | 14 | 0 | 68 |
| `TTTSXXOXXSOXXXXOSTSOOSST` | The Lab, before Cortex | 29 | `2F35F3BE` | `00000000` | 21 | 0 | 87 |
| `TTTTXSTTTTSXTOTTTOSTXXXX` | 100%: every stage, gem and key | 31 | `2FBDF7BE` | `00140500` | 26 | 2 | 100 |

So a password reaches any late stage without a RAM write. A password changes the gem and key bits on the title
level (`19`), never on the Stage Clear level (`2d`) or in a stage, which is what keeps the gem conditions from
firing on one. A password only holds a combination some community source published: The Lab's leaves out
exactly the gems of Up the Creek, Cortex Power, The High Road and the two secret stages.

## Still for the in-game check (DuckStation)

- **The secret ending:** with all 26 gems, cross The Great Hall's bridge and watch which level the ending loads
  (expected c1 `LID_GAMEWIN`, `39`); the harness fell off.
- **The normal ending:** beat Cortex and see the ending; nothing past entering his fight was played.
- **Boss hit counts** other than Papu Papu's, Brio's above all (9 or 5).
- **Keys:** win each Cortex bonus round and see the key; the harness entered no bonus round.
- **Whether a gem or key save shows a password that reloads the same gem and key bits.** Every password above
  was typed, none was read off the game's own save screen.
