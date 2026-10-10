# How AI generates achievements

The recipe an AI agent (Claude Code) follows to design, validate and ship an achievement set without a
human relaying screenshots from the emulator. It produced the Crash Bandicoot (USA) set: 16
achievements, 2 leaderboards and the rich presence script, each one validated against the real disc
before a person ever booted the game.

The short version: **never write a condition the agent cannot run.** Every condition is evaluated by
the real rcheevos runtime against the real game, frame by frame, in a headless emulator the agent
drives itself. The human's DuckStation check stays the final gate, but it confirms instead of debugging.

## Why the obvious approach fails

Writing conditions from community code notes and asking a person to test them is a slow, blind loop:
the agent guesses, the person plays, sends a screenshot, the agent guesses again. It also hides wrong
assumptions. For Crash, the RA code note called `0x61998` "on results screen"; it is really the
engine's `is_first_zone` flag, which pulses on every level load **and every respawn**, so the first
level-completion achievements unlocked on death. No amount of guessing finds that quickly; measuring
RAM finds it in one run.

## 1. Ground truth before conditions

1. Read `ra-developer-docs/README.md` and the files it lists — condition semantics come from the
   specification, not from trial and error.
2. Collect every RAM source for the game, ranked by trust: a decompilation (for Crash,
   [wurlyfox/c1](https://github.com/wurlyfox/c1), which names the `gool_globals` block at `0x8006188C`),
   tool scripts (ScriptHawk, emulator cheat databases), then RA code notes. Code notes describe other
   regions and revisions as often as not; treat them as leads.
3. Record what is known, with sources and confidence, in `apps/games/code-notes/<game>.md`. Correct
   it as measurements come in.

## 2. A harness the agent can drive

`tools/achievement-harness/` (see its README) is a headless PS1 emulator built for this loop:

- A small C libretro frontend loads a PS1 core (pcsx_rearmed by default; swanstation, the DuckStation
  fork, with a real BIOS) and the user's disc, with no window.
- The vendored rcheevos runtime evaluates the repo's own conditions — built by the seed commands, never
  copied strings — after every frame, exactly as DuckStation's `rc_client` does.
- Python drives it: pad input per frame, 2 MB RAM reads, pointer chains, save/load states, PNG
  screenshots (the agent reads them to navigate menus), per-frame CSV traces of named probes.
- States are recipes from a cold boot, never committed files, so any checkout reproduces them.

**Prove the harness is faithful before trusting it**: reproduce a bug already seen in the real
emulator. The Crash harness reproduced the "level achievement fires on death" bug on the respawn
frame, and then found two false positives nobody had reported (pause → quit, and an idle title screen
when the attract demo returns).

## 3. Measure, then design

1. Record traces of the scenarios that matter: cold boot and attract demo, entering a stage, death and
   respawn, pause → quit, the real clear, game over. `analyze.py --timeline` lists the frames where each
   probe changed.
2. Pick signals that change **only** on the event. For Crash: the level id `0x6188d` moving into the
   Stage Clear level `0x2D`, the game state `0x618d1`, the attract-demo flag `0x61a30`, the respawn
   counter `0x618a1`.
3. Write the condition with the traps in mind (`CLAUDE.md`, "Writing `mem_addr`"): rising edges for
   events, a guard that is non-zero only while the game really runs, no constant written as a bare
   `0x2d` (that is a memory read — use decimal or `h2D`), true-at-load suppression after state loads.
4. Check the syntax: `scripts/check-mem-addr.sh` (triggers, leaderboards and rich presence).

## 4. Scenarios: the event and its look-alikes

Every achievement gets a scenario that **must** fire it and the look-alike scenarios that **must not**:
death, death after a checkpoint, pause → quit, game over, results → map, the attract demo, other stages.
They live in `scenarios.py` and run inside `pytest` (`test_achievement_harness.py`, skipped without the
disc), so a later change that breaks a condition fails the suite.

Reaching the real event needs someone to play. `explore.py` does it: a Go-Explore search over input
chunks, keeping the states that make progress and restarting from them, toward a goal (a stage clear,
a boss, a checkpoint, a gem). It cleared N. Sanity Beach after 1,608 attempts. The result is a
deterministic input plan in `plans/`, replayed from a cold boot by every later run.

When the search cannot reach an event in reasonable time (99 lives, stages it never cleared), a RAM
poke is acceptable **only** as secondary evidence, labelled as such, and the event goes on the human's
checklist.

## 5. Orchestration

The work ran as a pipeline of AI agents, one roadmap PR at a time:

1. **A brief** of binding decisions (the user's answers, conventions, the definition of done) that every
   agent reads first, kept somewhere that survives a reboot (`.cache/orchestration/`, gitignored — `/tmp`
   was wiped twice mid-run).
2. **Implement**: one agent per PR, on its own branch, writing the seed, the scenarios, the tests and the
   docs, and running the definition of done.
3. **Review**: three independent read-only reviewers, each with one lens —
   - *logic, adversarially*: try to break every condition, running the harness to attack it;
   - *conventions*: the global and project `CLAUDE.md` rules, line by line, and commit messages;
   - *acceptance and evidence*: re-run a claimed scenario to confirm it, check the untested parts are
     listed honestly.
4. **Finish**: one agent verifies each finding (fixing the real ones, rejecting the rest with a reason),
   re-validates in the harness, runs the whole definition of done and fast-forwards the branch.

The adversarial reviewer is what caught the subtle bug no planned scenario did: after a death past a
checkpoint, Crash skips the Stage Clear screen and goes straight to the map, so the level achievements
needed a second path.

Achievement work ran in a separate git worktree with its own database and a throwaway container
(the disc and BIOS mounted read-only), in parallel with the site work, and was merged at the end.

## 6. Hand-off to the human

Each achievement doc in this directory ends with **"Still for the in-game check (DuckStation)"**: the
exact events the harness could not prove (unreached stages, poked values, bonus rounds, DuckStation's
own CD timing). The person tests those, as an unofficial achievement with "Test Unofficial
Achievements" if the achievement is new, and makes it official once it behaves.

## Checklist for a new achievement

1. Sources and code notes updated; the addresses it reads are measured in a trace.
2. Condition built by a seed command (idempotent, updates existing rows by title).
3. `check-mem-addr.sh` passes.
4. A scenario that fires it and the look-alike scenarios that must not, all `OK` in the harness.
5. Three-lens review; findings fixed or rejected with a reason.
6. Definition of done passes, harness included (with the disc mounted).
7. Its doc lists what is still for the in-game check; the user validates it in DuckStation.
