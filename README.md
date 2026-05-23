# RetroCheevos — Server

Alternative platform to RetroAchievements.org with full protocol compatibility (rcheevos).

## Prerequisites

- **Podman** 4+ (`podman --version`)
- **podman-compose** — the native `podman compose` subcommand requires an external docker-compose provider that is usually not installed. Install via pip:

```bash
pip install --user podman-compose
```

## Initial setup

```bash
# 1. Clone the repository
git clone ssh://git@codeberg.org/Gabriel-TwoBits/retrocheevos.git
cd retrocheevos

# 2. Copy environment variables
cp .env.example .env
# Edit .env if you need different passwords in dev

# 3. Start services (builds the image on first run)
podman-compose up --build
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

## Running in background

```bash
podman-compose up -d          # start in background
podman-compose logs -f web    # follow Django server logs
podman-compose down           # stop all (data persists in volumes)
podman-compose down -v        # stop AND delete volumes (full reset)
```

## First time: generate uv.lock

The `uv.lock` lockfile should be committed to the repository for reproducible builds.
After the first `podman-compose up --build`, generate it with:

```bash
podman-compose exec web uv lock
git add uv.lock
git commit -m "chore: add initial uv.lock"
```

## Troubleshooting

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
