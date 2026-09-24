# The survey — do this first

Everything in this project depends on knowing what students actually pay. Until
five real people per city answer this, the tool produces untested guesses and
says so on every screen.

Send this to international students you know at each city you cover. It takes
them two minutes. Aim for five per city; ten is better.

---

**Subject: 2 min — what do you actually spend per month?**

Hey — I'm building a tool that tells international students what a year at a
Canadian university really costs, because I couldn't find honest numbers when I
was applying from India. The published figures are always too low.

Could you tell me roughly what you spend per month, in CAD?

1. City:
2. Do you share a bedroom, have your own room in a shared place, or have your own studio?
2b. Are you near campus (walk or short bus) or further out?
3. Rent (your share):
4. Groceries (supermarket only):
4b. Eating out and takeaway, separately:
4c. Roughly how many meals out per week?
5. Transit (pass, or gas and insurance):
6. Phone + internet:
7. Everything else (clothes, going out, health, supplies):
8. Anything that cost way more than you expected?

No names, nothing published individually — it all goes into a range.

And if you don't mind one more: which schools did you apply to, and which others
did you seriously consider but skip? That's what teaches the ranking part.

---

## What to do with the answers

Put each response in `data/survey_responses.csv`, one row each:

```csv
city,housing_type,proximity,rent,food,eating_out,meals_out_per_week,transit,phone_internet,other,as_of,note
Saskatoon,private_room,near,725,380,120,4,55,85,260,2026-09-22,first year student
```

`food` is **groceries only**, because that is what the cost table behind the estimates measures. Put restaurant and takeaway spending in `eating_out`; it is recorded but not yet compared against an estimate.

`housing_type` is one of `shared_room`, `private_room`, `studio`.
`proximity` is `near` or `far`. Both matter: a studio far from campus and a
shared room next to it are different rows against different ranges.

Then run:

```bash
python cli.py calibrate --out CALIBRATION.md
```

That tells you how often your ranges actually contain reality. **That number is
the project.** A tool that says "our ranges cover 82% of real spending, median
error 11%" is worth more than one that quietly shows a confident wrong figure.

If coverage is below ~70%, your ranges are too narrow or centred wrong — widen
or re-anchor them and rerun. Write down what changed and why; that history is
the most interview-ready part of this whole repo.

## The second question

Answers to the "which did you apply to / consider" question go in
`data/labels.csv` (see `train_weights.py` for the format). Thirty of those and
the ranking weights stop being opinions and start being fitted.
