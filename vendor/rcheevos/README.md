# rcheevos (vendored parser)

> **Source:** <https://github.com/RetroAchievements/rcheevos> — commit in `UPSTREAM-COMMIT`.
> **Licence:** MIT (see `LICENSE`). © 2018 RetroAchievements.org.

Only the condition parser is vendored — `src/rcheevos/`, `src/rhash/md5.*` and the handful of
support files they include. The rc_client, rapi and rhash networking layers are **not** here; this
is not an emulator client, it exists so `scripts/check-mem-addr.sh` can validate `mem_addr`
strings against the same parser DuckStation runs.

Do not edit these files. To refresh, copy them from upstream and update `UPSTREAM-COMMIT`.
