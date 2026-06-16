# =============================================================================
# 03_format_ngp_upload.py
#
# PURPOSE:
#   Take the condensed call notes produced by 02_condense_call_notes.py and
#   format them for bulk import into NGP VAN. Only contacts with a matched
#   VANID are included — unmatched contacts have no NGP record to attach
#   notes to.
#
# OUTPUT SCHEMA (matches NGP bulk-note import template):
#   VANID         — integer NGP contact identifier
#   ContactName   — full name as stored in CallTime
#   DateEntered   — date of the most recent call to this contact (M/D/YYYY)
#   EnteredBy     — "LastName, FirstName" of the person doing the upload
#   NoteCategory  — left blank (NGP accepts empty)
#   NoteTags      — left blank
#   IsPinned      — "No" for all rows (notes are not pinned by default)
#   NoteText      — the full condensed note string from 02_condense_call_notes.py
#   Suppressions  — "Do not call" if NGP's NoCall flag was set or CallTime
#                   notes indicate a likely DNC request; blank otherwise
#
# HOW NGP PROCESSES THE UPLOAD:
#   Uploading notes APPENDS to existing notes — it does NOT replace them.
#   Each row in this file becomes one new note entry on the contact's record.
#   The DateEntered and EnteredBy fields appear in NGP's note history.
#
# INPUTS:
#   Data/call_notes_condensed.csv      — output of 02_condense_call_notes.py;
#                                        one row per CallTime contact with
#                                        a combined Notes string
#   Data/call_log_with_vanid.csv       — output of 01_match_calltime_to_ngp.py;
#                                        one row per call with Date and no_call
#
# OUTPUT:
#   Data/ngp_upload_ready.csv          — ready for bulk import into NGP VAN
# =============================================================================

import os
import re

import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# Configuration — edit these before running
# ---------------------------------------------------------------------------

ROOT        = r"C:\Users\willl\Documents\bluebonnet 2026"

# Input files
CONDENSED_FILE  = os.path.join(ROOT, "Data", "call_notes_condensed.csv")
CALL_LOG_FILE   = os.path.join(ROOT, "Data", "call_log_with_vanid.csv")

# Output file
OUTPUT_FILE     = os.path.join(ROOT, "Data", "ngp_upload_ready.csv")

# Who is doing this upload — appears in NGP's note history
ENTERED_BY = "Levinson, W"

# Phrases in CallTime notes that likely mean the contact asked not to be called.
# These matches are printed for human review before the upload file is saved.
DNC_NOTE_PATTERNS = [
    r"\bdo not call\b",
    r"\bdon'?t call\b",
    r"\bdo not phone\b",
    r"\bdon'?t phone\b",
    r"\bno phone\b",
    r"\bno phone calls?\b",
    r"\bno more calls?\b",
    r"\brequested no calls?\b",
    r"\bremove\s+(me|them|him|her)?\s*(from\s+)?(the\s+)?call(ing)?\s+list\b",
    r"\btake\s+(me|them|him|her)?\s*(off|out of)\s+(the\s+)?call(ing)?\s+list\b",
    r"\bstop call(ing)?\b",
]

DNC_NOTE_RE = re.compile("|".join(DNC_NOTE_PATTERNS), flags=re.IGNORECASE)

# ===========================================================================
# SECTION 1: Load condensed notes
# ===========================================================================
# This file has one row per CallTime contact. The Notes column combines all
# calls for that person into a single string (calls separated by " | ").
# Only contacts with a VANID (matched to NGP) can be uploaded.

print("Loading condensed call notes...")
condensed = pd.read_csv(CONDENSED_FILE)
print(f"  {len(condensed)} total contacts in condensed file")

# Filter to contacts that were successfully matched to an NGP VANID.
# Unmatched contacts don't exist (or can't be located) in NGP and can't
# receive notes through the bulk upload.
matched = condensed[condensed["VANID"].notna()].copy()
print(f"  {len(matched)} contacts have a VANID -> eligible for upload")
print(f"  {condensed['VANID'].isna().sum()} contacts have no VANID -> excluded")

# ===========================================================================
# SECTION 2: Pull the most recent call date per contact
# ===========================================================================
# The NGP upload requires a DateEntered for each note. We use the date of the
# most recent call to that contact from the raw call log. If a person was
# called multiple times, this is the most recent date.
#
# The call log has one row per call; we group by Contact ID and take the max.

# We go back to the full call log (rather than using the condensed file) because
# 02_condense_call_notes.py drops the Date column during aggregation. The call
# log has one row per call, so we group by Contact ID and take the latest date.
print("\nLoading call log to get per-contact dates...")
call_log = pd.read_csv(CALL_LOG_FILE, usecols=["Contact ID", "Date", "no_call"])

# Parse the datetime string ("2026-05-27 16:17:43") to a proper datetime
# so that max() gives the latest call rather than the lexicographically last.
call_log["Date"] = pd.to_datetime(call_log["Date"])

# Build a lookup: Contact ID -> most recent call date
# Also capture whether ANY call to this contact has no_call == 1 (NGP's
# DoNotCall flag). If so, we include a "Do not call" suppression in the upload.
date_lookup = (
    call_log
    .groupby("Contact ID")
    .agg(
        latest_date = ("Date",    "max"),   # most recent call date
        has_nocall  = ("no_call", lambda x: (x == 1).any()),  # True if flagged
    )
    .reset_index()
)

# ===========================================================================
# SECTION 3: Merge date and suppression info onto matched contacts
# ===========================================================================

