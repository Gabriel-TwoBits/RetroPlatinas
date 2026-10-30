#!/usr/bin/env bash
# Builds the pcsx_rearmed libretro core from a pinned upstream commit into the cache and prints its
# path. Every committed plan was searched on this build ("r26 ff81ed1"): a plan replays frame-exactly
# only on the core it was searched on, and the libretro buildbot serves only each core's latest
# nightly.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${here}/../.." && pwd)"
cores_dir="${repo_root}/.cache/achievement-harness/cores"

commit="ff81ed17a15241d2f3730cdd7585b38e172532ca"
short_commit="${commit:0:7}"
tarball_sha256="23e0006435e66503e1b862daaf8a47cb6bee120f4ca82482c08ec129668a35c5"
tarball_url="https://codeload.github.com/libretro/pcsx_rearmed/tar.gz/${commit}"
build_jobs=4
out="${cores_dir}/pcsx_rearmed-${short_commit}_libretro.so"

if [[ -f "${out}" ]]; then
    echo "${out}"
    exit 0
fi

mkdir -p "${cores_dir}"
work="$(mktemp -d)"
trap 'rm -rf "${work}"' EXIT

curl -sSfL -o "${work}/source.tar.gz" "${tarball_url}"
echo "${tarball_sha256}  ${work}/source.tar.gz" | sha256sum --check --quiet
tar -xzf "${work}/source.tar.gz" -C "${work}"
# The tarball has no .git: the version the core reports ("r26 <commit>") is passed in.
make -C "${work}/pcsx_rearmed-${commit}" -f Makefile.libretro -j"${build_jobs}" \
    GIT_VERSION="\" ${short_commit}\"" > "${work}/build.log" 2>&1 || {
    tail -n 40 "${work}/build.log" >&2
    exit 1
}
# A unique name in the cores directory: containers have their own PID namespaces, so `$$` may
# collide between two first uses at once.
partial="$(mktemp -p "${cores_dir}" "pcsx_rearmed-${short_commit}.XXXXXX")"
cp "${work}/pcsx_rearmed-${commit}/pcsx_rearmed_libretro.so" "${partial}"
mv "${partial}" "${out}"
echo "${out}"
