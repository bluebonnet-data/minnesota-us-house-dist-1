# CallTime → NGP VAN: Call Notes Pipeline

This folder contains three Python scripts that take a CallTime phone-banking export and produce a file ready for bulk upload into NGP VAN. Run them in order: 01, 02, 03.

---

## Overview

CallTime and NGP VAN maintain separate contact records. There are instances where they overlap, but it seems like the campaign generally maintains separate lists.
CallTime identifies contacts by a `Contact ID`; NGP uses a `VANID`. To upload call notes into NGP, every contact needs a VANID. This pipeline matches the two systems using a three-level strategy (existing ID → phone → name+state), condenses each person's calls into a single note, and formats the result for NGP's bulk note import.
The name+state matching criteria are probably too permissive, allowing CallTime people to match to the incorrect person in NGP.  Right now, it's probably not necessary to identify everyone at the cost of false positives.

These files are an intermediate step between exporting and importing. I have not yet found a way to automate NGP or CallTime uploads fully, but this does help standardize notes and call outcomes so they are easier to upload to NGP.

Importantly, this does NOT go the other way. We need to update CallTime contacts with donations logged from NGP.

## Raw Data

We should avoid putting PII on Github, so I'm adding an explanation of the output required. I did not update the variable names, so exported data from NGP should work.
Raw data fields to export from NGP: `VANID`, `Last`, `First`, `State/Province`, `Cell Phone`, `HomePhone`, `Preferred Phone`. Optional for now but used: `NoCall` (suppression flag)
Raw data fields to export from CallTime: export the full call log

```
I've started with a few raw data files. I exported these from NGP using the universe of people in the campaign's database and a few subsets of the CallTime logs.
Raw Data/call_log_export_*.csv          (CallTime export)
Raw Data/ngp_full_export_*.txt          (NGP full export, UTF-16 LE)
        │
        ▼
01_match_calltime_to_ngp.py
        │
        ▼  Data/call_log_with_vanid.csv
        │
        ▼
02_condense_call_notes.py
        │
        ▼  Data/call_notes_condensed.csv
        │
        ▼
03_format_ngp_upload.py
        │
        ▼  Data/ngp_upload_ready.csv       ← upload this to NGP
```

---

## Requirements

- Python
- Packages: `pandas`, `numpy` (both included in Anaconda base)

---

## Running the Scripts

Each script prints a progress summary and validation counts to the console. Review the console output before uploading to NGP — the validation section will flag any rows missing a VANID or NoteText.

---

## Script Details

### 01 — Match CallTime to NGP (`01_match_calltime_to_ngp.py`)

**What it does:** Assigns a VANID to every row in the CallTime call log.

**Matching strategy (in priority order):**

| Priority | Method | Key |
|---|---|---|
| 1 | Existing ID | `Contact NGP ID` already in CallTime |
| 2 | Phone (Cell) | Phone + last name + first initial |
| 3 | Phone (Home) | Phone + last name + first initial |
| 4 | Phone (Preferred) | Phone + last name + first initial |
| 5 | Name + state | Last name + full first name + state (from area code) |
| 6 | Unmatched | No VANID assigned |

Phone numbers are normalized to 10-digit strings before comparison. CallTime exports 11-digit floats with US country code (e.g. `18319154123.0` → `8319154123`); NGP exports 10-digit floats (e.g. `8319154123.0`).

State is inferred from the first 3 digits of the CallTime phone number using a built-in US area code → state crosswalk. Name+state matching requires **full first name** (not just the initial) because NGP has ~165K records and initial-only matching produced a 30% false-positive rate in testing.

Ambiguous matches (2+ NGP records share the same key) are flagged in `match_conflict` but never assigned — the script does not guess.

**Input files** (update these paths at the top of the script for new exports):
- `Raw Data/call_log_export_20260528.csv` — CallTime export (`CALLTIME_IN`)
- `Raw Data/ngp_full_export_20260528.txt` — NGP full export (`NGP_IN`)

**Output:** `Data/call_log_with_vanid.csv` — original call log plus these added columns:

| Column | Description |
|---|---|
| `vanid_assigned` | The matched VANID (blank if unmatched) |
| `match_method` | How the VANID was found: `existing`, `phone_cell`, `phone_home`, `phone_preferred`, `name_state`, or `unmatched` |
| `match_conflict` | `True` if any matching method found 2+ NGP records (ambiguous) |
| `no_call` | `1` if the contact's NGP record has the NoCall flag set; blank if unmatched |
| `vanid_cell_L3` | VANID from cell phone + last + initial lookup (for auditing) |
| `vanid_home_L3` | VANID from home phone + last + initial lookup (for auditing) |
| `vanid_preferred_L3` | VANID from preferred phone + last + initial lookup (for auditing) |
| `vanid_name_state` | VANID from name+state lookup (for auditing) |
| `name_state_count` | Number of NGP records that matched the name+state key (0 = no match, 1 = unique, 2+ = ambiguous) |
| `name_state_conflict` | `True` if 2+ NGP records share the same name+state combination |

---

### 02 — Condense Call Notes (`02_condense_call_notes.py`)

**What it does:** Collapses the call log to one row per person, combining all their calls into a single `Notes` string.

**Note format** (each call, joined by `; `):
1. `Call Date: M/D/YYYY H:MM AM/PM` — always included
2. Call outcome (e.g. `Connected`, `Voicemail`, `No Answer`)
3. `Contact phone is bad` — only when flagged
4. Contribution/commitment fields (e.g. `Pledge Amount: $100`) — only when non-empty
5. Free-text note from the caller — only when non-empty

