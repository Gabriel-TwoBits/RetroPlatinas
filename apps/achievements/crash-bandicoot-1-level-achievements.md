# Crash Bandicoot 1 — Level-Completion Achievements (Batch 1)

> **Addresses:** from the Crash Bandicoot code notes — see `apps/games/code-notes/crash-bandicoot-1.md` (RetroAchievements game id 10434).
> **Condition syntax:** see the vendored `ra-developer-docs/` in this directory.
> **Validated in-game** on DuckStation against `SCUS-94900 — Crash Bandicoot (USA)`.

The first six "complete the level" achievements. Seed them as `Achievement` rows with
`python manage.py seed_crash1_level_achievements` (idempotent). Each is worth 5 points and is
published as `community`.

Every Crash seed command (this one and `seed_crash1_code_notes`) first gets or creates the game
with the hash of its only supported disc, so `gameid` recognises it on a fresh database:

| MD5 (rcheevos PlayStation hash) | Label |
| --- | --- |
| `35386fd0891e594c9b6d8a4a5baa0027` | Crash Bandicoot (USA) — SCUS-94900 |

## Achievements

Every condition is `build_mem_addr(stage_id)`; only the stage id changes.

| Title | Stage id (`0x619c5`) |
| --- | --- |
| N. Sanity Beach | 0 |
| Jungle Rollers | 1 |
| The Great Gate | 2 |
| Boulders | 3 |
| Upstream | 4 |
| Rolling Stones | 6 |

```
N:0xW618cc!=0_N:0xH61994=0_N:0xH619c5=<id>_0xH61998=0.300._R:0xH61994=1_R:0xW618cc=0_0xH61998=1_d0xH61998=0_0xH619c5=<id>_0xH61994=0
```

## Logic

This is the standard "start marker, cancel, trigger at the end" shape described in
`ra-developer-docs/flags/resetif.md`.

| Part | Role |
| --- | --- |
| `N:0xW618cc!=0_N:0xH61994=0_N:0xH619c5=<id>_0xH61998=0.300.` | **arm.** `AndNext` chains three checks onto one hit count: a stage is loaded (Aku Aku pointer non-null), the player is inside a stage, it is *this* stage, and the results screen is off. Only counts as true once it has held for 300 frames — i.e. the player really played the level |
| `R:0xH61994=1_R:0xW618cc=0` | **disarm.** Returning to the map, or unloading the stage, resets every hit count |
| `0xH61998=1_d0xH61998=0_0xH619c5=<id>_0xH61994=0` | **trigger.** The results-screen flag rises 0→1 on this frame, in this stage |

Each guard exists because of a *measured* false positive, not caution:

- **The rising edge (`d`)** — `0x61998` also reads 1 during the boot sequence (on the "Sony
  Computer Entertainment America" screen). A bare `0xH61998=1` unlocks everything at boot.
- **The pointer** — at boot `0x61994` and `0x619c5` both read 0, which is indistinguishable from
  "inside stage 0". `0x618cc` is null until a stage's RAM is loaded (`0x9276D0` in game).
- **The 300-frame arm** — the same `0x61998` spike happens again while a stage *loads*, by which
  point the pointer is already valid and `0x61994`/`0x619c5` already hold their in-stage values.
  A purely instantaneous condition therefore fires on stage entry. Requiring 300 frames of actual
  play before the trigger is even considered separates "loading" from "finished". `ResetIf` on the
  map re-arms it for the next attempt.

`0x61a68` ("FF = finished/quit a level" in the code notes) is **not** usable: it reads 0 while
playing, on the results screen and on the map, spiking to 255 only transiently on stage entry.

Quitting a level skips the results screen, so no separate anti-quit guard is needed.
