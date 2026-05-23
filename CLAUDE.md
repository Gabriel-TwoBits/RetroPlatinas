# CLAUDE.md

Guidance for Claude Code working in this repository. See `README.md` for human setup instructions.

## Project

RetroCheevos is an alternative to RetroAchievements.org with full protocol compatibility (rcheevos). MVP targets Crash Bandicoot 1 (PS1).

- **Full roadmap (40 PRs):** `/run/media/nitrus/HD/RetroCheevos/PLANO_DESENVOLVIMENTO.md` (external drive)
- **Current state:** `git log` — do not document progress here, it decays fast

## Stack

Django 5.2 · Python 3.12 · Postgres 16 · Redis 7 · uv · podman-compose · Fedora 44 + SELinux Enforcing

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

**Naming** — kebab-case in all repo files, directories, and configs. Only forced exception: gettext locale directories that require a country code (`pt_BR`, `en_US`). That's why we use `pt` and `en` — no underscores needed.

**i18n mandatory** — every user-visible string is born inside `{% trans %}` / `{% blocktrans %}` (templates) or `gettext_lazy` (forms/models). No "we'll translate later" PRs.

**Comments** — default is none. Only add a comment when the *why* is non-obvious.

**No opportunistic cleanup** — a bugfix is not a refactor. Don't introduce abstractions beyond what the task requires.

## Workflow

- Branch off `main` as `pr/NN-slug-curto` where `NN` matches the PR number in the roadmap.
- One commit per PR (or a few focused ones).
- **Never `git push` without explicit user authorization.** This has caused incidents.
- Never use `--force`, `--no-verify`, or `reset --hard` unless explicitly asked.
- There is no PR mechanism — push directly to `main` when approved.

## Common traps

- **`AUTH_USER_MODEL`** is only safe to change before any `migrate` has run. If changed after: `podman-compose down -v` to destroy the Postgres volume before migrating.
- **`userns_mode: keep-id`** in `compose.yml` is required for Podman rootless UID mapping. Do not remove it.
- **SELinux:** bind mounts use `:Z` (already set). If you see permission errors on bind mounts, check SELinux context first.
- **`gettext` lives in the container only.** Run `makemessages` and `compilemessages` inside the container, not on the host.
- **After `makemessages`:** remove the `#, fuzzy` flag from the `.po` header and set `Language:` correctly before running `compilemessages`, or Django silently ignores the translations.

## i18n workflow

When any UI-touching change adds new visible strings:

1. `{% load i18n %}` at the top of the template (once per file).
2. Wrap strings: `{% trans "..." %}` for simple strings, `{% blocktrans %}...{% endblocktrans %}` for strings with variables.
3. In forms/models: `from django.utils.translation import gettext_lazy as _`, then `_("string")`.
4. `podman-compose exec web python manage.py makemessages -l pt -l en --ignore=staticfiles`
5. Fill in `msgstr` entries in `locale/pt/LC_MESSAGES/django.po`.
6. `compilemessages`, then commit both `.po` and `.mo` files.
