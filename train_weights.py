#!/usr/bin/env python3
"""Fit the ranker weights instead of choosing them.

Right now weights.json is hand-set, which is the honest label for "I picked
numbers that felt right". This script replaces them with weights fitted by
logistic regression to labelled data, and records how many labels it used.

The labels you need, in data/labels.csv:

    average,budget,status,housing_type,proximity,coop,city_size,program_id,chose
    78,25000,international,private_room,near,1,small,usask-cs,1
    78,25000,international,private_room,near,1,small,utoronto-cs,0

One row per (student, program) pair the student actually considered. `chose` is
1 if they applied to or picked it, 0 if they saw it and passed. Fifty rows is
enough to beat hand-tuned weights; five is not.

Where the labels come from, cheapest first:
  1. Your own application shortlist and those of friends who applied recently.
  2. The survey you send for calibration — add "which did you apply to, and what
     else did you seriously consider?"
  3. Later, the tool's own logs, once anyone is using it.

Run:  python train_weights.py --labels data/labels.csv
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date
from pathlib import Path

import numpy as np

from costmodel import load_all, load_all_programs, Student
from costmodel.match import admission_fit, cost_fit, degree_fit, preference_fit
from costmodel.estimate import estimate_cost

ROOT = Path(__file__).resolve().parent
FEATURES = ["degree_fit", "admission_fit", "cost_fit", "preference_fit"]


def build_matrix(rows, cities, programs, expiry):
    by_id = {p.id: p for p in programs}
    X, y = [], []
    skipped = 0
    for row in rows:
        prog = by_id.get(row["program_id"])
        if prog is None:
            skipped += 1
            continue
        student = Student(
            average_percent=float(row["average"]),
            tuition_budget=float(row["budget"]),
            status=row.get("status") or "international",
            housing_type=row.get("housing_type") or "private_room",
            proximity=row.get("proximity") or "near",
            wants_coop=str(row.get("coop", "0")).strip() in ("1", "true", "True", "yes"),
            preferred_city_size=(row.get("city_size") or None) or None,
        )
        city = cities[prog.city]
        est = estimate_cost(prog, city, student, expiry)
        X.append([
            degree_fit(prog)[0],
            admission_fit(student, prog),
            cost_fit(est, student.tuition_budget),
            preference_fit(student, prog, city),
        ])
        y.append(int(row["chose"]))
    return np.array(X, dtype=float), np.array(y, dtype=float), skipped


def fit(X, y, epochs=4000, lr=0.5, l2=1e-3, seed=0):
    """Plain gradient descent on logistic loss. No sklearn dependency, and every
    line is something you can explain in an interview."""
    rng = np.random.default_rng(seed)
    w = rng.normal(0, 0.01, X.shape[1])
    b = 0.0
    n = len(y)
    for _ in range(epochs):
        z = X @ w + b
        p = 1 / (1 + np.exp(-z))
        grad_w = X.T @ (p - y) / n + l2 * w
        grad_b = float(np.sum(p - y) / n)
        w -= lr * grad_w
        b -= lr * grad_b
    return w, b


def evaluate(X, y, w, b):
    p = 1 / (1 + np.exp(-(X @ w + b)))
    pred = (p >= 0.5).astype(float)
    acc = float((pred == y).mean())
    # Accuracy alone is misleading when most rows are 0, so report the base rate too.
    base = float(max(y.mean(), 1 - y.mean()))
    return {"accuracy": acc, "majority_baseline": base, "n": int(len(y))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", default="data/labels.csv")
    ap.add_argument("--min-labels", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true", help="fit and report, do not write weights.json")
    args = ap.parse_args()

    path = ROOT / args.labels
    if not path.exists():
        print(f"No label file at {path}.")
        print("Until it exists the ranker uses hand-set weights, and the UI says so.\n")
        print("Create it with these columns, one row per program a student considered:\n")
        print("  average,budget,status,housing_type,proximity,coop,city_size,program_id,chose")
        print("  78,25000,international,private_room,near,1,small,usask-cs,1")
        print("  78,25000,international,private_room,near,1,small,utoronto-cs,0\n")
        print("`chose` is 1 if they applied to or picked it, 0 if they saw it and passed.")
        print("Cheapest sources: your own shortlist and recent applicants you know, then")
        print("the follow-up question in SURVEY.md. Thirty rows is the minimum worth fitting.")
        return 1

    rows = list(csv.DictReader(path.open()))
    cities, _, expiry = load_all()
    programs = load_all_programs()
    X, y, skipped = build_matrix(rows, cities, programs, expiry)

    if len(y) < args.min_labels:
        print(f"Only {len(y)} usable labels (need {args.min_labels}).")
        print("Fitting on this little data would produce weights that look learned and are not.")
        return 1

    w, b = fit(X, y)
    metrics = evaluate(X, y, w, b)

    # Normalise to keep the weighted score inside [0, 1] like the hand-set version.
    scale = float(np.sum(np.abs(w))) or 1.0
    normalised = {name: float(val / scale) for name, val in zip(FEATURES, w)}

    print("\nFitted weights:")
    for name, val in normalised.items():
        print(f"  {name:<16} {val:+.3f}")
    print(f"\n  accuracy {metrics['accuracy']:.0%}  (majority baseline {metrics['majority_baseline']:.0%}, n={metrics['n']})")
    if skipped:
        print(f"  {skipped} row(s) skipped: unknown program_id")
    if metrics["accuracy"] <= metrics["majority_baseline"]:
        print("\n  The fitted model does not beat guessing the majority class.")
        print("  Report that honestly rather than shipping it as an improvement.")

    if args.dry_run:
        print("\n(dry run, weights.json untouched)")
        return 0

    out = {
        "_note": "Fitted by train_weights.py. Do not hand-edit; rerun the script.",
        "source": "learned",
        "fitted_on": date.today().isoformat(),
        "n_labels": metrics["n"],
        "metrics": metrics,
        "weights": normalised,
        "bias": float(b / scale),
    }
    (ROOT / "weights.json").write_text(json.dumps(out, indent=2) + "\n")
    print("\nweights.json updated (source: learned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
