FROM python:3.12-slim

# Copy uv binary from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# The venv lives outside /app so the dev bind mount does not hide it.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    gettext \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Tailwind standalone CLI (no Node). CSS is compiled at startup in entrypoint.sh.
ARG TAILWIND_VERSION=v3.4.17
RUN curl -fsSL -o /usr/local/bin/tailwindcss \
    "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-x64" \
    && chmod +x /usr/local/bin/tailwindcss

# Non-root user with UID/GID 1000, the host developer's UID under `userns_mode: keep-id`.
RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid 1000 --create-home --home-dir /home/app app

RUN mkdir /app && chown app:app /app

WORKDIR /app

# Dependencies get their own layer so source edits keep the build cache. `--locked`
# installs exactly what uv.lock pins and fails the build if the lock is stale.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked && \
    chown -R app:app /opt/venv

COPY --chown=app:app . .

USER app

EXPOSE 8000

ENTRYPOINT ["sh", "/app/entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