print("Merging dates and NoCall flags onto matched contacts...")
matched = matched.merge(date_lookup, on="Contact ID", how="left")

# Warn if any matched contact has no corresponding call-log entry (shouldn't
# happen, but good to surface).
missing_dates = matched["latest_date"].isna().sum()
if missing_dates > 0:
    print(f"  WARNING: {missing_dates} matched contact(s) have no date in call log")

# ===========================================================================
# SECTION 4: Format the date as NGP expects it
# ===========================================================================
# NGP's date format is M/D/YYYY with no leading zeros (e.g., "5/27/2026").
# We format explicitly using month/day/year integers to avoid OS-specific
# strftime zero-padding behavior.

def format_date(dt):
    """Convert a datetime to M/D/YYYY string (no zero padding)."""
    if pd.isna(dt):
        return ""
    return f"{dt.month}/{dt.day}/{dt.year}"

matched["DateEntered"] = matched["latest_date"].apply(format_date)

# ===========================================================================
# SECTION 5: Build the Suppressions column
# ===========================================================================
# "Do not call" is NGP's standard suppression string. We apply it if either:
#   1. The contact's NGP record already had NoCall set, or
#   2. The CallTime note text includes a likely do-not-call request.

def note_requests_dnc(note_text):
    """Return True when a CallTime note contains a likely DNC request."""
    if pd.isna(note_text):
        return False
    return bool(DNC_NOTE_RE.search(str(note_text)))


def is_nocall_flagged(value):
    """Return True for common NGP export values that mean NoCall is set."""
    if pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return value == 1 or value is True


matched["dnc_from_ngp"] = matched["has_nocall"].apply(is_nocall_flagged)
matched["dnc_from_notes"] = matched["Notes"].apply(note_requests_dnc)
matched["Suppressions"] = np.where(
    matched["dnc_from_ngp"] | matched["dnc_from_notes"],
    "Do not call",
    np.nan,
)

n_ngp_suppressed = matched["dnc_from_ngp"].sum()
n_note_suppressed = matched["dnc_from_notes"].sum()
n_suppressed = matched["Suppressions"].notna().sum()

print(f"  {n_ngp_suppressed} contact(s) already flagged NoCall in NGP")
print(f"  {n_note_suppressed} contact(s) flagged from CallTime note text")
print(f"  {n_suppressed} total contact(s) will receive 'Do not call' suppression")

if n_note_suppressed > 0:
    print("\nReview contacts flagged from CallTime notes before upload:")
    note_flagged = matched[matched["dnc_from_notes"]].copy()
    for _, row in note_flagged.iterrows():
        preview = str(row["Notes"])[:120]
        if len(str(row["Notes"])) > 120:
            preview += "..."
        print(f"  VANID={int(row['VANID'])}  {row['Contact Name']}")
        print(f"    Note: {preview}")

# ===========================================================================
# SECTION 6: Assemble the final upload DataFrame
# ===========================================================================
# Columns must match the NGP bulk-note import template exactly. Column names
# are case-sensitive in some NGP import wizards, so we use the exact names
# from the test template file.

# VANID: stored as a float (e.g., 145647880.0) in the CSV; NGP expects an
# integer with no decimal point. Convert via int() after dropping any NaN
# (already filtered above).
matched["VANID_int"] = matched["VANID"].astype(int)

upload = pd.DataFrame({
    "VANID":        matched["VANID_int"],
    "ContactName":  matched["Contact Name"],
    "DateEntered":  matched["DateEntered"],
    "EnteredBy":    ENTERED_BY,           # same for every row
    "NoteCategory": np.nan,               # blank — no category applied
    "NoteTags":     np.nan,               # blank — no tags applied
    "IsPinned":     "No",                 # notes are not pinned by default
    "NoteText":     matched["Notes"],
    "Suppressions": matched["Suppressions"],
})

# Reset the index so rows are numbered 0, 1, 2, ... in the output file
upload = upload.reset_index(drop=True)

# ===========================================================================
# SECTION 7: Validation checks before saving
# ===========================================================================

print("\nValidation checks:")

# Every row must have a VANID
missing_vanid = upload["VANID"].isna().sum()
print(f"  Rows missing VANID:       {missing_vanid}  (should be 0)")

# Every row must have a note to upload
empty_notes = (upload["NoteText"].isna() | (upload["NoteText"].str.strip() == "")).sum()
print(f"  Rows with empty NoteText: {empty_notes}  (should be 0)")

# Every row must have a date
missing_date = (upload["DateEntered"] == "").sum()
print(f"  Rows missing DateEntered: {missing_date}  (should be 0)")

# Spot-check: show a few sample rows so it's easy to verify the format
print("\nSample rows (first 5):")
for _, row in upload.head(5).iterrows():
    preview = str(row["NoteText"])[:80] + ("..." if len(str(row["NoteText"])) > 80 else "")
    print(f"  VANID={row['VANID']}  {row['ContactName']}")
    print(f"    Date: {row['DateEntered']}  EnteredBy: {row['EnteredBy']}")
    print(f"    Note: {preview}")
    if pd.notna(row["Suppressions"]):
        print(f"    Suppression: {row['Suppressions']}")
    print()

# ===========================================================================
# SECTION 8: Save output
# ===========================================================================

upload.to_csv(OUTPUT_FILE, index=False)
print(f"Output saved to: {OUTPUT_FILE}")
print(f"  {len(upload)} rows ready for NGP bulk note import")
