# rcheevos (vendored parser)

> **Source:** <https://github.com/RetroAchievements/rcheevos> — commit in `UPSTREAM-COMMIT`.
> **Licence:** MIT (see `LICENSE`). © 2018 RetroAchievements.org.

Only the condition parser is vendored — `src/rcheevos/`, `src/rhash/md5.*` and the handful of
support files they include. The rc_client, rapi and rhash networking layers are **not** here; this
is not an emulator client. It has two consumers:

- `scripts/check-mem-addr.sh` validates `mem_addr` strings against the same parser DuckStation runs.
- `scripts/format-score.sh` formats leaderboard scores with `rc_format_value` (`format.c`, sized by
  `RC_CLIENT_LEADERBOARD_DISPLAY_SIZE` from `rc_client.h`); `apps/leaderboards/test_formatting.py`
  compares the Python formatter against it.

Do not edit these files. To refresh, copy them from upstream and update `UPSTREAM-COMMIT`.
