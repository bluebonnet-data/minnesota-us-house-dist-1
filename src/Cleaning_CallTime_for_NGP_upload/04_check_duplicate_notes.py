# =============================================================================
# 04_check_duplicate_notes.py
#
# PURPOSE:
#   Before uploading call notes from CallTime into NGP VAN, check whether any
#   of those notes are already present in NGP. This matters because NGP's bulk
#   note upload APPENDS rather than replaces — running the same upload twice
#   would silently post every note twice on each contact's record.
#
#   This script compares the notes we plan to upload against notes already in
#   NGP and identifies any exact duplicates (same person AND same note text).
#
# CONTEXT FOR NEW READERS:
#   This script is step 4 in a four-step pipeline:
#     01_match_calltime_to_ngp.py   — matches CallTime contacts to NGP by VANID
#     02_condense_call_notes.py     — collapses to one row per person
#     03_format_ngp_upload.py       — formats for NGP bulk import
#     04_check_duplicate_notes.py   — (this script) checks for duplicates
#
#   VANID is NGP's unique integer identifier for a contact. It is the bridge
#   between the two systems and is the key we use to match people here.
#
# INPUTS:
#   Data/ngp_upload_ready.csv          — the notes we plan to upload, produced
#                                        by 03_format_ngp_upload.py
#   Raw Data/ngp_notes_export_*.csv    — a manual export of notes already in
#                                        NGP; this file must be exported from
#                                        NGP before running this script
#                                        (see Section 2 for format details)
#
# OUTPUT:
#   Prints a summary of duplicates found to the terminal. The code to save a
#   CSV of identified duplicates is written below but left commented out
#   (see Section 4) until a permanent output path is decided.
#
# NOTE ON SCRIPT STRUCTURE:
#   This script may need to be split into two scripts in the future because
#   there is a manual human step in the middle of it:
#     Script A — runs Section 1: loads the planned upload and outputs the
#                VANID list so a human can pull the matching notes from NGP
#                (either by manual export from the NGP UI or via the API)
#     [human step] — export or retrieve notes from NGP for those VANIDs
#     Script B — runs Sections 2–4: loads the NGP notes export and checks
#                for duplicates
#   For now, both halves are kept in one file for simplicity while the
#   workflow is still being figured out.
#
# DUPLICATE DEFINITION:
#   A planned note is a duplicate if NGP already has a note for the same VANID
#   with identical text (exact string match after stripping leading/trailing
#   whitespace from both sides).
# =============================================================================

import pandas as pd

from config import OUTPUT_DIR, RAW_DATA_DIR

# ---------------------------------------------------------------------------
# Configuration — update these paths before running
# ---------------------------------------------------------------------------

# The planned upload file produced by 03_format_ngp_upload.py
UPLOAD_FILE = OUTPUT_DIR / "ngp_upload_ready.csv"

# The manually exported NGP notes file. This must be pulled from NGP before
# running this script. The glob pattern below picks the most recent file
# matching that name pattern in the Raw Data folder.
NGP_NOTES_GLOB = "ngp_notes_export_*.csv"

# ---------------------------------------------------------------------------
# Column name configuration for the NGP notes export.
#
# NGP's notes export format may vary depending on how it was pulled (UI export,
# API, custom report). If the column names in the export differ from what is
# listed here, update these constants rather than changing code throughout
# the script. The two columns we need are the VANID and the note body.
# ---------------------------------------------------------------------------
NGP_COL_VANID    = "VANID"     # TODO: confirm exact column name in the NGP export
NGP_COL_NOTETEXT = "NoteText"  # TODO: confirm exact column name in the NGP export


# ===========================================================================
# SECTION 1: Load the planned upload and extract unique VANIDs
# ===========================================================================
# This is the file we are about to import into NGP — one row per contact,
# containing the full combined note string we want to post to their record.
#
# We extract the list of unique VANIDs from this file because that list is
# what we need in order to pull the right notes out of NGP for comparison.
# If we pulled ALL notes from NGP it would be a much larger export than
# necessary; scoping it to just these VANIDs keeps things manageable.
#
# HOW TO USE THIS LIST:
#   Two options depending on access:
#     (a) Manual export — paste or upload the VANID list into NGP's "My List"
#         tool, then export notes for that list to a CSV file.
#     (b) API — pass the VANID list to the NGP VAN API notes endpoint to
#         retrieve existing notes programmatically.
#   Either way, the resulting notes file is what Section 2 loads.

