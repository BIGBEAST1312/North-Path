#!/usr/bin/env python3
"""Flask web app. One page: describe your situation, get a ranked shortlist."""
from __future__ import annotations

import os

from flask import Flask, render_template, request

from costmodel import (
    cheapest_tuition,
    calibrate,
    housing_line,
    caveats,
    explain,
    DEFAULT_DEGREE,
    load_all,
    load_all_programs,
    load_degrees,
    load_outlook,
    load_programs,
    load_responses,
    load_weights,
    money,
    money_range,
    rank,
    top_factors,
    Student,
)
from costmodel import assistant
from costmodel import ratelimit

app = Flask(__name__)


def visitor() -> str:
    """Who is asking, for the assistant's call budget.

    Render sits behind a proxy, so remote_addr is the proxy. The left-most entry
    of X-Forwarded-For is the client. It is trivially spoofable — this is a
    courtesy budget protecting a free-tier key, not a security control, and the
    ranking it guards costs nothing to serve anyway.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    return (forwarded.split(",")[0].strip() or request.remote_addr or "unknown")

CITIES, _, EXPIRY = load_all()
DEGREES = load_degrees()
OUTLOOK = load_outlook()


def degree_groups():
    """Degrees grouped for the dropdown, in file order."""
    groups = {}
    for d in DEGREES.values():
        groups.setdefault(d.group, []).append(d)
    return groups


def data_health() -> dict:
    """What the page must disclose about its own data before showing any number."""
    unverified = 0
    total = 0
    for city in CITIES.values():
        for rng in city.costs.values():
            total += 1
            if not rng.verified:
                unverified += 1
    for prog in load_all_programs():
        for fig in (prog.admission_cutoff_percent, prog.tuition_intl_annual, prog.tuition_domestic_annual):
            total += 1
            if not fig.verified:
                unverified += 1

    cal = calibrate(CITIES, load_responses())
    return {
        "unverified": unverified,
        "total": total,
        "calibrated": bool(cal["n_observations"]),
        "coverage": cal["coverage"],
        "n_reports": cal["n_reports"],
    }


@app.route("/", methods=["GET", "POST"])
def index():
    weights = load_weights()
    health = data_health()
    results = None
    form = {
        "average": request.form.get("average", "78"),
        "budget": request.form.get("budget", "30000"),
        "status": request.form.get("status", "international"),
        "housing_type": request.form.get("housing_type", "private_room"),
        "proximity": request.form.get("proximity", "near"),
        "months": request.form.get("months", "12"),
        "meals_out": request.form.get("meals_out", "2"),
        "coop": request.form.get("coop") == "on",
        "crime_matters": request.form.get("crime_matters") == "on",
        "city_size": request.form.get("city_size", ""),
        "degree": request.form.get("degree", DEFAULT_DEGREE),
        "query": request.form.get("query", ""),
    }

    # Plain-English box: the model only fills in form fields, and only ones this
    # app validates. Every number below still comes from data/.
    ai_note = None
    asked_assistant = (request.method == "POST" and form["query"].strip()
                       and assistant.enabled())
    within_budget = ratelimit.allow(visitor()) if asked_assistant else False
    if asked_assistant and not within_budget:
        ai_note = ("The assistant has been used a lot in the last hour, so your typed answers "
                   "were used as they are. The ranking below is unaffected — it never uses "
                   "the assistant.")
    if asked_assistant and within_budget:
        try:
            parsed = assistant.parse_query(form["query"], DEGREES)
        except assistant.GeminiError as exc:
            parsed = {}
            # A busy model is a queue, not a fault: don't send the visitor to a
            # diagnostic script over something that fixes itself in ten seconds.
            transient = "busy" in str(exc).lower()
            ai_note = (
                "The assistant is busy right now, so your typed answers were used as they are. "
                "The ranking below is unaffected — it never uses the assistant."
                if transient else
                f"Assistant unavailable ({exc}). Your typed answers were used as they are. "
                "Run `python check_gemini.py` to diagnose."
            )
        if parsed:
            for key, value in parsed.items():
                if key in ("coop", "crime_matters"):
                    form[key] = bool(value)
                elif key in ("average", "budget", "meals_out"):
                    form[key] = f"{value:g}"
                else:
                    form[key] = value
            ai_note = "Read from your sentence: " + ", ".join(
                f"{k.replace('_', ' ')} {v}" for k, v in sorted(parsed.items()))
        elif ai_note is None:
            ai_note = "Nothing usable came out of that sentence, so the fields below were left alone."
    if form["degree"] not in DEGREES:
        form["degree"] = DEFAULT_DEGREE
    degree = DEGREES[form["degree"]]
    outlook = OUTLOOK.get(degree.outlook) if degree.outlook else None
    error = None
    no_match = None
    summary = None

    if request.method == "POST":
        try:
            student = Student(
                average_percent=float(form["average"]),
                tuition_budget=float(form["budget"]),
                status=form["status"],
                housing_type=form["housing_type"],
                proximity=form["proximity"],
                months_per_year=int(form["months"]),
                meals_out_per_week=float(form["meals_out"] or 0),
                wants_coop=form["coop"],
                preferred_city_size=form["city_size"] or None,
                crime_matters=form["crime_matters"],
            )
            if student.tuition_budget <= 0:
                raise ValueError("Enter a tuition budget above $0.")
            programs = load_programs(degree.id)
            scored = rank(
                student, programs, CITIES, weights, EXPIRY, limit=6,
                one_per_university=degree.kind == "pathway",
            )
            results = [
                {
                    "r": r,
                    "why": explain(r),
                    "caveats": caveats(r),
                    "factors": top_factors(r),
                    "housing_line": housing_line(r, student),
                    "total": money_range(r["estimate"].total_low, r["estimate"].total_high),
                    "tuition": money(r["estimate"].tuition.value),
                    "tuition_confirmed": r["estimate"].tuition.verified,
                    "living": money_range(r["estimate"].living_low, r["estimate"].living_high),
                    "monthly": {
                        k: ("included in student fees" if k == "transit" and v.high == 0
                            else money_range(v.low, v.high))
                        for k, v in r["estimate"].monthly.items()
                    },
                }
                for r in scored
            ]
            if results and assistant.enabled() and ratelimit.allow(visitor()):
                try:
                    summary = assistant.summarise(scored)
                except assistant.GeminiError:
                    summary = None
            if not results:
                cheapest = cheapest_tuition(programs, student.status)
                no_match = {
                    "budget": money(student.tuition_budget),
                    "cheapest": money(cheapest) if cheapest is not None else None,
                    "status": student.status,
                }
        except (ValueError, TypeError) as exc:
            error = str(exc)

    return render_template(
        "index.html",
        form=form,
        results=results,
        error=error,
        no_match=no_match,
        weights=weights,
        health=health,
        cities=sorted(CITIES),
        summary=summary,
        ai_note=ai_note,
        ai_enabled=assistant.enabled(),
        degree=degree,
        degree_groups=degree_groups(),
        outlook=outlook,
    )


@app.route("/methodology")
def methodology():
    return render_template("methodology.html", health=data_health(), weights=load_weights(), expiry=EXPIRY)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("DEBUG")))
