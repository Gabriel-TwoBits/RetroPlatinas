#!/bin/sh
set -e

# Compiled translations (.mo) are build artifacts, not tracked in git.
# Compile them on startup so a fresh checkout serves correct translations.
python manage.py compilemessages

# Tailwind CSS is a build artifact too (static/css/output.css), compiled on
# startup from the tracked input.css + tailwind.config.js. Same rationale as .mo.
tailwindcss -i static/css/input.css -o static/css/output.css --minify

# The mem_addr checker the achievement editor runs compiles from vendor/rcheevos on first use;
# checking a trivial trigger here compiles it at startup instead of during a web request.
bash scripts/check-mem-addr.sh '0=1' > /dev/null

exec "$@"
