#!/usr/bin/env python3
"""Command line entry point.

Examples:
    python cli.py degrees
    python cli.py rank --degree nursing --average 85 --budget 50000 --coop \
        --housing-type private_room --proximity near
    python cli.py cost --city Saskatoon --housing-type studio --proximity far
    python cli.py calibrate
    python cli.py audit
"""
from __future__ import annotations

import argparse
import sys

from costmodel import (
    audit,
    cheapest_tuition,
    calibrate,
    caveats,
    estimate_cost,
    explain,
    load_all,
    load_degrees,
    load_responses,
    load_weights,
    money,
    money_range,
    rank,
    report_markdown,
    Student,
)
from costmodel.schema import HOUSING_LABELS, HOUSING_TYPES, PROXIMITIES

CONFIDENCE_NOTE = {
    "unverified": "UNVERIFIED — built on placeholder data",
    "stale": "STALE — some figures are past their check-by date",
    "low": "wide range, low confidence",
    "moderate": "moderate confidence",
    "high": "narrow range, higher confidence",
}


def cmd_degrees(args) -> int:
    degrees = load_degrees()
    group = None
    for d in degrees.values():
        if d.group != group:
            group = d.group
            print(f"\n{group}")
        print(f"  {d.id:<16} {d.name}")
    print()
    return 0


def cmd_rank(args) -> int:
    degrees = load_degrees()
    if args.degree not in degrees:
        print(f"Unknown degree {args.degree!r}. Run `python cli.py degrees` for the list.")
        return 1
    degree = degrees[args.degree]
    cities, programs, expiry = load_all(degree.id)
    student = Student(
        average_percent=args.average,
        tuition_budget=args.budget,
        status="domestic" if args.domestic else "international",
        housing_type=args.housing_type,
        proximity=args.proximity,
        months_per_year=args.months,
        wants_coop=args.coop,
        preferred_city_size=args.city_size,
        crime_matters=args.crime_matters,
    )
    weights = load_weights()
    results = rank(student, programs, cities, weights, expiry, limit=args.limit,
                   one_per_university=degree.kind == "pathway")

    print(f"\n{degree.name}")
    if degree.notice:
        print(f"\n  NOTE: {degree.notice}\n")
    print(f"Ranking {len(programs)} programs for a {student.status} student, "
          f"{student.average_percent:g}% average, tuition budget {money(student.tuition_budget)}/year")
    print(f"Weights: {weights['source']}"
          + ("" if weights["source"] == "learned" else "  <- these are opinions, not findings"))
    print()

    if not results:
        cheapest = cheapest_tuition(programs, student.status)
        print("No universities available for the selected tuition fee budget.")
        if cheapest is not None:
            print(f"The lowest {student.status} tuition for {degree.name} is {money(cheapest)} a year.")
        print()
        return 0

    for i, r in enumerate(results, 1):
        prog = r["program"]
        est = r["estimate"]
        label = {"safety": "LIKELY ADMIT", "match": "MATCH", "reach": "REACH"}[r["label"]]
        print(f"{i}. {prog.university} — {prog.program}  [{label}]")
        print(f"   {prog.city}  ·  score {r['score']:.2f}  ·  {CONFIDENCE_NOTE[r['confidence']]}")
        print(f"   Tuition/year: {money(est.tuition.value)}   Living/year: {money_range(est.living_low, est.living_high)}   Together: {money_range(est.total_low, est.total_high)}")
        print(f"   Why: {explain(r)}")
        for c in caveats(r):
            print(f"   ! {c}")
        print()
    return 0


