# CLAUDE.md

Guidance for Claude Code working in this repository. See `README.md` for human setup instructions.

## Project

RetroCheevos is an alternative to RetroAchievements.org with full protocol compatibility (rcheevos). MVP targets Crash Bandicoot 1 (PS1).

- **Full roadmap (40 PRs):** `/mnt/HD/RetroCheevos/PLANO_DESENVOLVIMENTO.md` (external drive)
- **Current state:** `git log` — do not document progress here, it decays fast

## Stack

Django 5.2 · Python 3.12 · Postgres 16 · Redis 7 · uv · podman-compose · Debian 13 (trixie)

**Everything runs in the container. Never call `python` or `manage.py` on the host.** All commands go through:

```bash
podman-compose exec web python manage.py migrate
podman-compose exec web python manage.py makemigrations <app>
podman-compose exec web python manage.py createsuperuser
podman-compose exec web python -m pytest
podman-compose exec web python manage.py makemessages -l pt -l en --ignore=staticfiles
podman-compose exec web python manage.py compilemessages
```

## Conventions (non-negotiable)

**Commits** — English, Conventional Commits, **one line, no body**.
- Good: `feat: add game search endpoint`
- Bad: `adiciona busca de jogo` / multi-line with bullets

**Naming** — kebab-case in all repo files, directories, and configs. Forced exceptions: (1) gettext locale directories that require a country code (`pt_BR`, `en_US`) — that's why we use `pt` and `en`, no underscores needed; (2) Python modules and packages, which must be importable and so stay snake_case (migrations, management commands, app modules).

**i18n mandatory** — every user-visible string is born inside `{% trans %}` / `{% blocktrans %}` (templates) or `gettext_lazy` (forms/models). No "we'll translate later" PRs.

**Comments** — default is none. Only add a comment when the *why* is non-obvious.

**A bugfix is not a refactor** — don't introduce abstractions beyond what the task requires. This is not licence to walk past a failing check: see **Definition of done**.

## Documentation

