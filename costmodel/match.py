"""Rank programs for a student.

Four component scores, each in [0, 1], combined with weights from weights.json.
The biggest is degree fit: how strong this university is in the degree the
student chose, taken from a published subject ranking when one is on file.
The weights are hand-set until train_weights.py has real labels to fit them to —
the file records which, and the UI says so, because "I chose these numbers" and
"I fitted these numbers" are very different claims.

Interest matching is deliberately a plain token overlap rather than embeddings.
It runs anywhere with no model download, and swap_similarity() below is the one
place to change if you want embeddings later.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .estimate import affordability, estimate_cost
from .schema import City, CostEstimate, Program, Student

WEIGHTS_PATH = Path(__file__).resolve().parent.parent / "weights.json"

STOPWORDS = {
    "a", "an", "and", "the", "of", "in", "for", "with", "to", "on", "or", "i",
    "want", "like", "interested", "study", "studying", "degree", "program",
    "programs", "would", "love", "really", "am", "is", "are", "my", "me",
}


def load_weights(path: Optional[Path] = None) -> dict:
    return json.loads((path or WEIGHTS_PATH).read_text(encoding="utf-8"))


def _tokens(text: str) -> set:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOPWORDS and len(w) > 2}


def token_similarity(interests: str, description: str) -> float:
    """Jaccard-ish overlap, normalised by the shorter side.

    Returns 0.5 for an empty query so that a student who says nothing about
    their interests is not penalised against one who does.
    """
    a, b = _tokens(interests), _tokens(description)
    if not a:
        return 0.5
    if not b:
        return 0.0
    return len(a & b) / len(a)


_similarity: Callable[[str, str], float] = token_similarity


def swap_similarity(fn: Callable[[str, str], float]) -> None:
    """Replace the interest matcher (e.g. with an embedding model)."""
    global _similarity
    _similarity = fn


def admission_fit(student: Student, program: Program) -> float:
    """Logistic curve over the margin between the student's average and the cutoff.

    A 5-point margin is the scale: at the cutoff exactly the score is 0.5, five
    points above it is about 0.73, ten points below about 0.12.
    """
    margin = student.average_percent - program.admission_cutoff_percent.value
    return 1 / (1 + math.exp(-margin / 5))


def admission_label(student: Student, program: Program) -> str:
    margin = student.average_percent - program.admission_cutoff_percent.value
    if margin >= 8:
        return "safety"
    if margin >= 0:
        return "match"
    return "reach"


def cost_fit(estimate: CostEstimate, tuition_budget: float) -> float:
    """How comfortably tuition sits inside the tuition budget, 0.75 to 1.

    Anything over budget is filtered out before scoring, so this only nudges among
    affordable options: tuition at the full budget scores 0.75, free tuition 1.0.
    Kept deliberately gentle — the budget is a limit the student set, not a request
    to rank the cheapest school first.
    """
    if tuition_budget <= 0:
        return 0.0
    tuition = estimate.tuition.value
    if tuition > tuition_budget:
        return 0.0
    return 1.0 - 0.25 * (tuition / tuition_budget)


UNLISTED_GAP = 5.0  # points below the weakest listed school


def degree_fit(program: Program, n_positions: int = 25, unlisted_floor: Optional[float] = None) -> tuple:
    """How strong this university is in the chosen degree, 0 to 1, and on what basis.

    Three cases:
      subject  — the program has a subject_strength score from a published ranking.
      unlisted — other schools have a score for this degree but this one doesn't,
                 meaning it wasn't in the published list. It is placed just below
                 the weakest listed school rather than guessed at. Falling back to
                 overall reputation here would let an unranked school outscore a
                 ranked one, which gets the published ranking backwards.
      overall  — nobody has a score for this degree yet, so fall back to the
                 university's overall list position, and say so.
    """
    s = program.subject_strength
    if s is not None:
        return max(0.0, min(1.0, s.value / 100)), "subject"
    if unlisted_floor is not None:
        return max(0.0, unlisted_floor / 100), "unlisted"
    if program.list_position and n_positions > 1:
        rel = (program.list_position - 1) / (n_positions - 1)
        return 0.9 - 0.6 * rel, "overall"
    return 0.5, "none"


def safety_fit(city: City) -> Optional[float]:
    """Score a city's crime figure against the national baseline, 0 to 1.

    Returns None when the city has no crime figure, so the caller can leave the
    term out rather than silently scoring it as average.

    This is a blunt instrument and the UI says so: a city-wide index tells you
    very little about one neighbourhood, and reported crime is not the same
    thing as a student's actual risk.
    """
    if city.safety is None:
        return None
    ratio = city.safety.relative_to_national()
    # 0.6x national -> ~1.0, national -> 0.65, 2x national -> ~0.2
    return max(0.0, min(1.0, 1.3 - 0.65 * ratio))


def coop_fit(program: Program) -> float:
    """Scores a co-op requirement: does it exist, and how strong is the program.

    No co-op scores 0. With co-op, a school's position on the co-op strength list
    lifts it above the 0.6 baseline; schools with no listing stay at the baseline
    rather than being punished for the list's short length.
    """
    if program.coop.value is False:
        return 0.0
    if program.coop_strength is None:
        return 0.6
    return 0.6 + 0.4 * max(0.0, min(1.0, program.coop_strength.value / 100))


def preference_fit(student: Student, program: Program, city: City) -> float:
    parts: List[float] = []
    if student.wants_coop:
        parts.append(coop_fit(program))
    if student.preferred_city_size:
        parts.append(1.0 if city.size_band == student.preferred_city_size else 0.25)
    if student.crime_matters:
        score = safety_fit(city)
        if score is not None:
            parts.append(score)
    parts.append(_similarity(student.interests, program.description + " " + program.program))
    return sum(parts) / len(parts)


def score_program(
    student: Student,
    program: Program,
    city: City,
    weights: dict,
    expiry_months: int = 6,
    n_positions: int = 25,
    unlisted_floor: Optional[float] = None,
) -> dict:
    est = estimate_cost(program, city, student, expiry_months)
    afford = affordability(est, student.tuition_budget)
    d_fit, d_basis = degree_fit(program, n_positions, unlisted_floor)

    components = {
        "degree_fit": d_fit,
        "admission_fit": admission_fit(student, program),
        "cost_fit": cost_fit(est, student.tuition_budget),
        "preference_fit": preference_fit(student, program, city),
    }
    w = weights["weights"]
    components = {k: v for k, v in components.items() if k in w}
    total = sum(components[k] * w[k] for k in components) + weights.get("bias", 0.0)
    total = max(0.0, min(1.0, total))

    return {
        "program": program,
        "city": city,
        "estimate": est,
        "affordability": afford,
        "components": components,
        "contributions": {k: components[k] * w[k] for k in components},
        "score": total,
        "label": admission_label(student, program),
        "confidence": est.confidence,
        "safety": city.safety,
        "safety_considered": student.crime_matters and city.safety is not None,
        "crime_wanted": student.crime_matters,
        "coop_considered": student.wants_coop,
        "status": student.status,
        "degree_basis": d_basis,
    }


def cheapest_tuition(programs: List[Program], status: str) -> Optional[float]:
    """Lowest tuition for this degree — shown when nothing fits the budget."""
    return min((p.tuition(status).value for p in programs), default=None)


def unlisted_floors(programs: List[Program]) -> Dict[str, float]:
    """Per degree: the score given to schools missing from that degree's published list."""
    lowest: Dict[str, float] = {}
    for p in programs:
        if p.subject_strength is not None:
            v = p.subject_strength.value
            lowest[p.degree_id] = min(v, lowest.get(p.degree_id, v))
    return {d: v - UNLISTED_GAP for d, v in lowest.items()}


def rank(
    student: Student,
    programs: List[Program],
    cities: Dict[str, City],
    weights: Optional[dict] = None,
    expiry_months: int = 6,
    limit: Optional[int] = None,
    one_per_university: bool = False,
) -> List[dict]:
    weights = weights or load_weights()
    n_positions = max((p.list_position for p in programs), default=25) or 25
    floors_all = unlisted_floors(programs)  # computed before filtering, so budget can't move the floor
    programs = [p for p in programs if p.tuition(student.status).value <= student.tuition_budget]
    floors = floors_all
    results = [
        score_program(student, p, cities[p.city], weights, expiry_months, n_positions,
                      floors.get(p.degree_id))
        for p in programs
    ]
    results.sort(key=lambda r: r["score"], reverse=True)
    if one_per_university:
        seen, kept = set(), []
        for r in results:
            uid = r["program"].university_id or r["program"].university
            if uid not in seen:
                seen.add(uid)
                kept.append(r)
        results = kept
    return results[:limit] if limit else results
