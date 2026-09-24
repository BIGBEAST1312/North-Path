"""Gemini integration — two jobs, neither of which is inventing numbers.

1. parse_query()      plain English in, form fields out.
2. summarise()        a short paragraph about results the ranker already computed.

What the model is never allowed to do: supply a tuition figure, a rent figure, a
cost, a cutoff or a ranking. Every number a student sees comes from data/ with a
source attached. A language model asked for "tuition at UBC" will answer with a
confident, plausible, unsourced number — which is the exact failure this project
was built to avoid. So the model gets the numbers as input and is told to use only
those; the summary is checked afterwards, and dropped if it invents a figure.

With no API key the app runs exactly as before: the free-text box is hidden and
no summary appears. Nothing here is load-bearing.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Optional

from .schema import HOUSING_TYPES, PROXIMITIES

API_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "{model}:generateContent")
TIMEOUT = float(os.environ.get("GEMINI_TIMEOUT", "12"))
MAX_TOKENS = int(os.environ.get("GEMINI_MAX_TOKENS", "1200"))
RETRY_PAUSE = float(os.environ.get("GEMINI_RETRY_PAUSE", "0.8"))  # seconds, x attempt

# Google retires model names faster than a portfolio project gets redeployed:
# gemini-2.0-flash and then gemini-2.5-flash both stopped answering while this
# was being built, each time with a 404 naming its replacement. So the model
# name is not hard-coded. GEMINI_MODEL wins if set; otherwise the first name
# below that this key can actually call is used, and a 404 mid-flight moves on
# to the next one rather than breaking the page.
PREFERRED = (
    "gemini-3.6-flash",
    "gemini-flash-latest",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
)
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL") or PREFERRED[0]

_resolved: Optional[str] = None      # the name currently believed to work
_bad: set = set()                    # names this key 404s on
_SUGGESTED = re.compile(r"models/([A-Za-z0-9.\-]+)")


def api_key() -> Optional[str]:
    return os.environ.get("GEMINI_API_KEY") or None


def enabled() -> bool:
    return bool(api_key())


def _debug(message: str) -> None:
    """Say why a summary was dropped. Set GEMINI_DEBUG=1 to see these."""
    if os.environ.get("GEMINI_DEBUG"):
        print(f"[assistant] {message}", flush=True)


class GeminiError(RuntimeError):
    pass


def list_models() -> list:
    """Model names this key may call. Useful when a model name is refused."""
    key = api_key()
    if not key:
        raise GeminiError("no API key")
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8"))["error"]["message"]
        except Exception:  # noqa: BLE001
            pass
        raise GeminiError(f"HTTP {exc.code}{': ' + detail if detail else ''}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GeminiError(f"could not connect: {exc}") from exc
    return [m["name"].removeprefix("models/") for m in payload.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])]


def current_model() -> str:
    """The name that will be tried next. Not a promise that it works."""
    return _resolved or DEFAULT_MODEL


def resolve_model(*, refresh: bool = False, skip=()) -> str:
    """Pick a model name this key can call.

    An explicit GEMINI_MODEL is honoured until it 404s. Otherwise the preferred
    list is checked against what the key actually offers. `_bad` is permanent
    for the process (retired names); `skip` is for this request only (a model
    that is merely busy right now).
    """
    global _resolved
    out = set(_bad) | set(skip)
    if _resolved and not refresh and _resolved not in out:
        return _resolved

    pinned = os.environ.get("GEMINI_MODEL")
    if pinned and pinned not in out:
        _resolved = pinned
        return _resolved

    try:
        available = [m for m in list_models() if m not in out]
    except GeminiError:
        available = []

    for name in PREFERRED:
        if name in out:
            continue
        if not available or name in available:
            _resolved = name
            return _resolved
    for name in available:                      # anything current, flash first
        if "flash" in name:
            _resolved = name
            return _resolved
    if available:
        _resolved = available[0]
        return _resolved
    raise GeminiError("no usable model: this key offers none that answer")


def _extract(payload: dict) -> str:
    """The text of the answer, ignoring any reasoning parts.

    Gemini 3 models return their thinking as parts marked `thought`, and spend
    output tokens on it before writing a word. A response can therefore come
    back valid, billed and completely empty — which reads as "the model gave me
    nothing usable" unless the reason is surfaced. So: empty is an error here,
    carrying the finishReason, not a silent blank.
    """
    candidates = payload.get("candidates") or []
    if not candidates:
        blocked = (payload.get("promptFeedback") or {}).get("blockReason")
        raise GeminiError(f"no answer returned{f' (blocked: {blocked})' if blocked else ''}")
    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        reason = candidate.get("finishReason", "unknown")
        if reason == "MAX_TOKENS":
            raise GeminiError("the model used its whole output budget on reasoning "
                              "and wrote nothing — raise GEMINI_MAX_TOKENS")
        raise GeminiError(f"empty answer (finishReason {reason})")
    return text


def _post(model: str, prompt: str, temperature: float, max_tokens: int,
          *, json_only: bool = False, thinking: bool = False) -> str:
    key = api_key()
    config = {"temperature": temperature, "maxOutputTokens": max_tokens}
    if json_only:
        config["responseMimeType"] = "application/json"
    if not thinking:
        # Nothing here needs deliberation, and thinking eats the output budget.
        config["thinkingConfig"] = {"thinkingBudget": 0}
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": config,
    }).encode("utf-8")
    url = API_URL.format(model=model) + f"?key={key}"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Google says why in the body; pass that through rather than "request failed".
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8"))["error"]["message"]
        except Exception:  # noqa: BLE001 - the body may be empty or not JSON
            pass
        raise GeminiError(f"HTTP {exc.code}{': ' + detail if detail else ''}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GeminiError(f"could not connect: {exc}") from exc
    return _extract(payload)


def _call(prompt: str, *, temperature: float = 0.0, max_tokens: int = 0,
          json_only: bool = False) -> str:
    """Post the prompt, walking past retired model names instead of failing."""
    global _resolved
    if not api_key():
        raise GeminiError("no API key")
    max_tokens = max_tokens or MAX_TOKENS
    last: Optional[GeminiError] = None
    busy = 0
    skip: set = set()
    for attempt in range(4):
        model = resolve_model(skip=skip)
        try:
            return _post(model, prompt, temperature, max_tokens, json_only=json_only)
        except GeminiError as exc:
            message = str(exc)
            if message.startswith("HTTP 400") and ("Unknown name" in message
                                                   or "thinking" in message.lower()
                                                   or "responseMimeType" in message):
                # An older model that doesn't take these options. Ask plainly.
                _debug(f"{model} rejected the request options; retrying without them")
                return _post(model, prompt, temperature, max_tokens, thinking=True)
            if message.startswith(("HTTP 503", "HTTP 429")):
                # Overloaded or throttled: momentary, and the caller is a web
                # request waiting on it. Pause, then try a different model.
                busy += 1
                last = exc
                _debug(f"{model} is busy ({message[:12]}); retry {busy}")
                if busy >= 3:
                    raise GeminiError("the model is busy right now — try again in a moment") from exc
                time.sleep(RETRY_PAUSE * busy)
                if json_only:
                    # Constrained decoding is the first thing to be refused under
                    # load, and it is only a convenience — the reply is scanned
                    # for a JSON object either way. Ask plainly instead.
                    _debug("dropping JSON mode for the retry")
                    json_only = False
                elif busy > 1:
                    skip.add(model)          # a different model may be less loaded
                continue
            if not message.startswith("HTTP 404"):
                raise                        # a key or network problem: don't shop around
            _bad.add(model)
            last = exc
            # Google's own 404 usually names the replacement — try that first.
            for name in _SUGGESTED.findall(message):
                if name != model and name not in _bad:
                    _debug(f"{model} is retired; Google suggests {name}")
                    _resolved = name
                    break
            else:
                _debug(f"{model} is retired; looking for another")
                _resolved = None
                resolve_model(refresh=True)
    raise last or GeminiError("no usable model")


# --------------------------------------------------------------------------- parse

PARSE_PROMPT = """Turn a student's sentence into search filters for a Canadian university tool.

