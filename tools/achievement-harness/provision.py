"""Cache layout and everything the harness needs from outside the repo: disc, BIOS, cores, shim.

Nothing here is committed: cores, the compiled shim, states, traces and screenshots all live under
`.cache/achievement-harness/` (gitignored). The disc and the BIOS are never downloaded; they come
from the environment (`CRASH1_CUE`, `CRASH1_BIOS_DIR`).
"""

import os
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_DIR.parents[1]
CACHE_DIR = REPO_ROOT / ".cache" / "achievement-harness"
CORES_DIR = CACHE_DIR / "cores"
SYSTEM_DIR = CACHE_DIR / "system"
STATES_DIR = CACHE_DIR / "states"
TRACES_DIR = CACHE_DIR / "traces"
SHOTS_DIR = CACHE_DIR / "shots"
LIBRARY = CACHE_DIR / "build" / "libharness.so"
PLANS_DIR = HARNESS_DIR / "plans"

BUILD_SCRIPT = HARNESS_DIR / "build.sh"
SHIM_SOURCE = HARNESS_DIR / "src" / "harness.c"
RCHEEVOS_DIR = REPO_ROOT / "vendor" / "rcheevos"
RCHEEVOS_COMMIT_FILE = RCHEEVOS_DIR / "UPSTREAM-COMMIT"

DISC_ENV = "CRASH1_CUE"
BIOS_DIR_ENV = "CRASH1_BIOS_DIR"
CORE_URL = "https://buildbot.libretro.com/nightly/linux/x86_64/latest/{core}_libretro.so.zip"
DOWNLOAD_TIMEOUT_SECONDS = 120

# NTSC-U BIOS dumps swanstation accepts, most common first; the PS2 scph39001 image also boots it.
NTSC_U_BIOS_IMAGES = (
    "scph5501.bin",
    "scph1001.bin",
    "scph7001.bin",
    "scph101.bin",
    "scph39001.bin",
)


class MissingInput(RuntimeError):
    """A file the harness must not download (the disc, a BIOS) is not configured."""


def disc():
    """The Crash Bandicoot (USA) cue sheet named by CRASH1_CUE."""
    value = os.environ.get(DISC_ENV, "")
    if not value:
        raise MissingInput(f"{DISC_ENV} is not set: point it at the Crash Bandicoot (USA) .cue")
    path = Path(value)
    if not path.is_file():
        raise MissingInput(f"{DISC_ENV}={value} is not a readable file")
    return path


def bios_image(system_dir):
    """Links an NTSC-U BIOS from CRASH1_BIOS_DIR into `system_dir` and returns its file name."""
    value = os.environ.get(BIOS_DIR_ENV, "")
    if not value:
        raise MissingInput(f"{BIOS_DIR_ENV} is not set: swanstation needs a real BIOS")
    bios_dir = Path(value)
    if not bios_dir.is_dir():
        raise MissingInput(f"{BIOS_DIR_ENV}={value} is not a directory")
    available = {path.name.lower(): path for path in bios_dir.glob("*") if path.is_file()}
    for name in NTSC_U_BIOS_IMAGES:
        if name in available:
            link = system_dir / name
            if not (link.is_symlink() and link.resolve() == available[name].resolve()):
                link.unlink(missing_ok=True)
                link.symlink_to(available[name])
            return name
    raise MissingInput(f"{bios_dir} holds none of {', '.join(NTSC_U_BIOS_IMAGES)}")


def core(name):
    """Path to `<name>_libretro.so`, downloaded from the libretro buildbot on first use."""
    path = CORES_DIR / f"{name}_libretro.so"
    if path.is_file():
        return path
    CORES_DIR.mkdir(parents=True, exist_ok=True)
    url = CORE_URL.format(core=name)
    partial = path.with_name(f"{path.name}.{os.getpid()}")
    with (
        urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response,
        tempfile.TemporaryFile() as archive,
    ):
        shutil.copyfileobj(response, archive)
        archive.seek(0)
        with zipfile.ZipFile(archive) as bundle:
            if path.name not in bundle.namelist():
                raise RuntimeError(f"{url} does not contain {path.name}")
            with bundle.open(path.name) as source, partial.open("wb") as target:
                shutil.copyfileobj(source, target)
    partial.replace(path)
    return path


def library():
    """Path to the compiled shim, rebuilt by build.sh when a source is newer than it."""
    sources = [SHIM_SOURCE, BUILD_SCRIPT, *RCHEEVOS_DIR.rglob("*")]
    newest_source = max(path.stat().st_mtime for path in sources if path.is_file())
    if not LIBRARY.is_file() or LIBRARY.stat().st_mtime < newest_source:
        subprocess.run(["bash", str(BUILD_SCRIPT)], check=True, stdout=subprocess.DEVNULL)
    return LIBRARY


def rcheevos_commit():
    """The upstream rcheevos commit the vendored runtime was copied from."""
    return RCHEEVOS_COMMIT_FILE.read_text().strip()
