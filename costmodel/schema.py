"""Data types. Every cost figure is a range with provenance attached, never a bare number.

Why ranges: rent is a distribution, not a fact. A single figure with a source link
promises a precision the underlying data cannot deliver. A range carries its own
honesty: how wide it is tells the reader how much is actually known.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

CATEGORIES = ["rent", "food", "eating_out", "transit", "phone_internet", "other"]

# Weeks in an average month, for turning meals-per-week into a monthly cost.
WEEKS_PER_MONTH = 4.33

HOUSING_TYPES = ("shared_room", "private_room", "studio")
PROXIMITIES = ("near", "far")

HOUSING_LABELS = {
    "shared_room": "a shared room",
    "private_room": "your own room in a shared place",
    "studio": "your own studio",
}

# The point a city's Crime Severity Index is compared against. Roughly the
# Canada-wide CSI, but not yet checked against the Statistics Canada national
# figure — see VERIFY.md. Not a judgement about any city.
CSI_NATIONAL_BASELINE = 75.0


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


@dataclass(frozen=True)
class Range:
    """A monthly cost range in CAD, with where it came from and when it expires."""

    low: float
    high: float
    n: int = 0
    source_url: Optional[str] = None
    as_of: Optional[str] = None
    verified: bool = False
    source: str = ""  # human-readable name of where the number came from

    def __post_init__(self) -> None:
        if self.low > self.high:
            raise ValueError(f"range low {self.low} is above high {self.high}")
        if self.low < 0:
            raise ValueError("cost ranges cannot be negative")

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2

    @property
    def width(self) -> float:
        return self.high - self.low

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high

    def age_months(self, today: Optional[date] = None) -> Optional[float]:
        checked = _parse_date(self.as_of)
        if checked is None:
            return None
        today = today or date.today()
        return (today - checked).days / 30.44

    def is_stale(self, expiry_months: int, today: Optional[date] = None) -> bool:
        """Unverified or undated figures count as stale. Silence is not freshness."""
        age = self.age_months(today)
        if age is None:
            return True
        return age > expiry_months

    def scaled(self, factor: float) -> "Range":
        return Range(
            low=self.low * factor,
            high=self.high * factor,
            n=self.n,
            source_url=self.source_url,
            as_of=self.as_of,
            verified=self.verified,
            source=self.source,
        )

    @classmethod
    def from_dict(cls, raw: dict) -> "Range":
        return cls(
            low=float(raw["low"]),
            high=float(raw["high"]),
            n=int(raw.get("n", 0) or 0),
            source=raw.get("source", "") or "",
            source_url=raw.get("source_url"),
            as_of=raw.get("as_of"),
            verified=bool(raw.get("verified", False)),
        )


@dataclass(frozen=True)
class Figure:
    """A single published number (tuition, admission cutoff) with provenance.

    Unlike a cost range these really are point values: a university publishes one
    tuition figure. The provenance still matters, and it still expires.
    """

    value: float
    source_url: Optional[str] = None
    as_of: Optional[str] = None
    verified: bool = False
    source: str = ""  # human-readable name of where the number came from

    def is_stale(self, expiry_months: int, today: Optional[date] = None) -> bool:
        checked = _parse_date(self.as_of)
        if checked is None:
            return True
        today = today or date.today()
        return (today - checked).days / 30.44 > expiry_months

    @classmethod
    def from_dict(cls, raw: dict) -> "Figure":
        return cls(
            source=raw.get("source", "") or "",
            value=float(raw["value"]),
            source_url=raw.get("source_url"),
            as_of=raw.get("as_of"),
            verified=bool(raw.get("verified", False)),
        )


@dataclass(frozen=True)
class Flag:
    """A yes/no fact about a program (does it have co-op), with provenance.

    Same discipline as a Figure: somebody has to check it, and it expires.
    """

    value: Optional[bool]  # None = not yet known
    source_url: Optional[str] = None
    as_of: Optional[str] = None
    verified: bool = False
    source: str = ""  # human-readable name of where the fact came from

    def __bool__(self) -> bool:
        return bool(self.value)

    @property
    def known(self) -> bool:
        return self.value is not None

    @classmethod
    def from_dict(cls, raw) -> "Flag":
        if raw is None or isinstance(raw, bool):  # tolerate plain / missing forms
            return cls(value=raw)
        return cls(
            value=None if raw.get("value") is None else bool(raw["value"]),
            source=raw.get("source", "") or "",
            source_url=raw.get("source_url"),
            as_of=raw.get("as_of"),
            verified=bool(raw.get("verified", False)),
        )


@dataclass(frozen=True)
class Safety:
    """City-level crime figure, with the caveat attached to it rather than left implicit."""

    crime_severity_index: Figure
    note: str = ""
    violent_crime_severity_index: Optional[Figure] = None

    def relative_to_national(self) -> float:
        """Ratio against the national baseline. 1.0 means average, 1.4 means 40% above."""
        return self.crime_severity_index.value / CSI_NATIONAL_BASELINE

    def descriptor(self) -> str:
        ratio = self.relative_to_national()
        if ratio <= 0.8:
            return "below the national average"
        if ratio <= 1.2:
            return "around the national average"
        if ratio <= 1.6:
            return "above the national average"
        return "well above the national average"


@dataclass(frozen=True)
class City:
    city: str
    province: str
    size_band: str  # small | medium | large
    costs: dict  # category -> Range; rent and transit are keyed by housing/proximity
    safety: Optional[Safety] = None

    def rent(self, housing_type: str, proximity: str) -> Range:
        if housing_type not in HOUSING_TYPES:
            raise ValueError(f"unknown housing type {housing_type!r}")
        if proximity not in PROXIMITIES:
            raise ValueError(f"unknown proximity {proximity!r}")
        return self.costs[f"rent_{housing_type}_{proximity}"]

    def transit(self, proximity: str) -> Range:
        if proximity not in PROXIMITIES:
            raise ValueError(f"unknown proximity {proximity!r}")
        return self.costs[f"transit_{proximity}"]

    def meal_out(self) -> Optional[Range]:
        """Price of one full meal out, if the city has a figure."""
        return self.costs.get("meal_out")

    def monthly_ranges(self, housing_type: str, proximity: str, meals_out_per_week: float = 0) -> dict:
        """The spending categories for one housing choice.

        Eating out appears only when the student says they eat out: meal price x
        meals per week x weeks per month. At zero meals the line is left out
        entirely rather than shown as $0.
        """
        meal = self.meal_out()
        if meals_out_per_week and meal is not None:
            factor = meals_out_per_week * WEEKS_PER_MONTH
            eating_out = {"eating_out": meal.scaled(factor)}
        else:
            eating_out = {}
        return {**eating_out, **{
            "rent": self.rent(housing_type, proximity),
            "transit": self.transit(proximity),
            "food": self.costs["food"],
            "phone_internet": self.costs["phone_internet"],
            "other": self.costs["other"],
        }}


@dataclass(frozen=True)
class Degree:
    id: str
    name: str
    group: str
    kind: str = "degree"  # degree | pathway
    outlook: Optional[str] = None  # key into outlook.json groups
    pathway: tuple = ()  # for kind == "pathway": the degree ids it ranks
    notice: str = ""


@dataclass(frozen=True)
class Program:
    """One university offering one degree."""

    id: str
    university: str
    city: str
    program: str  # the degree name, as shown
    description: str
    coop: Flag
    admission_cutoff_percent: Figure
    tuition_intl_annual: Figure
    tuition_domestic_annual: Figure
    degree_id: str = ""
    university_id: str = ""
    list_position: int = 0
    offered: Flag = field(default_factory=lambda: Flag(value=True))
    coop_strength: Optional[Figure] = None  # university-level, 0-100
    upass: Optional[Flag] = None  # transit pass bundled into student fees
    tuition_note: str = ""  # what the domestic rate means at this school
    subject_strength: Optional[Figure] = None  # 0-100 from a published subject ranking

    def tuition(self, status: str) -> Figure:
        return (
            self.tuition_intl_annual
            if status == "international"
            else self.tuition_domestic_annual
        )


@dataclass
class Student:
    """What the person tells us about themselves."""

    average_percent: float
    tuition_budget: float  # per year, tuition only; living costs are reported, not budgeted
    status: str = "international"  # international | domestic
    housing_type: str = "private_room"  # shared_room | private_room | studio
    proximity: str = "near"  # near | far (from campus)
    months_per_year: int = 12
    meals_out_per_week: float = 0  # restaurant/takeaway meals; 0 leaves eating out off
    wants_coop: bool = False
    preferred_city_size: Optional[str] = None  # small | medium | large
    crime_matters: bool = False  # weigh city crime figures in the ranking
    interests: str = ""  # free text, matched against program descriptions

    def __post_init__(self) -> None:
        if not 0 <= self.average_percent <= 100:
            raise ValueError("average_percent must be between 0 and 100")
        if self.tuition_budget < 0:
            raise ValueError("tuition budget cannot be negative")
        if self.status not in ("international", "domestic"):
            raise ValueError("status must be international or domestic")
        if self.housing_type not in HOUSING_TYPES:
            raise ValueError(f"housing_type must be one of {HOUSING_TYPES}")
        if self.proximity not in PROXIMITIES:
            raise ValueError(f"proximity must be one of {PROXIMITIES}")
        if not 0 <= self.meals_out_per_week <= 21:
            raise ValueError("meals out per week must be between 0 and 21")


@dataclass
class CostEstimate:
    """Annual cost for one program, as a range, with everything that fed it."""

    program_id: str
    tuition: Figure
    living_low: float
    living_high: float
    monthly: dict = field(default_factory=dict)
    stale_fields: list = field(default_factory=list)
    unverified_fields: list = field(default_factory=list)

    @property
    def total_low(self) -> float:
        return self.tuition.value + self.living_low

    @property
    def total_high(self) -> float:
        return self.tuition.value + self.living_high

    @property
    def total_mid(self) -> float:
        return (self.total_low + self.total_high) / 2

    @property
    def confidence(self) -> str:
        """How much to trust this estimate, in one word.

        Driven by provenance, not by the arithmetic: a tight range built from
        unverified placeholders is not more trustworthy than a wide verified one.
        """
        if self.unverified_fields:
            return "unverified"
        if self.stale_fields:
            return "stale"
        spread = (self.total_high - self.total_low) / max(self.total_mid, 1)
        return "low" if spread > 0.35 else "moderate" if spread > 0.18 else "high"
