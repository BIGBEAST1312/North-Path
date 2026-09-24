#!/usr/bin/env python3
"""Fail loudly if the data files are malformed or undocumented.

    python validate_data.py            summary by file and field
    python validate_data.py --all      every outstanding field
    python validate_data.py --only usask   only lines containing "usask"
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter

from costmodel import audit, load_all, load_degrees, load_all_programs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only", help="filter lines containing this text")
    args = ap.parse_args()

    try:
        cities, _, expiry = load_all()
        degrees = load_degrees()
        programs = load_all_programs()
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED to load data: {exc}")
        return 2

    print(f"Loaded {len(cities)} cities, {len(degrees)} degree options, {len(programs)} university x degree offerings.")
    problems = audit()
    if args.only:
        problems = [p for p in problems if args.only in p]

    if not problems:
        print("Everything is sourced and dated.")
        return 0

    buckets = Counter()
    for p in problems:
        head = p.split(":")[0]
        file_ = head.split(".")[0]
        field = head.rsplit(".", 1)[-1]
        buckets[(file_, field)] += 1

    print(f"\n{len(problems)} field(s) outstanding:\n")
    for (file_, field), n in sorted(buckets.items()):
        print(f"  {file_:<10} {field:<28} {n}")

    if args.all or args.only:
        print()
        for p in problems:
            print(f"  - {p}")
    else:
        print("\nRun with --all for every line, or --only usask to focus on one university.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