If a person was called more than once, each call's note is separated by ` | `.

**Example (two calls):**
```
Call Date: 5/27/2026 4:17 PM; Voicemail | Call Date: 5/28/2026 10:03 AM; Connected; Contribution Ask: Asked; This is a good prospect
```

**Input:** `Data/call_log_with_vanid.csv` (output of script 01)

**Output:** `Data/call_notes_condensed.csv` — one row per CallTime contact:

| Column | Description |
|---|---|
| `Contact Name` | Name as stored in CallTime |
| `Contact ID` | CallTime's internal contact identifier |
| `VANID` | Matched NGP VANID (blank if unmatched) |
| `Contact Phone` | Phone number on file in CallTime |
| `Notes` | Combined note string for all calls to this person |

---

### 03 — Format for NGP Upload (`03_format_ngp_upload.py`)

**What it does:** Takes the condensed notes and formats them for NGP VAN's bulk note import. Only contacts with a VANID are included.

**Configuration** (edit at the top of the script before running):
- `ENTERED_BY` — the person uploading the notes; format `"LastName, FirstName"` (default: `"Levinson, W"`)

**Inputs:**
- `Data/call_notes_condensed.csv` — output of script 02
- `Data/call_log_with_vanid.csv` — used to pull the most recent call date per contact and the NoCall flag

**Output:** `Data/ngp_upload_ready.csv` — one row per matched contact, ready for NGP bulk import:

| Column | Value |
|---|---|
| `VANID` | Integer NGP contact ID |
| `ContactName` | Full name from CallTime |
| `DateEntered` | Date of most recent call to this contact (M/D/YYYY) |
| `EnteredBy` | From `ENTERED_BY` constant (e.g. `Levinson, W`) |
| `NoteCategory` | Blank |
| `NoteTags` | Blank |
| `IsPinned` | `No` |
| `NoteText` | Full condensed note string from script 02 |
| `Suppressions` | `Do not call` if NGP's NoCall flag is set; blank otherwise |

> **Important:** NGP bulk note upload **appends** notes — it does not replace existing ones. Each row in the upload file becomes a new note entry on the contact's record.

---

## Updating for a New Call Log Export

When a new CallTime export arrives:
1. Place it in `Raw Data/`
2. Update `CALLTIME_IN` at the top of `01_match_calltime_to_ngp.py`
3. If a new NGP export is also available, update `NGP_IN` in script 01 as well
4. Run all three scripts in order

Scripts 02 and 03 always read from `Data/` (the outputs of earlier scripts), so they do not need path changes unless the NGP export changes.

---

## Data Sources

| File | Format | Description |
|---|---|---|
| `Raw Data/call_log_export_*.csv` | Tab-separated, UTF-8 | CallTime call log export |
| `Raw Data/ngp_full_export_*.txt` | Tab-separated, **UTF-16 LE** | NGP VAN full contact export. Required columns: `VANID`, `Last`, `First`, `State/Province`, at least one of `Cell Phone` / `HomePhone` / `Preferred Phone`. Optional but used: `NoCall` (suppression flag). |
| `Raw Data/StandardText*.txt` | Tab-separated, **UTF-16 LE** | NGP Standard Text export (name + phone + address; used for reference) |

> The NGP files are UTF-16 LE (a common VAN export quirk). Opening them in a standard text editor or Excel without specifying encoding will show garbled characters. The scripts handle this automatically via `encoding='utf-16'`.

---

## Known Limitations / Future Work

### Do Not Call detection

The current pipeline does **not** automatically detect or set DNC (Do Not Call) suppressions from call notes. The `Suppressions` column in `ngp_upload_ready.csv` is intentionally left blank for all rows in this version.

There are two sources of DNC signals that a future version should handle:

1. **Free-text notes** — callers sometimes record explicit requests in the `Note` field (e.g., "Requested no phone calls", "Do not call"). In this export, 3 contacts made such requests. These are uploaded as regular notes so NGP staff can see them, but the suppression is not set automatically.

2. **NGP `NoCall` flag** — script 01 already reads this flag from the NGP export. Currently no contacts in this dataset have it set, but the logic is in place to carry it through to the `no_call` column in `call_log_with_vanid.csv`.

When implementing DNC detection, use keyword matching on the `NoteText` column in script 03 (patterns like `"no phone"`, `"do not call"`, `"requested no"`) and set `Suppressions = "Do not call"` for matching rows. Print a list of affected contacts to the console before saving so they can be reviewed before upload.

Future scripts should also link NGP data back to CallTime. It seems like CallTime does not auto-update contributions.  However, this should probably be in a different folder/sequence.

3. **Duplicate notes** - we should add a check that we're not duplicating notes in the NGP upload. This may require an NGP download to compare a record in NGP to the notes we plan on adding. The code includes the date and time of the call, so it should be straightforward to identify duplicates. 

---

## Troubleshooting

**Low match rate on phone matching** — Check that the NGP export includes `Cell Phone` and `Preferred Phone` columns (not just `HomePhone`). The script reports which phone columns it finds at startup.

**Many name+state mismatches** — Contacts from campaigns outside the main NGP export's geography will have area codes that map to a different state than their NGP address. This is expected for multi-state campaigns; those contacts fall through to unmatched.

**`vanid_assigned` is blank for a contact you expect to match** — Check `name_state_count` (0 means the name simply isn't in NGP; 2+ means there are multiple people with that name in that state and the script correctly refused to guess). Also check whether `Contact NGP ID` is populated in CallTime for that person.