print("Loading planned upload...")
upload = pd.read_csv(UPLOAD_FILE)
print(f"  {len(upload)} notes planned for upload across {upload['VANID'].nunique()} contacts")

# Extract the unique VANIDs. We cast to int to drop any decimal places that
# pandas adds when reading integer-like values from CSV (e.g., 145647880.0
# becomes 145647880), since NGP expects clean integers.
unique_vanids = sorted(upload["VANID"].dropna().astype(int).unique().tolist())
print(f"  {len(unique_vanids)} unique VANIDs — use this list to scope the NGP notes export")

# Print the VANID list to the terminal so it can be copied directly into NGP
# or passed to the API without needing to open any file.
print(f"  VANIDs: {unique_vanids}")

# Export the VANID list to a CSV so it can be uploaded to NGP or passed to
# the API as a file rather than copy-pasted from the terminal. Each VANID
# is on its own row under a "VANID" header. The output path is left as a
# placeholder until we decide where this script's outputs should live.
# pd.DataFrame({"VANID": unique_vanids}).to_csv("export_directory/vanids_to_pull.csv", index=False)


# ===========================================================================
# SECTION 2: Load the existing NGP notes export
# ===========================================================================
# This file must be exported manually from NGP before running this script.
# It represents the notes that are already on contacts' records in NGP — the
# baseline we compare against to detect duplicates.
#
# FORMAT NOTE:
#   We expect a standard CSV (comma-delimited, UTF-8). However, NGP exports
#   can vary — some are tab-delimited or encoded as UTF-16 LE (the same
#   encoding as the NGP full contact export). If the file loads with garbled
#   text or a parsing error, try adding sep='\t' or encoding='utf-16' to
#   the read_csv call below.
#
# COLUMN NOTE:
#   We only need two columns from this file: the VANID and the note text.
#   If NGP uses different column names, update NGP_COL_VANID and
#   NGP_COL_NOTETEXT in the configuration block above.

print("\nLoading existing NGP notes export...")
notes_files = sorted(RAW_DATA_DIR.glob(NGP_NOTES_GLOB))

if not notes_files:
    # If no export file is found, we cannot check for duplicates. The script
    # stops here rather than silently skipping the check, because proceeding
    # without the baseline would defeat the purpose of running this script.
    raise FileNotFoundError(
        f"No NGP notes export file found matching: {NGP_NOTES_GLOB}\n"
        "Export notes from NGP manually and place the file in the Raw Data folder."
    )

# Use the most recent matching file (sorted alphabetically — works when
# file names contain a date in YYYYMMDD format)
notes_file = notes_files[-1]
print(f"  Using: {notes_file.name}")

ngp_notes = pd.read_csv(notes_file)
print(f"  {len(ngp_notes)} existing notes loaded from NGP")

# Confirm the expected columns are present before proceeding. A clear error
# here is much easier to debug than a silent KeyError or wrong-column merge.
for col in [NGP_COL_VANID, NGP_COL_NOTETEXT]:
    if col not in ngp_notes.columns:
        raise KeyError(
            f"Expected column '{col}' not found in {notes_file.name}.\n"
            f"Columns present: {list(ngp_notes.columns)}\n"
            "Update the NGP_COL_* constants at the top of this script to match."
        )

# Keep only the columns we need; rename to internal names used throughout
# the rest of this script so downstream code doesn't depend on NGP's column
# naming conventions.
ngp_notes = ngp_notes[[NGP_COL_VANID, NGP_COL_NOTETEXT]].rename(columns={
    NGP_COL_VANID:    "vanid_existing",
    NGP_COL_NOTETEXT: "note_existing",
})

# Drop rows where the note body OR the VANID is null — both are required for
# a meaningful comparison. Dropping null VANIDs here also prevents a type
# problem: if any VANID is null, pandas reads the whole column as float64,
# which would make astype(str) produce "145647880.0" instead of "145647880"
# and silently break every lookup against the upload file.
ngp_notes = ngp_notes.dropna(subset=["vanid_existing", "note_existing"])
print(f"  {len(ngp_notes)} existing notes after dropping nulls")