Return ONLY a JSON object, no prose, no code fence. Keys, all optional — leave a key
out when the sentence does not say:
  average          number 0-100
  tuition_budget   number, CAD per year, TUITION ONLY
  status           "international" or "domestic"
  degree           the ID of the closest match from this list, e.g. "cs" not
                   "computer science": {degrees}
  housing_type     one of: shared_room, private_room, studio
  proximity        "near" or "far"
  meals_out        number of restaurant meals per week
  city_size        "small", "medium" or "large"
  coop             true or false
  crime            true or false

Rules:
- Never guess. A sentence with no budget gets no tuition_budget key.
- A budget described as covering everything is still the tuition budget here; use it.
- "78%" or "78 percent" or "I have a 78 average" all mean average: 78.
- Pick the closest degree from the list; if none is close, leave degree out.

Sentence: {query}"""


def _degree_index(degrees) -> tuple:
    """(ids, lookup). Accepts ids, or a mapping of id -> Degree so names help too.

    The ids are terse — `cs`, `it`, `ece` — so a model told only the ids has to
    guess that "computer science" is `cs`. Giving it the names, and accepting a
    name back, is the difference between a parse that works and a blank box.
    """
    ids, lookup = [], {}
    mapping = degrees if hasattr(degrees, "items") else {}
    for key in degrees:
        ids.append(key)
        lookup[_norm(key)] = key
        name = getattr(mapping.get(key), "name", None) if mapping else None
        if name:
            lookup[_norm(name)] = key
            for piece in name.replace("(", "/").replace(")", "/").split("/"):
                if piece.strip():
                    lookup.setdefault(_norm(piece), key)
    return ids, lookup


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def parse_query(query: str, degrees) -> dict:
    """Plain English -> form fields. Returns {} when the model gives nothing usable."""
    if not query.strip():
        return {}
    ids, lookup = _degree_index(degrees)
    mapping = degrees if hasattr(degrees, "items") else {}
    listing = ", ".join(
        f"{i} ({getattr(mapping.get(i), 'name', '')})" if mapping and getattr(mapping.get(i), "name", "")
        else i
        for i in sorted(ids)
    )
    text = _call(PARSE_PROMPT.format(degrees=listing, query=query.strip()), json_only=True)
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        _debug(f"no JSON object in the reply: {text[:200]!r}")
        return {}
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError:
        _debug(f"reply was not valid JSON: {match.group(0)[:200]!r}")
        return {}
    cleaned = _clean(raw, lookup)
    if not cleaned:
        _debug(f"every field was discarded; the model returned {raw}")
    return cleaned


def _number(value, low, high):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if low <= n <= high else None


def _clean(raw: dict, lookup) -> dict:
    """Keep only values this app can actually use. The model is not trusted to be in range."""
    if not hasattr(lookup, "get"):          # a bare list of ids still works
        lookup = {_norm(i): i for i in lookup}
    out = {}
    if (v := _number(raw.get("average"), 0, 100)) is not None:
        out["average"] = v
    if (v := _number(raw.get("tuition_budget"), 1, 500_000)) is not None:
        out["budget"] = v
    if raw.get("status") in ("international", "domestic"):
        out["status"] = raw["status"]
    if (degree := lookup.get(_norm(raw.get("degree") or ""))):
        out["degree"] = degree
    if raw.get("housing_type") in HOUSING_TYPES:
        out["housing_type"] = raw["housing_type"]
    if raw.get("proximity") in PROXIMITIES:
        out["proximity"] = raw["proximity"]
    if (v := _number(raw.get("meals_out"), 0, 21)) is not None:
        out["meals_out"] = v
    if raw.get("city_size") in ("small", "medium", "large"):
        out["city_size"] = raw["city_size"]
    if isinstance(raw.get("coop"), bool):
        out["coop"] = raw["coop"]
    if isinstance(raw.get("crime"), bool):
        out["crime_matters"] = raw["crime"]
    return out


# ----------------------------------------------------------------------- summarise

SUMMARY_PROMPT = """You are writing two or three sentences under a university shortlist.

