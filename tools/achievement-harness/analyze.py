"""Summarises a trace CSV: per probe, how often it changed and the values it took.

    python tools/achievement-harness/analyze.py TRACE.csv [PROBE ...]
    python tools/achievement-harness/analyze.py TRACE.csv --timeline PROBE [PROBE ...]

`--timeline` prints one line per frame where any of the probes changed.
"""

import argparse
import csv

MAX_VALUES_SHOWN = 10
NON_PROBE_COLUMNS = ("frame", "input")


def load(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


def summary(rows, probes):
    lines = ["| probe | changes | distinct values (first seen order) |", "| --- | --- | --- |"]
    for probe in probes:
        seen = []
        changes = 0
        previous = None
        for row in rows:
            value = row[probe]
            if value not in seen:
                seen.append(value)
            if previous is not None and value != previous:
                changes += 1
            previous = value
        shown = ", ".join(value or "(null)" for value in seen[:MAX_VALUES_SHOWN])
        hidden = len(seen) - MAX_VALUES_SHOWN
        more = f" (+{hidden} more)" if hidden > 0 else ""
        lines.append(f"| `{probe}` | {changes} | {shown}{more} |")
    return "\n".join(lines)


def timeline(rows, probes):
    lines = []
    previous = None
    for row in rows:
        current = tuple(row[probe] for probe in probes)
        if current != previous:
            values = "  ".join(f"{probe}={value}" for probe, value in zip(probes, current))
            lines.append(f"{row['frame']}  {values}")
        previous = current
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Summarise a harness trace CSV.")
    parser.add_argument("trace")
    parser.add_argument("probes", nargs="*")
    parser.add_argument("--timeline", action="store_true")
    args = parser.parse_args()
    rows = load(args.trace)
    if not rows:
        raise SystemExit(f"{args.trace} has no frames")
    probes = args.probes or [key for key in rows[0] if key not in NON_PROBE_COLUMNS]
    unknown = [probe for probe in probes if probe not in rows[0]]
    if unknown:
        raise SystemExit(f"{args.trace} has no probes {unknown}")
    print(timeline(rows, probes) if args.timeline else summary(rows, probes))
