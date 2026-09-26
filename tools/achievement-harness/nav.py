"""Tiny command language to drive the emulator from the shell, e.g. to find menus by screenshot.

    python tools/achievement-harness/nav.py [--core CORE] [--from STATE] "cmd; cmd; ..."

Commands (frames at 60 Hz):
    wait N              run N frames with no input
    hold BTN[+BTN] N    hold the buttons for N frames
    press BTN[+BTN]     hold 4 frames, release 12
    shot NAME           screenshot to .cache/achievement-harness/shots/nav/NAME.png
    save NAME           save a scratch state (never a derivable state's name)
    load NAME           load a derivable state (states.py) or a scratch state
    peek                print the key addresses
Buttons: CROSS SQUARE CIRCLE TRIANGLE START SELECT UP DOWN LEFT RIGHT L1 R1 L2 R2

Scratch states are for exploring only; scenarios and plans start from derivable states.
"""

import argparse

import navigation
import states
from harness import CORE_DEFAULTS, DEFAULT_CORE, Btn, Emu
from probes import summary
from provision import SHOTS_DIR

SCRATCH_DIR_NAME = "scratch"


def buttons(spec):
    return [getattr(Btn, name.upper()) for name in spec.split("+")]


def scratch_path(emu, name):
    return states.build_dir(emu) / SCRATCH_DIR_NAME / f"{name}.state"


def load(emu, name):
    if name in states.RECIPES:
        return states.load(emu, name)
    path = scratch_path(emu, name)
    if not path.is_file():
        raise SystemExit(f"no state {name!r}: derivable states are {sorted(states.RECIPES)}")
    emu.load_state(path)
    return path


def run(emu, script):
    for raw in script.split(";"):
        parts = raw.split()
        if not parts:
            continue
        command, args = parts[0], parts[1:]
        match command:
            case "wait":
                emu.step(int(args[0]))
            case "hold":
                emu.step(int(args[1]), buttons(args[0]))
            case "press":
                emu.step(navigation.PRESS_FRAMES, buttons(args[0]))
                emu.step(navigation.RELEASE_FRAMES)
            case "shot":
                print("shot", emu.screenshot(SHOTS_DIR / "nav" / f"{args[0]}.png"))
            case "save":
                if args[0] in states.RECIPES:
                    raise SystemExit(f"{args[0]} is a derivable state: derive it with states.py")
                print("save", emu.save_state(scratch_path(emu, args[0])))
            case "load":
                print("load", load(emu, args[0]))
            case "peek":
                print(f"frame {emu.frame}: {summary(emu)}")
            case _:
                raise SystemExit(f"unknown command {command!r}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drive the emulator with a command script.")
    parser.add_argument("script", nargs="+")
    parser.add_argument("--core", default=DEFAULT_CORE, choices=sorted(CORE_DEFAULTS))
    parser.add_argument("--from", dest="start", metavar="STATE")
    args = parser.parse_args()
    emu = Emu(core=args.core).load()
    if args.start:
        load(emu, args.start)
    run(emu, " ".join(args.script))
