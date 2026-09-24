# What to verify, and where

Every number in `data/` is a placeholder. Run `python validate_data.py` to see what's
left. For each figure: enter the real value, add the page URL to `source_url`, set
`as_of` to the date you checked it, then set `verified` to `true`.

**Easiest route:** `python make_workbook.py` builds `north-path-data.xlsx` with every row laid out and the
columns to fill highlighted. Fill it in a spreadsheet, then `python import_offerings.py north-path-data.xlsx --write`.
Editing the JSON by hand works too; the fields are below.

## offerings.json (25 universities × 40 degrees = 1,000 entries)

Keyed `<university>-<degree>`, e.g. `usask-nursing`. `python validate_data.py --only usask`
narrows the list to one school.

| Field | Where to find it |
| --- | --- |
| `tuition_intl_annual` | University's "tuition and fees" page, international undergrad, faculty of science or computer science. Use one year of full-time study. |
| `tuition_domestic_annual` | Same page, domestic/Canadian rate. For Quebec schools, use the rate for out-of-province Canadians too. |
| `admission_cutoff_percent` | Admissions page for the program. Many schools post a published minimum. When they post a range, use the low end and note that in `source_url`. |
| `coop` | Program page. Only set `true` if co-op or a paid internship option actually exists for that degree. |
| `offered` | Program page. `true` if the undergraduate degree exists, `false` to drop the school from that degree's results, `null` if unchecked. |
| `subject_strength` | A published subject ranking: QS World University Rankings by Subject, THE by subject, or Maclean's program rankings. Convert the school's position to 0–100 in a consistent way and write down how in the source note, e.g. `100 - 3 × (Canadian rank − 1)`. Use the same formula for every school within a degree. |

**Subject strength status:** THE 2026 scores are entered for 36 degrees. They were typed in from screenshots, so they're marked unverified: open each THE subject page on timeshighereducation.com, check the numbers, add the URL and set `verified` to true. Still missing: Biology, Environmental Science and Neuroscience (THE's *Life sciences* table), and Political Science, Criminology, Sociology and Social Work (THE's *Social sciences* table). Queen's and the Université du Québec network appear in some tables but aren't among the 25 universities, so they were skipped.

**Done so far:** Computer Science, Business and Nursing — 75 rows, every one with a source URL and a date.
Still blank inside those three: international tuition for McGill, Alberta, Ottawa and Victoria (plus York and
Dalhousie for nursing), most admission cutoffs, and some co-op flags. Quebec schools admit on the CEGEP
R-score, so a percentage cutoff there is approximate at best.

**Don't try all 1,000.** Pick 3–4 degrees, e.g. Computer Science, Nursing, Business and Mechanical Engineering. Fill `offered` and `subject_strength` for all 25 schools in those degrees first, because those two fields are what the ranking mainly depends on. Tuition and cutoffs can come next.

## The national crime baseline

`CSI_NATIONAL_BASELINE` in `costmodel/schema.py` is 75, an approximation of the Canada-wide CSI. Check the real national figure for 2024 on Statistics Canada and update it — every city's crime score is measured against it.

## universities.json — `upass`

`true` means the university charges a transit pass in student fees, so transit leaves the living-cost total. Check each school's mandatory-fees page and set it; `null` (unchecked) keeps the city fare estimate, which overstates cost for schools that do bundle a pass. USask is the only one set so far, and from a student's report rather than the fees page.

## universities.json — `coop_strength`

Position on an unattributed "top 30 for co-op" list, converted to 0–100. Replace with CEWIL Canada placement data or each university's published co-op numbers, or delete the field: schools without it sit at a neutral baseline.

## outlook.json

Salary and outlook are copied from University Magazine, which is a secondary source. Replace them with Statistics Canada's graduate outcomes data (median employment income two years after graduation, by field of study), then set `verified` to true.

## cities.json (19 cities)

| Field | Where to find it |
| --- | --- |
| `rent_*` | Now built from a supplied 1-bedroom average per city. **Studio** = that figure, -15% / +20%. **Private room** = 55% of it, **shared room** = 40% — both derived, not measured, and labelled that way on every card. Near and far are identical because the source has no campus-distance split. To do this properly: sample real listings on Rentals.ca, Kijiji or Facebook Marketplace for each housing type, record the low and high, put the number of listings in `n`, replace `source`, and set `verified`. Guelph, Sherbrooke and Fredericton currently use their provincial average; Waterloo uses Kitchener's figure. |
| `transit_near` / `transit_far` | City transit fare page — the fallback for schools with no confirmed U-Pass. |
| `food` | Now a provincial single-person grocery range from the supplied table — the same figure for every city in a province, and groceries only. City-level figures, or your own survey answers, would improve it. |
| `meal_out` | One national $20–30 figure for a full meal out, applied to every city. Replace with per-city restaurant prices (a local mid-range lunch survey, or Numbeo's "inexpensive restaurant" figure) so Vancouver and Saskatoon stop costing the same. |
| `phone_internet`, `other` | Still placeholders. These come from the survey, not from websites. See `SURVEY.md`. |
| `safety` (optional block) | Now filled for 15 cities with the 2024 Crime Severity Index and violent CSI, taken from Wikipedia's transcription of the Statistics Canada table. Confirm each against Statistics Canada table 35-10-0026-01, add the URL, then set `verified`. Victoria, Quebec City, Sherbrooke and Fredericton are not in the published table — leave them without a figure rather than estimating one. |

Add a `safety` block like this when you have the figure:

```json
"safety": {
  "crime_severity_index": {"value": 0, "source_url": "…statcan…", "as_of": "2026-09-21", "verified": true},
  "note": "City-wide index; says little about a specific neighbourhood."
}
```

## Don't

- Don't copy a number from a blog or an AI answer and mark it `verified`. That rule includes numbers from this project's own generator.
- Don't mark a field `verified` without a `source_url`. `validate_data.py` will flag it.
