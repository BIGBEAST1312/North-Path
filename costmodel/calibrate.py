"""Calibration: does the model's range actually contain what real students pay?

This is the part that makes the project defensible. Anyone can publish a cost
estimate; the question an interviewer (or a student) should ask is "how do you
know it's right", and the only honest answer is a measured one.

Two metrics, both per category and overall:

  coverage   — share of real reports that fall inside the predicted range.
               A well-calibrated range should cover most of them. Coverage near
               100% with very wide ranges is not a win; report width too.
  median error — median absolute difference between the report and the range
               midpoint, in dollars and as a share of the midpoint.

Survey data lives in data/survey_responses.csv, one row per student per month.
"""
from __future__ import annotations

import csv
import statistics
from pathlib import Path
from typing import Dict, List, Optional

from .schema import City, CATEGORIES

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_responses(path: Optional[Path] = None) -> List[dict]:
    path = path or DATA_DIR / "survey_responses.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        rows = []
        for raw in csv.DictReader(fh):
            if not raw.get("city"):
                continue
            row = {
                "city": raw["city"].strip(),
                "housing_type": (raw.get("housing_type") or "private_room").strip(),
                "proximity": (raw.get("proximity") or "near").strip(),
            }
            for cat in CATEGORIES:
                value = (raw.get(cat) or "").strip()
                row[cat] = float(value) if value else None
            eating_out = (raw.get("eating_out") or "").strip()
            row["eating_out"] = float(eating_out) if eating_out else None
            meals = (raw.get("meals_out_per_week") or "").strip()
            row["meals_out_per_week"] = float(meals) if meals else None
            row["as_of"] = (raw.get("as_of") or "").strip() or None
            row["note"] = (raw.get("note") or "").strip() or None
            rows.append(row)
    return rows


def calibrate(cities: Dict[str, City], responses: List[dict]) -> dict:
    per_category: Dict[str, dict] = {c: {"n": 0, "covered": 0, "errors": [], "rel_errors": []} for c in CATEGORIES}
    unknown_cities = set()
    bad_rows = set()

    for row in responses:
        city = cities.get(row["city"])
        if city is None:
            unknown_cities.add(row["city"])
            continue
        try:
            ranges = city.monthly_ranges(
                row.get("housing_type", "private_room"), row.get("proximity", "near"),
                row.get("meals_out_per_week") or 0,
            )
        except (KeyError, ValueError):
            bad_rows.add(f"{row['city']}/{row.get('housing_type')}/{row.get('proximity')}")
            continue
        for cat in CATEGORIES:
            actual = row.get(cat)
            if actual is None:
                continue
            rng = ranges[cat]
            bucket = per_category[cat]
            bucket["n"] += 1
            if rng.contains(actual):
                bucket["covered"] += 1
            err = abs(actual - rng.mid)
            bucket["errors"].append(err)
            bucket["rel_errors"].append(err / max(rng.mid, 1))

    summary = {}
    for cat, bucket in per_category.items():
        if bucket["n"] == 0:
            summary[cat] = {"n": 0}
            continue
        summary[cat] = {
            "n": bucket["n"],
            "coverage": bucket["covered"] / bucket["n"],
            "median_abs_error": statistics.median(bucket["errors"]),
            "median_rel_error": statistics.median(bucket["rel_errors"]),
        }

    total_n = sum(b["n"] for b in per_category.values())
    total_covered = sum(b["covered"] for b in per_category.values())
    all_rel = [e for b in per_category.values() for e in b["rel_errors"]]

    # Eating out is only comparable when the student said how often they eat out.
    eating = [r["eating_out"] for r in responses if r.get("eating_out") is not None]
    return {
        "eating_out_reported": len(eating),
        "eating_out_median": statistics.median(eating) if eating else None,
        "n_reports": len(responses),
        "n_observations": total_n,
        "coverage": (total_covered / total_n) if total_n else None,
        "median_rel_error": statistics.median(all_rel) if all_rel else None,
        "per_category": summary,
        "unknown_cities": sorted(unknown_cities),
        "unusable_rows": sorted(bad_rows),
    }


def report_markdown(result: dict) -> str:
    lines = ["# Calibration report", ""]
    if not result["n_observations"]:
        lines += [
            "No survey responses yet, so the cost ranges in this project are **uncalibrated**.",
            "",
            "Until real numbers land in `data/survey_responses.csv`, every figure the tool",
            "produces is an untested guess and should be labelled as such wherever it is shown.",
            "",
            "Collect at least 5 responses per city before publishing anything.",
        ]
        return "\n".join(lines)

    lines += [
        f"- Reports: **{result['n_reports']}**  (observations: {result['n_observations']})",
        f"- Overall coverage: **{result['coverage']:.0%}** of reported values fell inside the predicted range",
        f"- Median relative error vs range midpoint: **{result['median_rel_error']:.0%}**",
        "",
        "| Category | n | Coverage | Median error | Median error (%) |",
        "| --- | --- | --- | --- | --- |",
    ]
    for cat, stats in result["per_category"].items():
        if not stats.get("n"):
            lines.append(f"| {cat} | 0 | — | — | — |")
            continue
        lines.append(
            f"| {cat} | {stats['n']} | {stats['coverage']:.0%} | "
            f"${stats['median_abs_error']:,.0f} | {stats['median_rel_error']:.0%} |"
        )

    lines += ["", "## How to read this", ""]
    lines += [
        "Coverage below ~70% means the ranges are too narrow or centred wrong — widen them",
        "or re-anchor them. Coverage near 100% with a large median error means the ranges are",
        "so wide they are not saying much. Both are findings worth writing down.",
    ]
    if result.get("eating_out_median") is not None:
        lines += ["", (f"Eating out: median ${result['eating_out_median']:,.0f}/month across "
                       f"{result['eating_out_reported']} reports. Scored above only for the reports that "
                       "also gave a meals-per-week figure; the rest are recorded but not compared.")]
    if result["unknown_cities"]:
        lines += ["", f"Responses for cities with no cost data: {', '.join(result['unknown_cities'])}"]
    return "\n".join(lines)
