# RetroAchievements Developer Docs (vendored)

> **Source:** <https://github.com/RetroAchievements/docs> — `docs/developer-docs/`, commit `669062a`.
> Published at <https://docs.retroachievements.org/developer-docs/>.
> **Licence:** GPL-3.0 (see `LICENSE` in this directory). © RetroAchievements contributors.

Vendored verbatim so achievement logic is written against the specification rather than guessed at.
Do not edit these files — refresh them from upstream instead. RetroPlatinas' own notes on Crash
Bandicoot conditions live in `../crash-bandicoot-1-level-achievements.md`.

## Read these before writing or debugging any `mem_addr`

| File | Why |
| --- | --- |
| `condition-syntax.md` | memory sizes (`0xH`, `0xW`, …), prefixes (`d`, `p`), every logical flag |
| `why-delta.md` | why a condition must describe *the moment* it becomes true, not a state |
| `delta-values.md`, `prior-values.md` | `d` (previous frame) vs `p` (previous *different* value) |
| `hit-counts.md` | `.N.` — a condition that must hold N frames before counting as true |
| `flags/resetif.md` | the start-marker/cancel pattern; resetting on a known state such as the title screen |
| `flags/pauseif.md` | suspending evaluation instead of resetting it |
| `flags/andnext-ornext.md` | `N:` / `O:` — attaching several conditions to one hit count or `ResetIf` |
| `flags/addaddress.md` | `I:` — dereferencing pointers |
| `real-examples/` | worked solutions to the recurring traps |

Serialised forms the docs describe only via the graphical editor, taken from the rcheevos parser
(`src/rcheevos/condition.c`): conditions are joined with `_`; a hit count is appended as `.N.` (or
`(N)`); flags are a prefix followed by `:`.
