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

Badges are uploaded images named after their sequential number, as RetroAchievements names them
(`00001`, `00002`, …): upload one in the admin (**Achievements → Badges**) or from RAIntegration,
then set that name as the achievement's badge name. A badge's image never changes; new art is a new
badge. Staff may delete a badge no achievement uses. `00000` is the placeholder every achievement
shows until it gets a badge. Upload a game's icon in the game's admin page; until one is uploaded, a
placeholder is shown too. Placeholders are drawn in code. Emulators fetch the images from
RetroAchievements-compatible paths, served by Django views (not by the `/media/` static serving,
which exists in development only):

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

## Stats API

Read-only JSON for the public site, outside `dorequest.php` (`GET` only; an unknown user, game or
leaderboard answers 404 with `{"Error": …}`). The queries behind it live in `apps/core/stats.py`,
shared with the `dorequest.php` leaderboard handlers and the profile page.

| Path | Returns |
| --- | --- |
| `/api/users/<username>/` | hardcore and softcore points, global rank per mode, games played, achievements unlocked per mode |
| `/api/users/<username>/recent/` | the last 20 unlocks, newest first |
| `/api/games/<id>/leaderboard/<lb_id>/` | the top 100 entries: rank, raw score and the leaderboard's `Format` |
| `/api/games/<id>/players/` | the 100 most recent players: first and last played, playtime, achievements unlocked per mode |

Only published achievements count. A hardcore unlock also counts as a softcore one, as in the point
totals. Ranks are competition ranks (ties share a rank); a user with no points in a mode has no rank
in it. Inactive accounts (deactivated users and system accounts such as `ra-import`) hold no rank
and are left out of leaderboards and player lists.

## Anti-cheat

The `anticheat` app flags requests for manual review in the admin (**Anti-cheat → Suspicious
activities**, bulk actions *mark legitimate* / *mark cheating*, which record the reviewer and the
time). Flagging never blocks or bans a user. Thresholds are constants in
`apps/anticheat/detection.py`.

| Kind | Flagged when | Request outcome |
| --- | --- | --- |
| `invalid_signature` | `awardachievement` or `submitlbentry` arrives without `v`, or with a `v` that does not match (once per user, request type and minute) | rejected (`missing_parameter` / `invalid_parameter`) |
| `rate_limited` | a user sends more than 30 `awardachievement` in a minute (once per window) | HTTP 429, which rc_client retries with backoff, so the unlock is delayed, not lost |
| `unlock_burst` | 10 new unlocks of one game, in either mode, arrive within a minute (once per burst) | accepted |
| `early_unlock` | a new unlock arrives less than 30 s after the session's `startsession` | accepted |

Both timing checks go by when the request arrives, not by the unlock time `o` claims: `v` is an
unkeyed MD5 of public values, so anyone can sign any `o`. Unlocks out of an unlikely order are not
detected.

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

## Editing sets from RAIntegration

RAIntegration writes sets through `POST /dorequest.php` (the badge upload goes to
`POST /doupload.php`). Every action but `codenotes2`, `badgeiter` and `latestclient` needs `u` + `t`.
A refusal answers `access_denied` with `Status` 403, as RetroAchievements does.

| Action | Allowed to | Behaviour |
| --- | --- | --- |
| `codenotes2` | anyone | the game's notes, `Address` as `0x%06x` |
| `submitcodenote`, `submitcodenotes` | any user adds; only the note's author or staff changes or deletes it | an empty note deletes; the last writer becomes the note's author; `submitcodenotes` lists the refused addresses in `AccessDeniedAddresses` |
| `uploadachievement` | any user creates; only the author or staff changes | a new achievement is always a **draft**, whatever `f` says, and `f` never changes a status: publish in the admin. `b` must be an uploaded badge or `00000`; `x` is the type |
| `uploadleaderboard` | staff creates; only the author or staff changes | stored as `STA:…::CAN:…::SUB:…::VAL:…`; format aliases (`TIME`, `POINTS`, …) are stored by their canonical name. Leaderboards have no draft state: a new one is live for every player, hence staff only |
| `submitrichpresence` | staff | replaces the game's rich presence script |
| `submitgametitle` | staff | links the hash to game `g`, or to the game titled `i` on console `c`, created if there is none |
| `badgeiter` | anyone | the first badge number and the next one |
| `uploadbadgeimage` | any user | multipart `u`, `t`, `file` (PNG, JPEG or GIF, at most 1 MiB and 1024 px a side); answers the new badge's name as `BadgeIter` |
| `achievementwondata` | any user | the achievement's latest unlockers; the friends-only page (`f=1`) is empty |
| `latestclient` | anyone | answers `not_found`, which lets every emulator through |

`uploadachievement` and `uploadleaderboard` carry a checksum `h`, the lowercase hex MD5 rcheevos
computes (`u` is the username as sent; `a`/`i` is `0` for a new one), checked by
`achievement_upload_checksum` and `leaderboard_upload_checksum` in `apps/api/editor.py`:

| Request | `h` |
| --- | --- |
| `uploadachievement` | `md5(u + "SECRET" + a + "SEC" + m + z + "RE2" + z × 3)` |
| `uploadleaderboard` | `md5(u + "SECRET" + i + "SEC" + s + b + c + l + "RE2" + f)` |

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
