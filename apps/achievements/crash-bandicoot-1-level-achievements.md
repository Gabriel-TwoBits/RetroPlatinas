# Crash Bandicoot 1 — Level-Completion Achievements (Batch 1)

> **Addresses:** from the Crash Bandicoot code notes — see `apps/games/code-notes/crash-bandicoot-1.md` (RetroAchievements game id 10434).
> **Validated in-game** on DuckStation against `SCUS-94900 — Crash Bandicoot (USA)`.

The first six "complete the level" achievements. Seed them as `Achievement` rows with
`python manage.py seed_crash1_level_achievements` (idempotent). Each is worth 5 points and is
published as `community`.

## Achievements

| Title | Stage id (`0x619c5`) | `mem_addr` |
| --- | --- | --- |
| N. Sanity Beach | 0 | `0xH61998=1_d0xH61998=0_0xH61994=0_0xH619c5=0_0xW618cc!=0` |
| Jungle Rollers | 1 | `0xH61998=1_d0xH61998=0_0xH61994=0_0xH619c5=1_0xW618cc!=0` |
| The Great Gate | 2 | `0xH61998=1_d0xH61998=0_0xH61994=0_0xH619c5=2_0xW618cc!=0` |
| Boulders | 3 | `0xH61998=1_d0xH61998=0_0xH61994=0_0xH619c5=3_0xW618cc!=0` |
| Upstream | 4 | `0xH61998=1_d0xH61998=0_0xH61994=0_0xH619c5=4_0xW618cc!=0` |
| Rolling Stones | 6 | `0xH61998=1_d0xH61998=0_0xH61994=0_0xH619c5=6_0xW618cc!=0` |

## Logic

The condition fires on the frame the results screen appears, while a stage is loaded:

| Term | Meaning |
| --- | --- |
| `0xH61998=1_d0xH61998=0` | the results-screen flag just rose 0→1 (rising edge, not a level state) |
| `0xH61994=0` | overworld status is "in a stage", not "on the map" |
| `0xH619c5=<id>` | the stage that was just finished |
| `0xW618cc!=0` | the Aku Aku pointer is non-null, i.e. a stage's RAM is actually loaded |

Two guards exist because of measured false positives, not caution:

- **The rising edge** is needed because `0x61998` also reads 1 during the boot sequence (on the
  "Sony Computer Entertainment America" screen), before the title menu. A bare `0xH61998=1`
  unlocks every achievement the moment the game boots.
- **The pointer guard** is needed because at boot `0x61994` and `0x619c5` are both still 0 —
  identical to "in a stage, stage 0" — so the rising edge alone still false-fires on stage 0.
  During boot no stage is loaded and `0x618cc` reads 0; inside a stage it holds a real pointer
  (`0x9276D0` on the N. Sanity Beach results screen).

`0x61a68` ("FF = finished/quit a level" in the code notes) is **not** usable: it reads 0 while
playing, on the results screen and on the map, spiking to 255 only transiently on stage entry.

Quitting a level skips the results screen, so no separate anti-quit guard is needed.
