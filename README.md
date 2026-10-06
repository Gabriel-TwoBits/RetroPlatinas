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
podman-compose exec web uv lock
# Then: git add uv.lock && git commit

# Add a new dependency
podman-compose exec web uv add package-name
# Then: git add pyproject.toml uv.lock && git commit
```

## Accessing the admin

http://localhost:8000/admin/ → log in with the superuser created above.

## Playing with DuckStation

The official DuckStation build works as is: it sends its achievement requests to the host set in
`[Cheevos] Host` of its `settings.ini`. No fork or patched binary is needed.

1. Seed the game, so the server recognises the disc (idempotent):

   ```bash
   podman-compose exec web python manage.py seed_crash1_level_achievements
   podman-compose exec web python manage.py seed_crash1_collectible_achievements
   podman-compose exec web python manage.py seed_crash1_advanced_achievements
   podman-compose exec web python manage.py seed_crash1_rich_presence
   ```

   They register *Crash Bandicoot (USA)* (SCUS-94900, rcheevos hash
   `35386fd0891e594c9b6d8a4a5baa0027`) with its achievements and its rich presence script. Any
   other disc is an unknown game.
2. With DuckStation closed, edit the `[Cheevos]` section of its `settings.ini` (on Linux,
   `~/.local/share/duckstation/settings.ini`):

   ```ini
   [Cheevos]
   Enabled = true
   Host = http://localhost:8000
   ```

3. Register on the site (http://localhost:8000/register/), then log in from DuckStation:
   *Settings → Achievements → Login*. DuckStation encrypts the stored token with a per-machine key,
   so a token cannot be pasted into `settings.ini`: log in through the GUI on every machine.

Other keys of the same section:

| Key | Setting | When |
| --- | --- | --- |
| `UnofficialTestMode = true` | Test Unofficial Achievements | Only for an author testing their own `draft` achievements, which are served to that author alone, as unofficial, and never awarded. Published (`community`, `verified`) achievements load without it. |
| `ChallengeMode = true` | Hardcore mode | Save states are blocked; turning it on requires a reset. Each unlock reports its mode, and a hardcore unlock counts for both the hardcore and the softcore totals. |

## Running in background

```bash
podman-compose --in-pod=false up -d   # start in background
podman-compose logs -f web    # follow Django server logs
podman-compose down           # stop all (data persists in volumes)
podman-compose down -v        # stop AND delete volumes (full reset)
```

## First time: generate uv.lock

The `uv.lock` lockfile should be committed to the repository for reproducible builds.
After the first `podman-compose --in-pod=false up --build`, generate it with:

```bash
podman-compose exec web uv lock
git add uv.lock
git commit -m "chore: add initial uv.lock"
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