# ===========================================================================
# SECTION 3: Identify duplicates
# ===========================================================================
# A note in the planned upload is a duplicate if NGP already has a note for
# the same VANID with identical text. We strip leading/trailing whitespace
# from both sides before comparing, but otherwise require an exact match —
# no case-folding, no punctuation normalization.
#
# Implementation: we build a set of (VANID, note_text) tuples from the
# existing NGP notes, then check each planned row against that set. Set
# lookup is O(1), so this scales even for large exports.

# Guard: every row in the upload should have a VANID — script 03 filters to
# matched contacts only. But if a null VANID somehow slipped through, the
# float->int conversion in the lookup below would raise a cryptic ValueError.
# We catch it here with a clear message before doing any comparison.
rows_missing_vanid = upload["VANID"].isna().sum()
if rows_missing_vanid > 0:
    raise ValueError(
        f"{rows_missing_vanid} row(s) in the upload file have a null VANID. "
        "All rows must have a VANID before running the duplicate check. "
        "Re-run 03_format_ngp_upload.py and verify its output before continuing."
    )

print("\nChecking for duplicates...")

# Build the set of (VANID, note_text) pairs already in NGP.
# VANIDs are normalized to plain integer strings (e.g., "145647880") on both
# sides. We cast through float first to handle cases where the CSV stored the
# VANID as "145647880.0", then through int to drop the decimal, then to str.
# This ensures the two sides always compare the same string representation
# regardless of how each file happened to encode the VANID column.
existing_pairs = set(
    zip(
        ngp_notes["vanid_existing"].apply(lambda x: str(int(float(x)))),
        ngp_notes["note_existing"].str.strip(),
    )
)

# For each planned note, check whether that (VANID, text) pair is in the set.
# Same float->int->str normalization applied to the upload side for consistency.
upload["is_duplicate"] = upload.apply(
    lambda row: (
        str(int(float(row["VANID"]))),
        str(row["NoteText"]).strip(),
    ) in existing_pairs,
    axis=1,
)

duplicates  = upload[upload["is_duplicate"]].copy()
clean       = upload[~upload["is_duplicate"]].copy()

print(f"  Duplicates found:    {len(duplicates)}")
print(f"  Non-duplicate notes: {len(clean)}")


# ===========================================================================
# SECTION 4: Report results
# ===========================================================================
# Print each duplicate to the terminal so it can be reviewed immediately.
# The code to save a CSV of duplicates is written below but commented out
# until a permanent output directory is established.

if len(duplicates) == 0:
    print("\nNo duplicates found. The planned upload is safe to import into NGP.")
else:
    print(f"\n{len(duplicates)} duplicate note(s) identified:")
    for _, row in duplicates.iterrows():
        # Truncate long notes in the terminal preview for readability
        note_preview = str(row["NoteText"])[:100]
        if len(str(row["NoteText"])) > 100:
            note_preview += "..."
        print(f"  VANID {row['VANID']} — {row['ContactName']}")
        print(f"    Note: {note_preview}")

    # -----------------------------------------------------------------------
    # Save the identified duplicates to a CSV for review.
    # The output path is left as a placeholder until we decide where this
    # script will live and where its outputs should go.
    # -----------------------------------------------------------------------

    # duplicates.to_csv("export_directory/identified_duplicate_notes.csv", index=False, encoding="utf-8")


# ===========================================================================
# SECTION 5: Export non-duplicate notes for upload to NGP
# ===========================================================================
# The clean DataFrame contains only the notes that do not already exist in
# NGP — these are safe to upload without creating duplicates.
#
# We drop the is_duplicate column before saving because it is an internal
# working column added by this script and is not part of the NGP upload
# schema. All other columns are preserved exactly as they appear in the
# input file (ngp_upload_ready.csv, produced by 03_format_ngp_upload.py).
#
# OUTPUT FORMAT:
#   Matches the output of 03_format_ngp_upload.py:
#     - Standard CSV (comma-delimited, UTF-8)
#     - Columns: VANID, ContactName, DateEntered, EnteredBy, NoteCategory,
#                NoteTags, IsPinned, NoteText, Suppressions
#     - No row index written to file (index=False)
#   This file can be imported directly into NGP using the same bulk note
#   import process as ngp_upload_ready.csv.

print("\nExporting non-duplicate notes for NGP upload...")

clean_export = clean.drop(columns=["is_duplicate"])

clean_export.to_csv(
    OUTPUT_DIR / "ngp_upload_deduped.csv",
    index=False,
    encoding="utf-8",
)

print(f"  {len(clean_export)} rows written to Data/ngp_upload_deduped.csv")