These are the results, already computed:
{facts}

"Likely admit" means the published cutoff is at or below the student's average; "reach"
means it is above; "match" is borderline. The cards below already show every figure, so
your job is the shape of the list, not its contents.

Write it for the student, in plain sentences, as a person would say it out loud.

Hard rules:
- At most THREE numbers in total, and only ones that appear above, written exactly as
  they are written above. No rounding, no restating, no new figures. When in doubt, use
  fewer numbers and more words.
- Never list ranges one after another or recite the shortlist school by school.
- Do not rank, re-order or recommend a single school.
- If a figure is marked unconfirmed, say so when you mention it.
- No preamble, no bullet points, no headings. Two or three sentences."""


def _facts(results) -> str:
    lines = []
    for r in results:
        p, est = r["program"], r["estimate"]
        lines.append(
            f"- {p.university} ({p.city}): {p.program}, index {r['score']*100:.0f}%, "
            f"{r['label']}, tuition ${est.tuition.value:,.0f}"
            f"{' (unconfirmed)' if not est.tuition.verified else ''}, "
            f"living ${est.living_low:,.0f}-${est.living_high:,.0f}"
        )
    return "\n".join(lines)


NUMBER = re.compile(r"\$?\d[\d,]*(?:\.\d+)?")   # a sentence-ending period is not a decimal
YEAR = re.compile(r"^(19|20)\d\d$")


def _invented_number(text: str, facts: str) -> Optional[str]:
    """The first figure in the summary that isn't in the facts we handed it, if any.

    Deliberately strict about money: a summary that quietly rounds $66,110 to
    $66,000 is still putting a figure on screen that no source supports. Years
    ("the 2026 rankings") and small counts ("all three schools") are let through,
    because those aren't claims about cost.
    """
    allowed = {n.lstrip("$").replace(",", "") for n in NUMBER.findall(facts)}
    for token in NUMBER.findall(text):
        bare = token.lstrip("$").replace(",", "")
        if bare in allowed:
            continue
        is_money = token.startswith("$")
        value = float(bare) if bare.replace(".", "", 1).isdigit() else 0
        if not is_money and (value <= 100 or YEAR.match(bare)):
            continue  # a count, a percentage or a year, not a cost claim
        return token
    return None


def summarise(results) -> Optional[str]:
    """A short paragraph about the shortlist, or None if anything is off."""
    if not results:
        return None
    facts = _facts(results[:6])
    text = _call(SUMMARY_PROMPT.format(facts=facts), temperature=0.3).strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        _debug("model returned nothing")
        return None
    if len(text) > 700:
        _debug(f"summary too long ({len(text)} chars)")
        return None
    invented = _invented_number(text, facts)
    if invented:
        _debug(f"summary discarded: it contains {invented}, which is not in the data")
        return None
    return text
