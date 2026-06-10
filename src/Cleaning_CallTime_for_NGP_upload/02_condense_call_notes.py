# =============================================================================
# 02_condense_call_notes.py
#
# PURPOSE:
#   Condense the CallTime call log to one row per person. Each person's calls
#   are combined into a single "notes" column so the output can be reviewed
#   and later used to bulk-upload notes to NGP VAN.
#
# OUTPUT COLUMNS:
#   Contact Name  — as stored in CallTime
#   Contact ID    — CallTime's internal person identifier
#   VANID         — matched NGP VANID from 01_match_calltime_to_ngp.py (NaN if
#                   unmatched)
#   Contact Phone — the phone number on file in CallTime
#   Notes         — one combined note string per person (see format below)
#
# NOTES COLUMN FORMAT:
#   Each call produces one note entry with up to five parts, joined by "; ":
#     1. Call date and time  (always first; e.g. "Call Date: 5/27/2026 4:17 PM")
#     2. Call outcome  (always included)
#     3. "Contact phone is bad"  (only when Contact Phone is Bad == 1)
#     4. Contribution / commitment fields, formatted as "Field Name: value"
#        (only included when the field is non-empty):
#          Contribution Ask, Contribution Ask Result, Contribution Ask Amount,
#          Pledged, Pledge Amount, Commitment Asks & Results, Commitments
#     5. Free-text note from the Note column  (only when non-empty)
#
#   If a person was called more than once, each call's note entry is separated
#   by " | " so all calls are visible in a single cell.
#
#   Example (two calls for one person):
#     "Call Date: 5/27/2026 4:17 PM; Voicemail | Call Date: 5/28/2026 10:03 AM; Connected; Contribution Ask: Asked; This is a good prospect"
#
# INPUT:
#   Data/call_log_with_vanid.csv  — output of 01_match_calltime_to_ngp.py,
#                                   which adds vanid_assigned to the call log
#
# OUTPUT:
#   Data/call_notes_condensed.csv
# =============================================================================

import pandas as pd
import numpy as np

from config import OUTPUT_DIR

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
INPUT_FILE = OUTPUT_DIR / "call_log_with_vanid.csv"
OUTPUT_FILE = OUTPUT_DIR / "call_notes_condensed.csv"

# ---------------------------------------------------------------------------
# Contribution / commitment columns to include when non-empty.
# The display label is used in the note string ("Label: value").
# ---------------------------------------------------------------------------
CONTRIB_COLS = [
    ("Contribution Ask",            "Contribution Ask"),
    ("Contribution Ask Result",     "Contribution Ask Result"),
    ("Contribution Ask Amount",     "Contribution Ask Amount"),
    ("Pledged",                     "Pledged"),
    ("Pledge Amount",               "Pledge Amount"),
    ("Commitment Asks & Results",   "Commitment Asks & Results"),
    ("Commitments",                 "Commitments"),
]

# ===========================================================================
# SECTION 1: Load data
# ===========================================================================

print("Loading matched call log...")
ct = pd.read_csv(INPUT_FILE)
print(f"  {len(ct)} rows ({ct['Contact ID'].nunique()} unique contacts)")

# ===========================================================================
# SECTION 2: Build one note string per call row
# ===========================================================================
# Each row becomes a short note string. Parts are assembled in order and
# joined with "; " — empty parts are skipped so we never get stray semicolons.

def format_call_datetime(raw):
    """
    Convert a CallTime datetime string ("2026-05-27 16:17:43") to a human-
    readable format for the note: "5/27/2026 4:17 PM".
    Returns an empty string if the value is missing or unparseable.
    """
    try:
        dt = pd.to_datetime(raw)
        # Build M/D/YYYY with no leading zeros, then append 12-hour time
        hour   = dt.hour % 12 or 12          # convert 0 -> 12, 13 -> 1, etc.
        minute = f"{dt.minute:02d}"
        ampm   = "AM" if dt.hour < 12 else "PM"
        return f"{dt.month}/{dt.day}/{dt.year} {hour}:{minute} {ampm}"
    except Exception:
        return ""


def build_call_note(row):
    """Return a single note string for one call row."""
    parts = []

    # 1. Call date and time — always first so it's easy to find in NGP
    call_dt = format_call_datetime(row.get("Date"))
    if call_dt:
        parts.append(f"Call Date: {call_dt}")

    # 2. Outcome — always present
    if pd.notna(row.get("Outcome")):
        parts.append(str(row["Outcome"]).strip())

    # 3. Bad phone flag — include the literal string when flagged
    if row.get("Contact Phone is Bad") == 1:
        parts.append("Contact phone is bad")

    # 4. Contribution / commitment fields — only when populated
    for col, label in CONTRIB_COLS:
        if col in row.index and pd.notna(row[col]) and str(row[col]).strip() != "":
            parts.append(f"{label}: {str(row[col]).strip()}")

    # 5. Free-text note — only when populated
    if pd.notna(row.get("Note")) and str(row["Note"]).strip() != "":
        parts.append(str(row["Note"]).strip())

    return "; ".join(parts)

ct["call_note"] = ct.apply(build_call_note, axis=1)

# ===========================================================================
# SECTION 3: Condense to one row per person
# ===========================================================================
# Group by Contact ID (CallTime's unique person identifier). For people with
# multiple calls, join each call's note with " | " so all calls are visible.
#
# VANID: a person may have multiple calls, all with the same matched VANID.
# We take the first non-null value; if all calls are unmatched, VANID is NaN.

def first_non_null(series):
    """Return the first non-NaN value in a Series, or NaN if all are NaN.

    We can't use pandas' built-in "first" aggregation here because it returns
    the first value regardless of whether it is NaN. A contact called multiple
    times may only have a VANID on some of those rows (e.g., if the match was
    ambiguous on one call but clean on another). We want the matched VANID,
    not whatever happened to be first in the file.
    """
    valid = series.dropna()
    return valid.iloc[0] if len(valid) > 0 else np.nan

condensed = (
    ct.groupby("Contact ID", sort=False)
    .agg(
        contact_name  = ("Contact Name",    "first"),
        contact_phone = ("Contact Phone",   "first"),
        vanid         = ("vanid_assigned",  first_non_null),
        notes         = ("call_note",       lambda x: " | ".join(x)),
    )
    .reset_index()
)

# Rename columns to match the requested output schema
condensed = condensed.rename(columns={
    "contact_name":  "Contact Name",
    "Contact ID":    "Contact ID",
    "vanid":         "VANID",
    "contact_phone": "Contact Phone",
    "notes":         "Notes",
})

# Put columns in logical reading order
condensed = condensed[["Contact Name", "Contact ID", "VANID", "Contact Phone", "Notes"]]

# ===========================================================================
# SECTION 4: Summary and save
# ===========================================================================

print(f"\nCondensed to {len(condensed)} unique contacts")
print(f"  With VANID assigned: {condensed['VANID'].notna().sum()}")
print(f"  Without VANID:       {condensed['VANID'].isna().sum()}")

# Show a few sample rows so it's easy to spot formatting issues
print("\nSample notes (first 5 contacts with a non-empty note or contribution):")
sample = condensed[condensed["Notes"].str.contains(";", na=False)].head(5)
for _, row in sample.iterrows():
    print(f"  {row['Contact Name']}: {row['Notes'][:120]}")

condensed.to_csv(OUTPUT_FILE, index=False)
print(f"\nOutput saved to: {OUTPUT_FILE}")
