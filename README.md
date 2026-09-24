# North Path — Program Index

A degree-first university selector for Canada. Pick one of 40 degrees (or the
pre-med pathway), tell it your average, budget and living preferences, and it
ranks 25 Canadian universities by how strong they are in that degree, whether
you'd get in, and what a year would actually cost — tuition plus rent, food and
transit — as a **range**, with its sources and its measured error shown.

Built because published cost-of-living figures for international students are
close to useless: a single confident number, no source, no date, usually low.

## What makes it different from a filter with a nice UI

1. **Every living cost is a range, not a point estimate.** Rent is a
   distribution, not a fact. A range carries its own honesty — how wide it is
   tells you how much is actually known.
2. **Every figure has provenance and an expiry.** Source URL, date checked, and
   a check-by date after which it is marked stale rather than quietly presented
   as current.
3. **The ranges are calibrated against what real students pay**, and the tool
   displays that error rate rather than hiding it.
4. **The ranking weights say whether they were chosen or fitted.** Hand-set
   weights are opinions; the UI labels them as such until `train_weights.py`
   replaces them with weights fitted to real choices.

## Quick start

```bash
pip install -r requirements.txt

python validate_data.py                  # what still needs a real source
python cli.py degrees                    # the 41 options and their ids
python cli.py rank --degree nursing --average 85 --budget 50000 --coop \
    --housing-type private_room --proximity near
python cli.py rank --degree premed --average 90 --budget 55000
python cli.py cost --city Saskatoon --housing-type studio --proximity far
python cli.py calibrate                  # how well the ranges match reality
python app.py                            # web UI on http://localhost:5000
python -m unittest discover -s tests     # 105 tests
```

## Collecting the data

```bash
python make_workbook.py                          # -> north-path-data.xlsx
# fill the yellow columns in Excel / Sheets / LibreOffice
python import_offerings.py north-path-data.xlsx  # dry run
python import_offerings.py north-path-data.xlsx --write
python validate_data.py
```

The workbook has three sheets: **Universities** (25 rows, U-Pass), **Degrees**
(the 41 options and their ids) and **Offerings** (1,000 rows, one per university
× degree, with columns for offered, tuition international, tuition domestic,
admission cutoff, co-op, source URL and date). A row with a source URL and a
date imports as verified; without them it still imports but stays flagged, so
`validate_data.py` keeps listing it.

## The state of the data

**Computer Science, Business and Nursing are filled in** — 75 university × degree
rows with international and domestic tuition, admission cutoffs where the school
publishes one, co-op, and a source URL for every row. Five schools are confirmed
*not* to offer nursing (Waterloo, SFU, Guelph, Concordia, UQAM) and drop out of
that degree's results. The U-Pass is confirmed for all 25 universities.

Everything else is still an unverified placeholder, and the tool says so on
every screen. A school whose tuition hasn't been checked shows "unconfirmed"
beside the figure, because the budget filter can only be as right as that number.

Your first real job is replacing them:

1. Run `python validate_data.py` for the list of what's missing.
2. For each: find the figure on an official or primary page, put the number in,
   fill `source_url` and `as_of`, and set `verified` to `true`.
3. Tuition and admission cutoffs come from the university's own pages. Rent
   comes from rental listings (record a low and a high across a real sample, and
   put the sample size in `n`) or StatCan tables. Transit comes from the city's
   fare page. Crime figures come from the Statistics Canada Crime Severity Index
   table for that city.
4. Rerun `validate_data.py` until it's clean.

Do **three cities** properly before adding a fourth. The first council on this
project was blunt about it: scraping fifteen sites is how this stalls half-built.

## Then calibrate

See `SURVEY.md`. Ask five international students per city what they actually
spend, put the answers in `data/survey_responses.csv`, and run
`python cli.py calibrate --out CALIBRATION.md`.

That report — predicted range versus reality, coverage and median error per
category — is the most valuable artifact in this repo. It is the answer to "how
do you know your numbers are right", which is the question anyone serious will
ask.

## Then learn the weights

Until there are labelled choices, ranking weights are hand-set and the interface
admits it. Collect thirty or more rows of "here's a student, here's a program,
did they choose it" in `data/labels.csv` and run:

```bash
python train_weights.py --labels data/labels.csv --dry-run   # look first
python train_weights.py --labels data/labels.csv             # then write
```

It fits a logistic regression by plain gradient descent — about twenty lines you
can walk anyone through — reports accuracy against the majority-class baseline,
and tells you when the fitted model isn't beating that baseline instead of
pretending it is.

## Layout

```
costmodel/
  schema.py      Range and Figure types: provenance and staleness live here
  loader.py      load JSON into typed objects, audit what's unverified
  estimate.py    tuition + living costs -> annual range, affordability verdict
  match.py       four component scores (degree strength first), weights from weights.json
  explain.py     plain-language reasons naming checkable numbers
  calibrate.py   predicted ranges vs real reports: coverage and error
  assistant.py   Gemini: parses a sentence, summarises results, invents nothing
  ratelimit.py   the assistant's hourly call budget; the ranking is never limited
data/
  degrees.json        41 options: 40 degrees + the pre-med pathway
  universities.json   25 universities, city, list position
  offerings.json      university x degree: offered?, tuition, cutoff, co-op, subject strength
  outlook.json        salary / job outlook per degree group (display only)
  cities.json         living-cost ranges per city, plus optional crime index
  survey_responses.csv what real students report spending
cli.py           rank / cost / calibrate / audit
app.py           Flask web UI
train_weights.py fit the ranker weights instead of choosing them
validate_data.py pre-commit data check
make_workbook.py  build the fill-in spreadsheet
import_offerings.py  read the filled spreadsheet back into data/
```

## The assistant (optional)