def cmd_cost(args) -> int:
    cities, programs, expiry = load_all(args.degree)
    city = cities.get(args.city)
    if city is None:
        print(f"No cost data for {args.city!r}. Known cities: {', '.join(sorted(cities))}")
        return 1

    student = Student(
        average_percent=80,
        tuition_budget=0,
        status="domestic" if args.domestic else "international",
        housing_type=args.housing_type,
        proximity=args.proximity,
        months_per_year=args.months,
    )

    where = "near campus" if args.proximity == "near" else "further from campus"
    print(f"\n{city.city}, {city.province} — monthly ranges ({HOUSING_LABELS[args.housing_type]}, {where})")
    if city.safety:
        csi = city.safety.crime_severity_index
        flag = "" if csi.verified else "  [unverified]"
        print(f"  crime severity index {csi.value:g} — {city.safety.descriptor()}{flag}")
    for name, rng in city.monthly_ranges(args.housing_type, args.proximity).items():
        flag = "" if rng.verified else "   [unverified]"
        n = f" n={rng.n}" if rng.n else ""
        print(f"  {name:<16} {money_range(rng.low, rng.high)}{n}{flag}")

    for prog in [p for p in programs if p.city == city.city]:
        est = estimate_cost(prog, city, student, expiry)
        print(f"\n  {prog.university} — {prog.program}")
        print(f"    tuition   {money(est.tuition.value)}")
        print(f"    living    {money_range(est.living_low, est.living_high)} over {args.months} months")
        print(f"    TOTAL     {money_range(est.total_low, est.total_high)}  ({est.confidence})")
    print()
    return 0


def cmd_calibrate(args) -> int:
    cities, _, _ = load_all()
    responses = load_responses()
    result = calibrate(cities, responses)
    text = report_markdown(result)
    print("\n" + text + "\n")
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text + "\n")
        print(f"written to {args.out}")
    return 0


def cmd_audit(args) -> int:
    problems = audit()
    if not problems:
        print("All figures carry a source and a date. Nice.")
        return 0
    print(f"\n{len(problems)} field(s) need attention:\n")
    for p in problems:
        print(f"  - {p}")
    print("\nReplace each placeholder with a real figure, set source_url and as_of, "
          "then flip verified to true.\n")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="North Path — cost-first university selector for Canada")
    sub = parser.add_subparsers(dest="command", required=True)

    common_housing = dict(choices=list(HOUSING_TYPES), default="private_room")
    common_proximity = dict(choices=list(PROXIMITIES), default="near")

    p_rank = sub.add_parser("rank", help="rank programs for a student")
    p_rank.add_argument("--average", type=float, required=True, help="admission average, percent")
    p_rank.add_argument("--budget", type=float, required=True, help="tuition budget per year in CAD (tuition only)")
    p_rank.add_argument("--domestic", action="store_true", help="domestic tuition instead of international")
    p_rank.add_argument("--housing-type", **common_housing)
    p_rank.add_argument("--proximity", **common_proximity,
                        help="near or far from campus: changes rent and transit")
    p_rank.add_argument("--months", type=int, default=12)
    p_rank.add_argument("--coop", action="store_true", help="co-op is required")
    p_rank.add_argument("--city-size", choices=["small", "medium", "large"])
    p_rank.add_argument("--crime-matters", action="store_true",
                        help="weigh city crime figures in the ranking")
    p_rank.add_argument("--degree", default="cs", help="degree id, see `python cli.py degrees`")
    p_rank.add_argument("--limit", type=int, default=5)
    p_rank.set_defaults(func=cmd_rank)

    p_deg = sub.add_parser("degrees", help="list the 41 degree options")
    p_deg.set_defaults(func=cmd_degrees)

    p_cost = sub.add_parser("cost", help="show the cost breakdown for one city")
    p_cost.add_argument("--city", required=True)
    p_cost.add_argument("--housing-type", **common_housing)
    p_cost.add_argument("--proximity", **common_proximity)
    p_cost.add_argument("--months", type=int, default=12)
    p_cost.add_argument("--domestic", action="store_true")
    p_cost.add_argument("--degree", default="cs")
    p_cost.set_defaults(func=cmd_cost)

    p_cal = sub.add_parser("calibrate", help="compare predictions against real student reports")
    p_cal.add_argument("--out", help="write the report to this file")
    p_cal.set_defaults(func=cmd_calibrate)

    p_audit = sub.add_parser("audit", help="list every unverified figure")
    p_audit.set_defaults(func=cmd_audit)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
