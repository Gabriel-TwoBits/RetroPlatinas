#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
vendor="${repo_root}/vendor/rcheevos"
binary="${repo_root}/.cache/check-mem-addr"

if [[ ! -x "${binary}" ]]; then
    mkdir -p "$(dirname "${binary}")"
    cc -O0 -o "${binary}" \
        "${repo_root}/scripts/check-mem-addr.c" \
        "${vendor}"/src/rcheevos/*.c \
        "${vendor}"/src/rhash/md5.c \
        "${vendor}"/src/rc_util.c \
        "${vendor}"/src/rc_compat.c \
        "${vendor}"/src/rc_version.c \
        -I"${vendor}/include" -I"${vendor}/src" -I"${vendor}/src/rcheevos" \
        -lm
fi

exec "${binary}" "$@"
