"""Turn city cost ranges plus tuition into an annual cost estimate.

The arithmetic is deliberately simple and additive so that every dollar in the
output can be traced back to a line in data/cities.json. Nothing here is clever;
the value is in the provenance and the range, not the formula.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from .schema import City, CostEstimate, Program, Range, Student


def estimate_cost(
    program: Program,
    city: City,
    student: Student,
    expiry_months: int = 6,
    today: Optional[date] = None,
) -> CostEstimate:
    monthly = city.monthly_ranges(student.housing_type, student.proximity, student.meals_out_per_week)
    months = student.months_per_year

    # A U-Pass charged in student fees means transit is not a separate monthly cost.
    # The fee itself sits in mandatory student fees, which this model does not carry
    # yet — see the methodology page.
    if program.upass is not None and program.upass.value is True:
        monthly = dict(monthly)
        monthly["transit"] = Range(low=0, high=0, source="U-Pass included in student fees: " + program.upass.source,
                                   as_of=program.upass.as_of, verified=program.upass.verified)

    living_low = sum(r.low for r in monthly.values()) * months
    living_high = sum(r.high for r in monthly.values()) * months

    tuition = program.tuition(student.status)

    stale, unverified = [], []
    for name, rng in monthly.items():
        if not rng.verified:
            unverified.append(f"{city.city}.{name}")
        elif rng.is_stale(expiry_months, today):
            stale.append(f"{city.city}.{name}")

    if not tuition.verified:
        unverified.append(f"{program.id}.tuition")
    elif tuition.is_stale(expiry_months, today):
        stale.append(f"{program.id}.tuition")

    return CostEstimate(
        program_id=program.id,
        tuition=tuition,
        living_low=living_low,
        living_high=living_high,
        monthly={k: v.scaled(months) for k, v in monthly.items()},
        stale_fields=stale,
        unverified_fields=unverified,
    )


def within_tuition_budget(program_tuition: float, tuition_budget: float) -> bool:
    return program_tuition <= tuition_budget


def affordability(estimate: CostEstimate, tuition_budget: float) -> dict:
    """Tuition against the tuition budget. Living costs are reported alongside, never budgeted.

    The student sets a budget for tuition only. Living costs vary with choices they
    haven't made yet (roommates, distance, how they eat), so they are shown as a
    range on top rather than silently mixed into a single pass/fail.
    """
    tuition = estimate.tuition.value
    headroom = tuition_budget - tuition
    return {
        "verdict": "within tuition budget" if headroom >= 0 else "over tuition budget",
        "tuition": tuition,
        "headroom": headroom,
        "living_low": estimate.living_low,
        "living_high": estimate.living_high,
    }
