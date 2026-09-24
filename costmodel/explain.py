"""Plain-language explanations for a ranked result.

Every sentence here must name a number the user can check against the data file.
No sentence should be sayable if the underlying figure is missing.
"""
from __future__ import annotations

from .schema import HOUSING_LABELS


def money(value: float) -> str:
    return f"${value:,.0f}"


def money_range(low: float, high: float) -> str:
    return f"{money(low)}–{money(high)}"


def explain(result: dict) -> str:
    prog = result["program"]
    est = result["estimate"]
    afford = result["affordability"]
    cutoff = prog.admission_cutoff_percent.value

    bits = []

    basis = result.get("degree_basis")
    if basis == "subject":
        src = prog.subject_strength.source.split(":")[0] if prog.subject_strength.source else "a published subject ranking"
        bits.append(f"scores {prog.subject_strength.value:g}/100 for this subject in {src}")
    elif basis == "unlisted":
        bits.append(f"not in the published subject list for {prog.program}, so it is placed below every school that is")
    elif basis == "overall":
        bits.append(
            f"no subject ranking on file for {prog.program} yet, so this uses the university's "
            f"overall position (#{prog.list_position}) instead"
        )

    label = result["label"]
    if label == "safety":
        bits.append(f"your average is comfortably above the {cutoff:g}% cutoff")
    elif label == "match":
        bits.append(f"your average clears the {cutoff:g}% cutoff")
    else:
        bits.append(f"the {cutoff:g}% cutoff is above your average")

    tuition_word = "tuition is" if est.tuition.verified else "tuition is an unconfirmed"
    bits.append(
        f"{tuition_word} {money(afford['tuition'])} a year, {money(afford['headroom'])} under your tuition budget"
        if afford["headroom"] > 0 else
        f"{tuition_word} {money(afford['tuition'])} a year, right at your tuition budget"
    )
    bits.append(
        f"living costs add roughly {money_range(afford['living_low'], afford['living_high'])} a year on top"
    )

    if result.get("safety_considered"):
        safety = result["safety"]
        violent = safety.violent_crime_severity_index
        line = (f"{result['city'].city} scores {safety.crime_severity_index.value:g} on the Crime Severity "
                f"Index, {safety.descriptor()}")
        if violent is not None:
            line += f" (violent crime {violent.value:g})"
        bits.append(line)
    elif result.get("crime_wanted"):
        bits.append(f"no published crime figure for {result['city'].city}, so crime was left out of its score")

    if result.get("coop_considered"):
        strength = result["program"].coop_strength
        if strength is not None:
            bits.append(f"co-op strength {strength.value:g}/100 on the list supplied")

    return "; ".join(bits) + "."


def housing_line(result: dict, student) -> str:
    """One line describing the housing assumption behind the number."""
    label = HOUSING_LABELS[student.housing_type]
    where = "near campus" if student.proximity == "near" else "further out"
    rent = result["estimate"].monthly["rent"]
    transit = result["estimate"].monthly["transit"]
    transit_text = ("transit covered by the U-Pass in student fees" if transit.high == 0
                    else f"{money_range(transit.low, transit.high)} transit")
    line = f"Assumes {label} {where}: {money_range(rent.low, rent.high)} rent and {transit_text} over the year."
    eating = result["estimate"].monthly.get("eating_out")
    if eating is not None and getattr(student, "meals_out_per_week", 0):
        meals = student.meals_out_per_week
        line += (f" Plus {meals:g} meal{'s' if meals != 1 else ''} out a week at $20–30 each: "
                 f"{money_range(eating.low, eating.high)} a year.")
    return line


def caveats(result: dict) -> list:
    est = result["estimate"]
    out = []
    strength = result["program"].subject_strength
    if strength is not None and "applied to this degree" in strength.source:
        out.append("subject score comes from the closest THE subject table, not one for this exact degree")
    if strength is not None and strength.source.startswith("Order only"):
        out.append("subject score is a rough position-based estimate, not a published score")
    prog = result["program"]
    if not est.tuition.verified:
        out.append("this school's tuition has not been checked — the figure shown is a placeholder, so the "
                   "budget filter may be wrong for it")
    if result.get("status") == "domestic" and "Quebec-resident rate" in prog.tuition_note:
        out.append("domestic figure is the Quebec-resident rate — Canadians from other provinces pay more here")
    if result.get("status") == "domestic" and "R-score" in prog.tuition_note:
        out.append("Quebec schools admit on the CEGEP R-score, so the percentage cutoff shown is approximate")
    offered = result["program"].offered
    if offered.value is None or not offered.verified:
        out.append(f"not yet confirmed that {result['program'].university} offers this degree")
    if est.unverified_fields:
        out.append(
            f"{len(est.unverified_fields)} figure(s) behind this number are unverified placeholders — "
            "treat the total as illustrative only"
        )
    if est.stale_fields:
        out.append(
            f"{len(est.stale_fields)} figure(s) are past their check-by date and may have drifted"
        )
    rent = est.monthly.get("rent")
    if rent is not None and rent.source.startswith("Derived"):
        out.append("room rent is derived from the city's 1-bedroom average, not measured for shared housing")
    if rent is not None and "provincial 1-BR average" in rent.source:
        out.append("rent uses the provincial average — no figure published for this city")
    food = est.monthly.get("food")
    if food is not None and "Groceries only" in food.source and "eating_out" not in est.monthly:
        out.append("groceries only — you said no meals out, so nothing is budgeted for restaurants")
    eating = est.monthly.get("eating_out")
    if eating is not None:
        out.append("meal price is one national $20–30 figure, not adjusted per city")
    if rent is not None and rent.n == 0 and rent.verified:
        out.append("rent range has no recorded sample size")
    if result.get("safety_considered"):
        out.append(
            "crime index is city-wide and counts reported crime — it says little about one "
            "neighbourhood or about your own risk"
        )
    if result.get("coop_considered") and result["program"].coop_strength is not None:
        out.append("co-op strength comes from a list with no stated methodology — treat it as a weak signal")
    return out


def top_factors(result: dict, n: int = 2) -> list:
    ordered = sorted(result["contributions"].items(), key=lambda kv: kv[1], reverse=True)
    pretty = {
        "degree_fit": "degree strength",
        "admission_fit": "admission fit",
        "cost_fit": "cost fit",
        "preference_fit": "preference fit",
    }
    return [pretty[k] for k, _ in ordered[:n]]
