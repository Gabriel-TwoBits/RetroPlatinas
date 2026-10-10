#!/usr/bin/env bash
# Builds the harness shim (src/harness.c + the repo's vendored rcheevos) into the cache and prints
# its path. libretro.h is fetched on first use from a pinned libretro-common commit.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${here}/../.." && pwd)"
rc="${repo_root}/vendor/rcheevos"
build_dir="${repo_root}/.cache/achievement-harness/build"
header="${build_dir}/libretro.h"
out="${build_dir}/libharness.so"

libretro_commit="010b54f473125370bf71854907c4bd2633981d60"
libretro_sha256="c928d8f176b4e4bc45ee2a41ef236d25cc19e9bc2abc2e2e4c32cf08d6423801"
libretro_url="https://raw.githubusercontent.com/libretro/libretro-common/${libretro_commit}/include/libretro.h"

mkdir -p "${build_dir}"

if [[ ! -f "${header}" ]]; then
    curl -sSfL -o "${header}.$$" "${libretro_url}"
    echo "${libretro_sha256}  ${header}.$$" | sha256sum --check --quiet
    mv "${header}.$$" "${header}"
fi

cc -O2 -fPIC -shared -o "${out}.$$" \
    "${here}/src/harness.c" \
    "${rc}"/src/rcheevos/*.c \
    "${rc}"/src/rhash/md5.c \
    "${rc}"/src/rc_util.c \
    "${rc}"/src/rc_compat.c \
    "${rc}"/src/rc_version.c \
    -I"${build_dir}" -I"${rc}/include" -I"${rc}/src" -I"${rc}/src/rcheevos" \
    -ldl -lm
mv "${out}.$$" "${out}"
echo "${out}"
