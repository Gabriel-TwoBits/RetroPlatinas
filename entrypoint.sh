#!/bin/sh
set -e

# Compiled translations (.mo) are build artifacts, not tracked in git.
# Compile them on startup so a fresh checkout serves correct translations.
python manage.py compilemessages

exec "$@"