Set `GEMINI_API_KEY` and two things appear: a plain-English box that fills in the
form, and a short summary above the results. Both are deliberately fenced in —
the model never supplies a number.

- **Parsing:** every field it returns is validated the same way the form is. An
  average of 250, an unknown degree or a nonsense city size is discarded.
- **Summarising:** it is handed the computed figures and told to use only those.
  Any summary containing a number that isn't in them is thrown away, including a
  rounded version of a real one (`$66,000` for `$66,110` fails).

The model name is not pinned: Google retires them faster than a portfolio
project gets redeployed, so the app asks the key what it can call, and a 404
naming a replacement is followed rather than surfaced as a broken page.
`python check_gemini.py` diagnoses a key or model problem in one step.

With no key the app behaves exactly as before, so an expired key or a rate limit
degrades the page rather than breaking it. `costmodel/assistant.py` is the whole
integration.

## Deploying

See `DEPLOY.md`. Short version: push to GitHub, create a Render web service with
build `pip install -r requirements.txt` and start
`gunicorn app:app --bind 0.0.0.0:$PORT`, then add `GEMINI_API_KEY` in the
dashboard. `render.yaml` describes the same setup for a blueprint deploy.

## How degree choice drives the ranking

The index score has four parts: **degree strength** (50%), admission fit
(20%), cost fit (15%) and preferences (15%). The budget is **tuition only** and
acts as a hard filter: programs over it are removed, and if none remain the
page says "No universities available for the selected tuition fee budget" and
shows the lowest tuition for that degree. Living costs are estimated and shown
with each result, never mixed into the budget. Degree strength comes from
`subject_strength` in `offerings.json` — a 0–100 figure from a published subject
ranking (QS by Subject, THE by subject, Maclean's program rankings), with its
source. 36 of the 40 degrees now use **THE World University Rankings 2026 by
subject**, with the published "Overall" score as the 0–100 figure (the midpoint
where THE only gives a band). Mapping:

| THE subject table | Degrees it scores |
| --- | --- |
| Computer Science | CS, Software Eng, Data Science, IT, Cybersecurity |
| Medicine (clinical & health) | Nursing, Health Sci, Pharmacy, Public Health, Nutrition, Med Lab |
| Business & economics | Business, Accounting, Economics, Finance, Marketing, HR, Supply Chain |
| Engineering | all five engineering degrees |
| Psychology / Education | Psychology / Education |
| Physical sciences | Physics, Biochem/Chem, Math & Stats |
| Arts & humanities | English, History, Fine Arts, Architecture |

Where the table isn't an exact match for the degree (for example, CS scores
applied to IT), the card says so. Agriculture uses a position-only list and is
labelled as a rough estimate. Schools missing from a THE table are placed just
below the lowest-ranked school on it, not guessed at. Biology, Environmental
Science, Neuroscience and the social sciences still have no subject data and
fall back to overall position; THE's Life Sciences and Social Sciences tables
would cover them.

Universities marked `offered: false` for a degree are removed from its results.
`null` means not yet confirmed: they stay in, flagged.

Salary and job outlook appear for the chosen degree but never affect the score —
they describe the degree, not the university, so they are the same for every
school in the list.

**Pre-med pathway.** Canada has no MBBS; the MD comes after an undergraduate
degree, surgery is a residency after that, and most medical schools admit few or
no international students. Choosing "Planning to become a doctor" ranks the
usual undergraduate routes (Biology, Health Sciences, Biochemistry, Neuroscience),
one result per university, under a notice saying all of this.

## Housing, distance and crime

Rent comes from a supplied 1-bedroom average per city. The **studio** range is
that figure (-15% / +20%); **private** and **shared** rooms are derived from it
(55% and 40%) and every card that uses them says "derived, not measured".
15 cities have their own figure, Waterloo borrows Kitchener's, and Guelph,
Sherbrooke and Fredericton fall back to a provincial average and say so.
Distance from campus changes transit but not rent, because the source is one
city-wide average — a discount for living further out would be invented.

**Eating out.** Groceries and restaurants are separate lines. A meal out is
priced at $20–30 and multiplied by the meals-per-week the student enters; at
zero the line disappears. One national meal price for now, so it understates the
expensive cities.

**U-Pass.** Where a university charges a transit pass in student fees, transit
drops out of the living-cost total and the card says "covered by the U-Pass in
student fees". Set `upass.value` per university in `universities.json`; `null`
means unchecked and the city fare estimate is used. Only USask is confirmed.
Note that mandatory student fees, including the U-Pass fee itself, are not in
the tuition figures either — that gap is stated on the methodology page.

Crime is off by default. Tick "crime rate matters to me" and the city's
Statistics Canada **Crime Severity Index (2024)** is scored against a national
baseline and folded into preference fit; the card shows the score, the violent
crime figure, and the reminder that a city-wide index says little about one
neighbourhood. 15 of the 19 cities are in the published table. The other four
(Victoria, Quebec City, Sherbrooke, Fredericton) have no figure, and the card
says crime was left out of their score rather than assuming average.

Ticking "co-op is a must" drops programs without co-op and nudges the rest by a
university-level co-op strength score. That list came with no publisher or
methodology, so it is deliberately weak: on the list helps a little, off it
costs nothing, and the card labels it.

## Limits worth stating out loud

- Admission cutoffs are published minimums, not predictions of your odds.
- The crime index is city-wide, reported-crime only, and is not a measure of any
  individual student's risk.
- "Near campus" and "further out" are two coarse buckets, not a commute model.
- Scholarships, bursaries and assistantships are not modelled at all.
- Interest matching is token overlap, not semantics. `swap_similarity()` in
  `match.py` is the single place to plug in embeddings.
- Three cities and six programs is a demonstration, not coverage of Canada.
