"""Load the JSON data files into typed objects, and report what is unverified.

Data layout:
  cities.json        living costs per city
  universities.json  one row per university (name, city, list position)
  degrees.json       the 41 selectable options (40 degrees + a pre-med pathway)
  offerings.json     one row per university x degree: offered?, tuition, cutoff,
                     co-op, subject strength
  outlook.json       salary / job outlook per degree group (context only)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .schema import (
    City, Degree, Figure, Flag, HOUSING_TYPES, PROXIMITIES, Program, Range, Safety,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_DEGREE = "cs"

REQUIRED_COST_KEYS = (
    [f"rent_{h}_{p}" for h in HOUSING_TYPES for p in PROXIMITIES]
    + [f"transit_{p}" for p in PROXIMITIES]
    + ["food", "phone_internet", "other"]
)


def _dir(data_dir: Optional[Path]) -> Path:
    return data_dir or DATA_DIR


def load_cities(path: Path | None = None) -> Tuple[Dict[str, City], int]:
    path = path or DATA_DIR / "cities.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    expiry = int(raw.get("default_expiry_months", 6))
    cities: Dict[str, City] = {}
    for entry in raw["cities"]:
        costs = {k: Range.from_dict(v) for k, v in entry["costs"].items()}
        missing = [k for k in REQUIRED_COST_KEYS if k not in costs]
        if missing:
            raise ValueError(f"{entry['city']} is missing cost entries: {missing}")

        safety = None
        if entry.get("safety"):
            violent = entry["safety"].get("violent_crime_severity_index")
            safety = Safety(
                crime_severity_index=Figure.from_dict(entry["safety"]["crime_severity_index"]),
                note=entry["safety"].get("note", ""),
                violent_crime_severity_index=Figure.from_dict(violent) if violent else None,
            )
        cities[entry["city"]] = City(
            city=entry["city"], province=entry["province"], size_band=entry["size_band"],
            costs=costs, safety=safety,
        )
    return cities, expiry


def load_degrees(data_dir: Optional[Path] = None) -> Dict[str, Degree]:
    raw = json.loads((_dir(data_dir) / "degrees.json").read_text(encoding="utf-8"))
    out: Dict[str, Degree] = {}
    for d in raw["degrees"]:
        out[d["id"]] = Degree(
            id=d["id"], name=d["name"], group=d["group"], kind=d.get("kind", "degree"),
            outlook=d.get("outlook"), pathway=tuple(d.get("pathway", ())), notice=d.get("notice", ""),
        )
    return out


def load_outlook(data_dir: Optional[Path] = None) -> dict:
    path = _dir(data_dir) / "outlook.json"
    return json.loads(path.read_text(encoding="utf-8"))["groups"] if path.exists() else {}


def _universities(data_dir: Optional[Path]) -> List[dict]:
    return json.loads((_dir(data_dir) / "universities.json").read_text(encoding="utf-8"))["universities"]


def _offerings(data_dir: Optional[Path]) -> dict:
    return json.loads((_dir(data_dir) / "offerings.json").read_text(encoding="utf-8"))["offerings"]


def _program(uni: dict, degree: Degree, entry: dict) -> Program:
    strength = entry.get("subject_strength")
    coop_strength = uni.get("coop_strength")
    upass = uni.get("upass")
    return Program(
        id=f"{uni['id']}-{degree.id}",
        university=uni["name"],
        city=uni["city"],
        program=degree.name,
        description=entry.get("description") or degree.name,
        coop=Flag.from_dict(entry.get("coop")),
        admission_cutoff_percent=Figure.from_dict(entry["admission_cutoff_percent"]),
        tuition_intl_annual=Figure.from_dict(entry["tuition_intl_annual"]),
        tuition_domestic_annual=Figure.from_dict(entry["tuition_domestic_annual"]),
        degree_id=degree.id,
        university_id=uni["id"],
        list_position=int(uni.get("list_position", 0)),
        offered=Flag.from_dict(entry.get("offered")),
        subject_strength=Figure.from_dict(strength) if strength else None,
        coop_strength=Figure.from_dict(coop_strength) if coop_strength else None,
        upass=Flag.from_dict(upass) if upass else None,
        tuition_note=uni.get("tuition_note", "") or "",
    )


def load_programs(degree_id: str = DEFAULT_DEGREE, data_dir: Optional[Path] = None) -> List[Program]:
    """Every university's offering of one degree (or one pathway's degrees).

    Universities whose offering is explicitly marked not offered are dropped.
    Unknown ("not yet confirmed") offerings stay in, and are flagged downstream.
    """
    degrees = load_degrees(data_dir)
    if degree_id not in degrees:
        raise ValueError(f"unknown degree {degree_id!r}")
    chosen = degrees[degree_id]
    ids = list(chosen.pathway) if chosen.kind == "pathway" else [chosen.id]

    offerings = _offerings(data_dir)
    programs: List[Program] = []
    for uni in _universities(data_dir):
        for did in ids:
            entry = offerings.get(f"{uni['id']}-{did}")
            if entry is None:
                continue
            prog = _program(uni, degrees[did], entry)
            if prog.offered.value is False:
                continue
            programs.append(prog)
    return programs


def load_all_programs(data_dir: Optional[Path] = None) -> List[Program]:
    degrees = load_degrees(data_dir)
    out: List[Program] = []
    for d in degrees.values():
        if d.kind == "degree":
            out.extend(load_programs(d.id, data_dir))
    return out


def load_all(degree_id: str = DEFAULT_DEGREE, data_dir: Path | None = None):
    cities_path = (data_dir / "cities.json") if data_dir else None
    cities, expiry = load_cities(cities_path)
    programs = load_programs(degree_id, data_dir)

    known_cities = {u["city"] for u in _universities(data_dir)}
    missing = known_cities - set(cities)
    if missing:
        raise ValueError(f"universities reference cities with no cost data: {sorted(missing)}")
    return cities, programs, expiry


def _check(problems: List[str], label: str, item) -> None:
    if item is None:
        return
    if not item.verified:
        problems.append(f"{label}: unverified placeholder")
    elif not item.source_url:
        problems.append(f"{label}: verified but no source_url")
    elif not item.as_of:
        problems.append(f"{label}: verified but no as_of date")


def audit(data_dir: Path | None = None) -> List[str]:
    """Return every field still carrying an unverified placeholder."""
    cities, _, _ = load_all(data_dir=data_dir)
    problems: List[str] = []

    for city in cities.values():
        for name, rng in city.costs.items():
            _check(problems, f"cities.{city.city}.{name}", rng)
        if city.safety is None:
            problems.append(f"cities.{city.city}.safety: not in the published crime table (optional)")
        else:
            _check(problems, f"cities.{city.city}.safety.crime_severity_index", city.safety.crime_severity_index)
            if city.safety.violent_crime_severity_index is not None:
                _check(problems, f"cities.{city.city}.safety.violent_crime_severity_index",
                       city.safety.violent_crime_severity_index)

    programs = load_all_programs(data_dir)
    scored_degrees = {p.degree_id for p in programs if p.subject_strength is not None}
    for prog in programs:
        for name in ("admission_cutoff_percent", "tuition_intl_annual", "tuition_domestic_annual", "coop", "offered"):
            _check(problems, f"offerings.{prog.id}.{name}", getattr(prog, name))
        if prog.subject_strength is None and prog.degree_id not in scored_degrees:
            problems.append(f"offerings.{prog.id}.subject_strength: no subject ranking for this degree yet")
        else:
            _check(problems, f"offerings.{prog.id}.subject_strength", prog.subject_strength)
    return problems