- **Language** — repo docs are written in **English**, like the rest of the codebase (only user-facing UI strings are i18n'd).
- **Location** — reference/design docs live beside the app they describe (`apps/<app>/…`). Game memory maps live in `apps/games/code-notes/<game-slug>.md`, one file per game.
- **Filenames** — kebab-case (`.md`), same as every other non-module file.
- **Structured technical references use tables** — e.g. a memory map is `| Address | Type | Description |`.
- **Credit external sources** — a short header with the URL and attribution.
- **No ephemeral progress** — same rule as the roadmap: state and history belong in `git log`, not in docs.
- **Seed data is not a data migration** — data migrations run against the test DB and collide with test fixtures. Seed reference data with a fixture (`loaddata`) or an idempotent management command instead (e.g. `manage.py seed_crash1_code_notes`).

## Workflow

- Branch off `main` as `pr/NN-slug-curto` where `NN` matches the PR number in the roadmap.
- One commit per PR (or a few focused ones).
- **Never `git push` without explicit user authorization.** This has caused incidents.
- Never use `--force`, `--no-verify`, or `reset --hard` unless explicitly asked.
- There is no PR mechanism — push directly to `main` when approved.

## Definition of done

No task is finished until all of these pass, in the container, with the real output shown:

```bash
podman-compose exec web python -m pytest              # whole suite, not just your file
podman-compose exec web ruff check apps/ && podman-compose exec web ruff format --check apps/
podman-compose exec web python manage.py check
podman-compose exec web python manage.py makemigrations --check --dry-run
podman-compose build                                  # the deploy image must build
```

Every one of these must pass over the **whole tree**, not just the files you touched. A failing test,
lint error or unformatted file is a defect in the repository — fix it, whoever wrote it, and commit
the fix separately from the feature. Then re-check every commit of the change against this file and
the user's global `CLAUDE.md`, line by line.

## Common traps

- **`AUTH_USER_MODEL`** is only safe to change before any `migrate` has run. If changed after: `podman-compose down -v` to destroy the Postgres volume before migrating.
- **`userns_mode: keep-id`** in `compose.yml` is required for Podman rootless UID mapping. Do not remove it.
- **Bind mounts:** the `:Z` suffix (SELinux relabel) is inert on Debian 13 — harmless, kept for portability. Dev host migrated from Fedora 44 to Debian; there is no SELinux/`dnf`/`rpm` here — use `apt`.
- **`podman-compose` orphaned:** it was `pip --user` installed for python3.14; the Debian upgrade moved system `python3` to 3.13 (no `pip`), so the module is unreachable and `podman-compose` fails with `ModuleNotFoundError: podman_compose`. Fix: `sudo apt install podman-compose`.
- **`gettext` lives in the container only.** Run `makemessages` and `compilemessages` inside the container, not on the host.
- **After `makemessages`:** remove the `#, fuzzy` flag from the `.po` header and set `Language:` correctly before running `compilemessages`, or Django silently ignores the translations.

## Writing `mem_addr` (achievement conditions)

**Mandatory before writing or debugging any condition:** read
`apps/achievements/ra-developer-docs/README.md` and the files it lists. The RetroAchievements
developer documentation is vendored into that directory precisely so the logic is written against
the specification instead of reverse-engineered by trial and error in the emulator. Guessing at
condition semantics has already cost several play-through debugging sessions.

The server never evaluates `mem_addr` — rcheevos does, inside the emulator. Automated tests can
only prove the backend cycle and the shape of the expression. **Every `mem_addr` must be
validated in game before it ships.**

**Check the syntax before asking anyone to boot a game.** The rcheevos parser is vendored in
`vendor/rcheevos/`, so a malformed condition is caught locally instead of silently becoming an
"unsupported" achievement in the emulator:

```bash
podman-compose exec web bash scripts/check-mem-addr.sh '0xH61998=1_d0xH61998=0'
```

`apps/achievements/tests.py` runs it over every generated condition, so `pytest` already fails on a
syntax error. It compiles on first use into `.cache/` (gitignored).

- **Code notes are best-effort, not truth.** They come from the RA community and describe another
  region/revision as often as not. Verify each address before relying on it.
- **Console RAM is zeroed at reset, so `0` means "not initialised yet", not "state zero".** Any
  address that legitimately holds `0` during play (`0x61994` = in a stage, `0x619c5` = stage 0)
  is indistinguishable from the boot sequence. Add a guard that is provably non-zero only when
  the game is really running — a pointer (e.g. `0xW618cc!=0`) is the reliable one.
- **Prefer rising edges to level comparisons** for anything that means "an event happened":
  `0xHaddr=1_d0xHaddr=0` instead of `0xHaddr=1`. A transient spike during boot will otherwise
  unlock the achievement the moment the game loads.
- **rcheevos suppresses achievements whose condition is already true at load**, so a bad condition
  that is true on the results screen will not re-fire after a save-state load. Re-test from a
  state saved *before* the trigger.
- **Debug memory with Rich Presence.** Put a dump in `Game.rich_presence_patch` and read the
  values off the emulator overlay; clear it afterwards:
  ```
  Format:Val
  FormatType=VALUE

  Display:
  ovw @Val(0xH61994) stg @Val(0xH619c5) res @Val(0xH61998)
  ```
- **DuckStation only fetches the patch (conditions + Rich Presence) when the game loads.** A reset
  is not enough — close the game and open it again, or you are testing the old conditions.

### Testing a `community` achievement in game

`community` maps to `Flags=5` (*unofficial*). Enable "Test Unofficial Achievements"
(`Cheevos/UnofficialTestMode`) and reload the game, then read the **achievement list**, not the
pause-screen counter:

- The "X of Y" counter only counts `core` achievements, so it stays put no matter how many
  unofficial ones loaded. Unofficial ones live in their own list bucket, suffixed `(Unofficial)`.
- The in-game popup **does** fire for them, which is what proves the `mem_addr` is right.
- rcheevos **never sends `awardachievement` for an unofficial achievement**, so no `UserUnlock`
  and no points — by design, and the server cannot override it. Promote to `verified` to see the
  full cycle. `handle_awardachievement` ignores `status`/`flags`, so both go through the same code.

## i18n workflow

When any UI-touching change adds new visible strings:

1. `{% load i18n %}` at the top of the template (once per file).
2. Wrap strings: `{% trans "..." %}` for simple strings, `{% blocktrans %}...{% endblocktrans %}` for strings with variables.
3. In forms/models: `from django.utils.translation import gettext_lazy as _`, then `_("string")`.
4. `podman-compose exec web python manage.py makemessages -l pt -l en --ignore=staticfiles`
5. Fill in `msgstr` entries in `locale/pt/LC_MESSAGES/django.po`.
6. `compilemessages`, then commit both `.po` and `.mo` files.
