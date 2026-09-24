#!/usr/bin/env python3
"""Build a fill-in workbook for collecting tuition, cutoffs and availability.

    python make_workbook.py            -> north-path-data.xlsx

One row per university x degree. Fill the yellow columns, then run
`python import_offerings.py north-path-data.xlsx` to write the answers back into
data/offerings.json with their sources and dates.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from costmodel import load_all_programs, load_degrees
from costmodel.loader import _universities

ROOT = Path(__file__).resolve().parent
HEAD_FILL = PatternFill("solid", fgColor="12281E")
FILL_ME = PatternFill("solid", fgColor="FFF2B8")      # yellow: you fill these
READONLY = PatternFill("solid", fgColor="F1EFEA")     # grey: leave alone
HEAD_FONT = Font(name="Arial", bold=True, color="F5EFDC", size=10)
BODY = Font(name="Arial", size=10)
NOTE = Font(name="Arial", size=10, italic=True, color="6A6D73")


def _header(ws, headers, widths, fill_from):
    ws.append(headers)
    for i, (h, w) in enumerate(zip(headers, widths), start=1):
        cell = ws.cell(row=1, column=i)
        cell.fill, cell.font = HEAD_FILL, HEAD_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = f"A2"
    return fill_from


def build() -> Path:
    wb = Workbook()

    # ---------------- how to use ----------------
    ws = wb.active
    ws.title = "Start here"
    lines = [
        ("North Path — data collection workbook", True),
        ("", False),
        ("Yellow columns are yours to fill. Grey columns are generated — leave them.", False),
        ("", False),
        ("Sheets:", True),
        ("  Universities — 25 schools: U-Pass, and anything you want to note.", False),
        ("  Degrees — the 41 options and their ids.", False),
        ("  Offerings — 1,000 rows, one per university x degree. The main job.", False),
        ("", False),
        ("On the Offerings sheet, for each row you care about:", True),
        ("  offered        yes / no / blank. 'no' removes that school from the degree's results.", False),
        ("  tuition_intl   international undergrad tuition for one year, in CAD. Numbers only.", False),
        ("  tuition_dom    domestic rate for the same year.", False),
        ("  cutoff_percent published admission minimum, e.g. 78. Use the low end of a range.", False),
        ("  coop           yes / no / blank — does this degree have a co-op or internship option.", False),
        ("  source_url     the page you read it on. Without this the import leaves it unverified.", False),
        ("  checked_on     the date you looked, as YYYY-MM-DD.", False),
        ("", False),
        ("Do not try to fill all 1,000 rows. Sort by degree, do Computer Science for all 25", False),
        ("schools, then Nursing, then Business. Three degrees done properly beats forty half-done.", False),
        ("", False),
        ("When you're finished: python import_offerings.py north-path-data.xlsx", False),
        ("Then: python validate_data.py", False),
    ]
    for text, bold in lines:
        ws.append([text])
        ws.cell(row=ws.max_row, column=1).font = Font(name="Arial", size=11, bold=bold)
    ws.column_dimensions["A"].width = 100

    # ---------------- universities ----------------
    ws = wb.create_sheet("Universities")
    _header(ws, ["id", "university", "city", "province_note", "upass (yes/no)", "upass_source_url", "notes"],
            [14, 38, 16, 16, 15, 42, 40], 5)
    unis = _universities(None)
    for u in unis:
        ws.append([u["id"], u["name"], u["city"], "",
                   "yes" if (u.get("upass") or {}).get("value") is True else "", "", ""])
    yes_no = DataValidation(type="list", formula1='"yes,no"', allow_blank=True)
    ws.add_data_validation(yes_no)
    yes_no.add(f"E2:E{ws.max_row}")
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for i, cell in enumerate(row, start=1):
            cell.font = BODY
            cell.fill = FILL_ME if i in (4, 5, 6, 7) else READONLY

    # ---------------- degrees ----------------
    ws = wb.create_sheet("Degrees")
    _header(ws, ["id", "degree", "group", "kind"], [18, 44, 30, 10], 99)
    for d in load_degrees().values():
        ws.append([d.id, d.name, d.group, d.kind])
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for cell in row:
            cell.font, cell.fill = BODY, READONLY

    # ---------------- offerings: the fill-in grid ----------------
    ws = wb.create_sheet("Offerings")
    headers = ["key", "university", "city", "degree", "offered (yes/no)", "tuition_intl",
               "tuition_dom", "cutoff_percent", "coop (yes/no)", "source_url", "checked_on"]
    _header(ws, headers, [26, 34, 14, 34, 13, 13, 13, 13, 12, 44, 13], 5)

    # One realistic example row, as the skill requires, marked clearly.
    ws.append(["EXAMPLE — delete this row", "University of Saskatchewan", "Saskatoon",
               "Computer Science", "yes", 24600, 8100, 70, "yes",
               "https://students.usask.ca/money/tuition-fees.php", "2026-09-23"])
    for cell in ws[2]:
        cell.font = NOTE

    programs = sorted(load_all_programs(), key=lambda p: (p.degree_id, p.list_position))
    for p in programs:
        ws.append([p.id, p.university, p.city, p.program, "", None, None, None, "", "", ""])

    yn = DataValidation(type="list", formula1='"yes,no"', allow_blank=True)
    ws.add_data_validation(yn)
    yn.add(f"E3:E{ws.max_row}")
    yn.add(f"I3:I{ws.max_row}")

    for row in ws.iter_rows(min_row=3, max_row=ws.max_row):
        for i, cell in enumerate(row, start=1):
            cell.font = BODY
            cell.fill = FILL_ME if i >= 5 else READONLY
            if i in (6, 7):
                cell.number_format = '$#,##0'
            if i == 8:
                cell.number_format = '0'
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{ws.max_row}"

    out = ROOT / "north-path-data.xlsx"
    wb.save(out)
    return out


if __name__ == "__main__":
    path = build()
    print(f"wrote {path}")
