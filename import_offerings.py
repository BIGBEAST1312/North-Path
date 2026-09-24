#!/usr/bin/env python3
"""Read the filled workbook back into data/offerings.json and universities.json.

    python import_offerings.py north-path-data.xlsx            # see what would change
    python import_offerings.py north-path-data.xlsx --write    # actually write

Only rows you filled are touched. A figure with a source_url and a checked_on date
is marked verified; without them it is imported but stays unverified, because an
unsourced number is a guess wearing a number's clothes.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _yes_no(value):
    if value is None:
        return None
    v = str(value).strip().lower()
    return True if v in ("yes", "y", "true", "1") else False if v in ("no", "n", "false", "0") else None


def _date(value):
    if value is None:
        return None
    text = str(value)[:10].strip()
    return text if DATE.match(text) else None


def _figure(value, url, checked, existing):
    """Build a figure dict, preserving what was already verified if the cell is blank."""
    if value in (None, ""):
        return existing, False
    verified = bool(url) and bool(checked)
    return ({"value": float(value), "source": "", "source_url": url or None,
             "as_of": checked, "verified": verified}, True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("workbook")
    ap.add_argument("--write", action="store_true", help="save changes (otherwise dry run)")
    args = ap.parse_args()

    wb = load_workbook(ROOT / args.workbook, data_only=True)
    offerings_path = ROOT / "data" / "offerings.json"
    unis_path = ROOT / "data" / "universities.json"
    off = json.loads(offerings_path.read_text(encoding="utf-8"))
    unis = json.loads(unis_path.read_text(encoding="utf-8"))

    changes, unsourced, unknown = 0, 0, []

    ws = wb["Offerings"]
    for row in ws.iter_rows(min_row=2, values_only=True):
        key, _u, _c, _d, offered, t_intl, t_dom, cutoff, coop, url, checked = row[:11]
        if not key or str(key).startswith("EXAMPLE"):
            continue
        entry = off["offerings"].get(str(key).strip())
        if entry is None:
            unknown.append(key)
            continue
        checked = _date(checked)
        url = (str(url).strip() or None) if url else None
        touched = False

        for cell, field in ((t_intl, "tuition_intl_annual"), (t_dom, "tuition_domestic_annual"),
                            (cutoff, "admission_cutoff_percent")):
            new, did = _figure(cell, url, checked, entry[field])
            if did:
                entry[field], touched = new, True
                if not new["verified"]:
                    unsourced += 1

        for cell, field in ((offered, "offered"), (coop, "coop")):
            flag = _yes_no(cell)
            if flag is not None:
                entry[field] = {"value": flag, "source": "", "source_url": url or None,
                                "as_of": checked, "verified": bool(url) and bool(checked)}
                touched = True
                if not (url and checked):
                    unsourced += 1
        changes += touched

    ws = wb["Universities"]
    by_id = {u["id"]: u for u in unis["universities"]}
    upass_changes = notes_changes = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        uid, _name, _city, prov_note, upass, upass_url, notes = row[:7]
        if uid not in by_id:
            continue
        uni = by_id[uid]
        flag = _yes_no(upass)
        note = (str(notes).strip() or None) if notes else None
        url = (str(upass_url).strip() or None) if upass_url else None
        if flag is not None:
            uni["upass"] = {"value": flag, "source": note or "From the data workbook.",
                            "source_url": url, "as_of": None, "verified": bool(url) and bool(note)}
            upass_changes += 1
        elif note:
            # Left blank on purpose — keep the reasoning rather than dropping it.
            uni["upass"] = {"value": None, "source": note, "source_url": url,
                            "as_of": None, "verified": False}
            upass_changes += 1
        if prov_note:
            uni["tuition_note"] = str(prov_note).strip()
            notes_changes += 1

    print(f"{changes} offering row(s) filled, {upass_changes} university U-Pass value(s) set, "
          f"{notes_changes} tuition note(s) recorded.")
    if unsourced:
        print(f"{unsourced} field(s) came without a source_url and checked_on date — imported, "
              "but left unverified so validate_data.py still lists them.")
    if unknown:
        print(f"{len(unknown)} row(s) had a key not in offerings.json: {unknown[:5]}")

    if not args.write:
        print("\nDry run. Re-run with --write to save.")
        return 0

    offerings_path.write_text(json.dumps(off, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    unis_path.write_text(json.dumps(unis, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\nWritten. Now run: python validate_data.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
