# RetroPlatinas — Server

Alternative platform to RetroAchievements.org with full protocol compatibility (rcheevos).

Copyright (C) 2026 Gabriel-TwoBits. Licensed under the [GNU AGPL-3.0](LICENSE) —
if you run a modified version as a network service, you must offer its source to your users.

## Prerequisites

- **Podman** 4+ (`podman --version`)
- **podman-compose** — the native `podman compose` subcommand requires an external docker-compose provider that is usually not installed. Install via pip:

```bash
pip install --user podman-compose
```

## Initial setup

```bash
# 1. Clone the repository
git clone ssh://git@codeberg.org/Gabriel-TwoBits/retroplatinas.git
cd retroplatinas

# 2. Copy environment variables
cp .env.example .env
# Edit .env if you need different passwords in dev

# 3. Start services (builds the image on first run)
podman-compose --in-pod=false up --build
```

The server will be available at http://localhost:8000

## Common commands

```bash
# Apply migrations
podman-compose exec web python manage.py migrate

# Create a superuser for the admin
podman-compose exec web python manage.py createsuperuser

# Open Django shell
podman-compose exec web python manage.py shell

# Run tests
podman-compose exec web python -m pytest

# Regenerate lockfile after changing dependencies in pyproject.toml
# (the image installs exactly what uv.lock pins; a stale lock fails the build)
podman-compose exec web uv lock
# Then: git add uv.lock && git commit

# Add a new dependency
podman-compose exec web uv add package-name
# Then: git add pyproject.toml uv.lock && git commit
```

## Accessing the admin

http://localhost:8000/admin/ → log in with the superuser created above.

## Badges, game icons and avatars

Upload an achievement's badge or a game's icon in the admin; until one is uploaded, a neutral
placeholder is drawn in code. Emulators fetch them from RetroAchievements-compatible paths, served
by Django views (not by the `/media/` static serving, which exists in development only):

| Path | Image |
| --- | --- |
| `/Badge/<badge name>.png` | the badge, 64×64 |
| `/Badge/<badge name>_lock.png` | the grayscale locked badge, derived from the upload |
| `/Images/<game image name>.png` | the game icon, 96×96 (`000001` is reserved for the unknown-game placeholder) |
| `/UserPic/<username>.png` | an identicon drawn from the username, 128×128 |

API payloads carry these as absolute URLs with a `?v=` version that changes with the image:
DuckStation caches images by URL, and a missing URL makes rcheevos fetch RetroAchievements' own art.

## Sessions, presence and hardcore

`PlayerGame` (one row per user and game) records who plays what. `startsession` creates it,
records when the session started and moves its last-played time, `ping` (rc_client sends one
every 120 s while the emulator runs) stores the current rich presence, and an unlock also moves
last played. Each `ping` credits the time since the previous contact as playtime when the gap is
at most 4 minutes; a longer gap
(emulator paused, closed or offline) credits nothing, and so does a new `startsession`, which also
clears the previous session's rich presence. A session pinged within the last
5 minutes is "playing now" (`PlayerGame.objects.playing_now()`). Rarity counts a game's
`PlayerGame` rows as its players.

Hardcore follows what rcheevos actually sends:

- `h` on each `awardachievement` is trusted as the mode of that unlock. A hardcore unlock also
  records the softcore one and adds its points to both totals (no 2× hardcore points).
- `h` on `startsession`/`ping` only records the session's mode (`PlayerGame.hardcore`).
- There is no `resethardcore` request: disabling hardcore or loading a state happens inside the
  emulator, which then sends softcore unlocks.

With `DEBUG` on, `GET /api/test/presence/<username>/` returns that user's live sessions (game,
rich presence, mode, last ping) as JSON, or 404 for an unknown user. It is a test endpoint and
answers 404 whenever `DEBUG` is off.

## Anti-cheat

The `anticheat` app flags requests for manual review in the admin (**Anti-cheat → Suspicious
activities**, bulk actions *mark legitimate* / *mark cheating*, which record the reviewer and the
time). Flagging never blocks or bans a user. Thresholds are constants in
`apps/anticheat/detection.py`.

| Kind | Flagged when | Request outcome |
| --- | --- | --- |
| `invalid_signature` | `awardachievement` or `submitlbentry` arrives without `v`, or with a `v` that does not match | rejected (`missing_parameter` / `invalid_parameter`) |
| `rate_limited` | a user sends more than 30 `awardachievement` in a minute (once per window) | HTTP 429, which rc_client retries with backoff, so the unlock is delayed, not lost |
| `unlock_burst` | 10 achievements of one game unlocked within a minute (once per burst) | accepted |
| `early_unlock` | an unlock lands less than 30 s after the session's `startsession` | accepted |

`v` is the lowercase hex MD5 rcheevos signs every unlock and leaderboard entry with (`u` is the
username as sent):

| Request | `v` without `o` | `v` with `o` |
| --- | --- | --- |
| `awardachievement` | `md5(a + u + h)` | `md5(a + u + h + a + o)` |
| `submitlbentry` | `md5(i + u + s)` | `md5(i + u + s + o)` |

rcheevos sends `o` (seconds since the unlock or completion) only on retries and only when it is
not zero. An unlock carrying `o` is dated that far back, at most one day. A request crafted by hand
(curl, a test script) must sign itself the same way — `award_validation_hash` and
`leaderboard_validation_hash` in `apps/anticheat/detection.py` compute it.

## Running in background

```bash
podman-compose --in-pod=false up -d   # start in background
podman-compose logs -f web    # follow Django server logs
podman-compose down           # stop all (data persists in volumes)
podman-compose down -v        # stop AND delete volumes (full reset)
```

## Troubleshooting

### `podman-compose up` fails: `--userns and --pod cannot be set together`

podman-compose 1.x creates a pod by default, which is incompatible with the
`userns_mode: keep-id` this project uses. Pass `--in-pod=false` on every `up`
(already shown in the commands above):

```bash
podman-compose --in-pod=false up --build
```

### SELinux: permission denied on bind mounts

Fedora uses SELinux in Enforcing mode. The `compose.yml` already adds `:Z` to bind mounts,
which relabels the directory automatically. If you still get a permission error:

```bash
# Check SELinux context of the directory
ls -lZ .

# Relabel manually if needed
chcon -Rt svirt_sandbox_file_t .
```

### Ownership of files created by the container

The container uses `userns_mode: keep-id`, which maps your host UID into the container.
Files created inside the container will appear with your user's ownership on the host.

If you run into ownership issues, verify your UID matches what Podman is using:

```bash
podman-compose exec web id
```

### Port 8000 already in use

```bash
# Check which process is using it
ss -tlnp | grep 8000
# Change the port in compose.yml: "8001:8000"
```

### Container `web` restarting in a loop

```bash
# View full logs
podman-compose logs web

# Common cause: db or redis not ready yet
# The compose already uses healthchecks, but on slow hardware you may need more retries
```
