# =============================================================================
# 01_match_calltime_to_ngp.py
#
# PURPOSE:
#   Assign a VANID to every row in the CallTime call log export by matching
#   against the NGP VAN full export. We want a VANID on every row so that
#   note uploads to NGP can use the canonical contact identifier rather than
#   relying on NGP's own fuzzy-matching at import time.
#
# MATCHING STRATEGY (in priority order):
#   Step 1 — "existing":   use Contact NGP ID if already populated in CallTime.
#   Step 2 — "phone":      strip leading country code from CallTime's 11-digit
#                          phone; look up in Cell/Home/Preferred Phone fields.
#                          Match requires phone + last name + first initial (L3).
#   Step 3 — "name_state": for contacts not matched by phone, derive state from
#                          the CallTime phone's area code (US area code → state
#                          crosswalk), then match on last name + full first name
#                          + state. Only unique (1-result) matches are kept.
#                          NOTE: full first name is required here (not initial)
#                          because NGP has ~165K records and initial-only matching
#                          produces too many false positives (30% error rate).
#
#   Three match strictness levels (phone-based):
#     Level 1: phone match only
#     Level 2: phone  +  last name
#     Level 3: phone  +  last name  +  first initial   [chosen standard]
#
#   NoCall is carried over from NGP. Records with NoCall = 1 are kept but flagged.
#
# VALIDATION:
#   Rows where Contact NGP ID is already set provide ground truth. We verify
#   that our phone matching finds the same VANID for those rows.
#
# INPUT FILES:
#   Raw Data/call_log_export_20260528.csv
#   Raw Data/ngp_full_export_20260528.txt   (UTF-16 LE, tab-delimited)
#
# OUTPUT:
#   Data/call_log_with_vanid.csv  — call log with added columns:
#       vanid_assigned  : the matched VANID (NaN if unmatched)
#       match_method    : "existing" | "phone_cell" | "phone_home" |
#                         "phone_preferred" | "name_state" | "unmatched"
#       match_conflict  : True if multiple NGP records matched (ambiguous)
#       no_call         : NoCall flag from NGP (1 = contact requested no calls;
#                         NaN if unmatched). Records are KEPT regardless.
# =============================================================================

import pandas as pd
import numpy as np
import os

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------
ROOT        = r"C:\Users\willl\Documents\bluebonnet 2026"
CALLTIME_IN = os.path.join(ROOT, "Raw Data", "call_log_export_20260528.csv")
NGP_IN      = os.path.join(ROOT, "Raw Data", "ngp_full_export_20260528.txt")
OUTPUT_DIR  = os.path.join(ROOT, "Data")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "call_log_with_vanid.csv")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ===========================================================================
# SECTION 1: Load data
# ===========================================================================

print("Loading CallTime call log...")
ct = pd.read_csv(CALLTIME_IN)
print(f"  {len(ct)} rows loaded")

# NGP full export — UTF-16 LE tab-delimited (standard VAN export format).
# This file includes Cell Phone and Preferred Phone in addition to HomePhone,
# along with suppression flags (NoCall, NoEmail, NoMail) and PreferredEmail.
print("\nLoading NGP full export...")
ngp = pd.read_csv(NGP_IN, sep="\t", encoding="utf-16", low_memory=False)
print(f"  {len(ngp):,} rows loaded")

# Report which phone columns are present — the script uses whatever it finds
phone_cols_available = [c for c in ["Cell Phone", "HomePhone", "Preferred Phone"]
                        if c in ngp.columns]
print(f"  Phone columns found: {phone_cols_available}")

# ===========================================================================
# SECTION 2: Clean phone numbers and extract area codes
# ===========================================================================
# CallTime stores phones as 11-digit floats with US country code prefix
#   e.g.  18319154123.0  →  "18319154123"  →  strip leading 1  →  "8319154123"
# NGP stores all phone fields as 10-digit floats (no country code)
#   e.g.  4076945558.0   →  "4076945558"
# We normalize both to 10-digit strings before comparing.

def clean_phone_calltime(phone):
    """Return a 10-digit string from an 11-digit CallTime phone float.
    Returns None for nulls or unexpected formats.
    """
    if pd.isna(phone):
        return None
    s = str(int(phone))
    if len(s) == 11 and s[0] == "1":
        return s[1:]      # drop US country code
    elif len(s) == 10:
        return s
    else:
        return None       # unexpected — don't guess

def clean_phone_ngp(phone):
    """Return a 10-digit string from an NGP phone float.
    All NGP phones in this export are 10 digits, but we handle 11-digit
    entries defensively in case a future export includes them.
    """
    if pd.isna(phone):
        return None
    s = str(int(phone))
    if len(s) == 10:
        return s
    elif len(s) == 11 and s[0] == "1":
        return s[1:]
    else:
        return None

# Clean CallTime phone once; area code is the first 3 digits of the result
ct["phone_clean"] = ct["Contact Phone"].apply(clean_phone_calltime)
ct["area_code"]   = ct["phone_clean"].apply(
    lambda p: p[:3] if pd.notna(p) and len(p) == 10 else None
)

# Clean each NGP phone column and store in a new column with a consistent
# naming convention: phone_clean_<source>
NGP_PHONE_COLS = [
    ("Cell Phone",       "phone_clean_cell"),
    ("HomePhone",        "phone_clean_home"),
    ("Preferred Phone",  "phone_clean_preferred"),
]

for src_col, clean_col in NGP_PHONE_COLS:
    if src_col in ngp.columns:
        ngp[clean_col] = ngp[src_col].apply(clean_phone_ngp)
    else:
        print(f"  WARNING: expected column '{src_col}' not found in NGP file")

# Report coverage per phone field
print("\nNGP phone field coverage:")
for src_col, clean_col in NGP_PHONE_COLS:
    if clean_col in ngp.columns:
        n = ngp[clean_col].notna().sum()
        print(f"  {src_col:<18}: {n:,} records ({100*n/len(ngp):.1f}%)")

# ===========================================================================
# SECTION 2.5: Area code → state crosswalk
# ===========================================================================
# Maps US 3-digit area codes to 2-letter state abbreviations. Used to infer
# the state of a CallTime contact's phone number, which then anchors the
# name-based fallback match in Section 5.5.
#
# Source: NANPA (North American Numbering Plan Administration) assignments.
# Note: area codes can theoretically span state lines for small states that
# share a code, but this is rare. When uncertain, the match will return
# multiple candidates and be flagged as a conflict.

AREA_CODE_TO_STATE = {
    # Alabama
    205: "AL", 251: "AL", 256: "AL", 334: "AL", 938: "AL",
    # Alaska
    907: "AK",
    # Arizona
    480: "AZ", 520: "AZ", 602: "AZ", 623: "AZ", 928: "AZ",
    # Arkansas
    479: "AR", 501: "AR", 870: "AR",
    # California
    209: "CA", 213: "CA", 279: "CA", 310: "CA", 323: "CA", 408: "CA",
    415: "CA", 424: "CA", 442: "CA", 510: "CA", 530: "CA", 559: "CA",
    562: "CA", 619: "CA", 626: "CA", 628: "CA", 650: "CA", 657: "CA",
    661: "CA", 669: "CA", 707: "CA", 714: "CA", 747: "CA", 760: "CA",
    805: "CA", 818: "CA", 820: "CA", 831: "CA", 858: "CA", 909: "CA",
    916: "CA", 925: "CA", 949: "CA", 951: "CA",
    # Colorado
    303: "CO", 719: "CO", 720: "CO", 970: "CO",
    # Connecticut
    203: "CT", 475: "CT", 860: "CT", 959: "CT",
    # Delaware
    302: "DE",
    # DC
    202: "DC",
    # Florida
    239: "FL", 305: "FL", 321: "FL", 352: "FL", 386: "FL", 407: "FL",
    448: "FL", 561: "FL", 689: "FL", 727: "FL", 754: "FL", 772: "FL",
    786: "FL", 813: "FL", 850: "FL", 863: "FL", 904: "FL", 941: "FL",
    954: "FL",
    # Georgia
    229: "GA", 404: "GA", 470: "GA", 478: "GA", 678: "GA", 706: "GA",
    762: "GA", 770: "GA", 912: "GA",
    # Hawaii
    808: "HI",
    # Idaho
    208: "ID", 986: "ID",
    # Illinois
    217: "IL", 224: "IL", 309: "IL", 312: "IL", 331: "IL", 447: "IL",
    464: "IL", 618: "IL", 630: "IL", 708: "IL", 773: "IL", 779: "IL",
    815: "IL", 847: "IL", 872: "IL",
    # Indiana
    219: "IN", 260: "IN", 317: "IN", 463: "IN", 574: "IN", 765: "IN",
    812: "IN", 930: "IN",
    # Iowa
    319: "IA", 515: "IA", 563: "IA", 641: "IA", 712: "IA",
    # Kansas
    316: "KS", 620: "KS", 785: "KS", 913: "KS",
    # Kentucky
    270: "KY", 364: "KY", 502: "KY", 606: "KY", 859: "KY",
    # Louisiana
    225: "LA", 318: "LA", 337: "LA", 504: "LA", 985: "LA",
    # Maine
    207: "ME",
    # Maryland
    240: "MD", 301: "MD", 410: "MD", 443: "MD", 667: "MD",
    # Massachusetts
    339: "MA", 351: "MA", 413: "MA", 508: "MA", 617: "MA", 774: "MA",
    781: "MA", 857: "MA", 978: "MA",
    # Michigan
    231: "MI", 248: "MI", 269: "MI", 313: "MI", 517: "MI", 586: "MI",
    616: "MI", 679: "MI", 734: "MI", 810: "MI", 906: "MI", 947: "MI",
    989: "MI",
    # Minnesota
    218: "MN", 320: "MN", 507: "MN", 612: "MN", 651: "MN", 763: "MN",
    952: "MN",
    # Mississippi
    228: "MS", 601: "MS", 662: "MS", 769: "MS",
    # Missouri
    314: "MO", 417: "MO", 557: "MO", 573: "MO", 636: "MO", 660: "MO",
    816: "MO",
    # Montana
    406: "MT",
    # Nebraska
    308: "NE", 402: "NE", 531: "NE",
    # Nevada
    702: "NV", 725: "NV", 775: "NV",
    # New Hampshire
    603: "NH",
    # New Jersey
    201: "NJ", 551: "NJ", 609: "NJ", 640: "NJ", 732: "NJ", 848: "NJ",
    856: "NJ", 862: "NJ", 908: "NJ", 973: "NJ",
    # New Mexico
    505: "NM", 575: "NM",
    # New York
    212: "NY", 315: "NY", 332: "NY", 347: "NY", 516: "NY", 518: "NY",
    585: "NY", 607: "NY", 631: "NY", 646: "NY", 680: "NY", 716: "NY",
    718: "NY", 838: "NY", 845: "NY", 914: "NY", 917: "NY", 929: "NY",
    934: "NY",
    # North Carolina
    252: "NC", 336: "NC", 704: "NC", 743: "NC", 828: "NC", 910: "NC",
    919: "NC", 980: "NC", 984: "NC",
    # North Dakota
    701: "ND",
    # Ohio
    216: "OH", 220: "OH", 234: "OH", 283: "OH", 330: "OH", 380: "OH",
    419: "OH", 440: "OH", 513: "OH", 567: "OH", 614: "OH", 740: "OH",
    937: "OH",
    # Oklahoma
    405: "OK", 539: "OK", 572: "OK", 580: "OK", 918: "OK",
    # Oregon
    458: "OR", 503: "OR", 541: "OR", 971: "OR",
    # Pennsylvania
    215: "PA", 223: "PA", 267: "PA", 272: "PA", 412: "PA", 445: "PA",
    484: "PA", 570: "PA", 610: "PA", 717: "PA", 724: "PA", 814: "PA",
    835: "PA", 878: "PA",
    # Rhode Island
    401: "RI",
    # South Carolina
    803: "SC", 839: "SC", 843: "SC", 854: "SC", 864: "SC",
    # South Dakota
    605: "SD",
    # Tennessee
    423: "TN", 615: "TN", 629: "TN", 731: "TN", 865: "TN", 901: "TN",
    931: "TN",
    # Texas
    210: "TX", 214: "TX", 254: "TX", 281: "TX", 325: "TX", 346: "TX",
    361: "TX", 409: "TX", 430: "TX", 432: "TX", 469: "TX", 512: "TX",
    682: "TX", 713: "TX", 726: "TX", 737: "TX", 806: "TX", 817: "TX",
    830: "TX", 832: "TX", 903: "TX", 915: "TX", 936: "TX", 940: "TX",
    945: "TX", 956: "TX", 972: "TX", 979: "TX",
    # Utah
    385: "UT", 435: "UT", 801: "UT",
    # Vermont
    802: "VT",
    # Virginia
    276: "VA", 434: "VA", 540: "VA", 571: "VA", 703: "VA", 757: "VA",
    804: "VA",
    # Washington (state)
    206: "WA", 253: "WA", 360: "WA", 425: "WA", 509: "WA", 564: "WA",
    # West Virginia
    304: "WV", 681: "WV",
    # Wisconsin
    262: "WI", 414: "WI", 534: "WI", 608: "WI", 715: "WI", 920: "WI",
    # Wyoming
    307: "WY",
    # Territories
    787: "PR", 939: "PR",   # Puerto Rico
    340: "VI",              # US Virgin Islands
    671: "GU",              # Guam
}

# Map each CallTime row's area code to a state abbreviation
ct["phone_state"] = ct["area_code"].apply(
    lambda ac: AREA_CODE_TO_STATE.get(int(ac)) if pd.notna(ac) else None
)

n_mapped = ct["phone_state"].notna().sum()
print(f"\nCallTime area code -> state: {n_mapped} of {len(ct)} rows mapped "
      f"({100*n_mapped/len(ct):.1f}%)")
print("  State distribution (CallTime):")
print(ct["phone_state"].value_counts().head(10).to_string())

# ===========================================================================
# SECTION 3: Clean and standardize names
# ===========================================================================
# Used for strictness levels 2 and 3. All comparisons are lowercased.
#
# NGP has separate Last/First columns.
# CallTime has a single "Contact Name" field: "First Last" or "First Mid Last".
# We take the first token as first name and the last token as last name.
# This correctly handles most compound last names when CallTime also stores
# only the last token — but if NGP stores a full compound name as Last
# (e.g. "Van Deerlin") the comparison will still fail. Phone-only matching
# is safer for compound names.

ngp["last_clean"]    = ngp["Last"].str.strip().str.lower()
ngp["first_clean"]   = ngp["First"].str.strip().str.lower()
ngp["first_initial"] = ngp["first_clean"].str[0]

# Clean the NGP state field — strip whitespace, uppercase for consistency
# "State/Province" is the primary address state (2-letter abbreviation)
ngp["state_clean"] = ngp["State/Province"].str.strip().str.upper()

def parse_calltime_name(full_name):
    """Split a 'First Last' CallTime name into (first, last, initial).
    Returns a Series for use with apply(..., result_type='expand').
    """
    parts = str(full_name).strip().split()
    if len(parts) >= 2:
        first = parts[0].lower()
        last  = parts[-1].lower()
        return pd.Series({"first_clean": first,
                          "last_clean":  last,
                          "first_initial": first[0]})
    return pd.Series({"first_clean": None, "last_clean": None, "first_initial": None})

ct[["first_clean", "last_clean", "first_initial"]] = (
    ct["Contact Name"].apply(parse_calltime_name)
)

# ===========================================================================
# SECTION 4: Build NGP phone lookup tables
# ===========================================================================
# For each NGP phone column, we build three lookup dicts corresponding to
# the three match strictness levels:
#
#   level 1 key: phone
#   level 2 key: (phone, last_name)
#   level 3 key: (phone, last_name, first_initial)
#
# Each dict maps key → list of VANIDs. A match is unambiguous only when
# exactly one VANID maps to the key.
#
# We store results in a nested dict:
#   LOOKUPS[clean_col][level] = {"all": {key: [vanids]},
#                                "unique": {key: [vanid]}}

def build_lookups(df, phone_col):
    """Build level-1/2/3 lookup dicts for one NGP phone column.

    Returns a dict with keys "L1", "L2", "L3", each containing
    "all" (every match) and "unique" (only unambiguous matches).
    """
    sub = df.dropna(subset=[phone_col])

    def _make(key_cols):
        grouped = sub.groupby(key_cols)["VANID"].apply(list).to_dict()
        unique  = {k: v for k, v in grouped.items() if len(v) == 1}
        return {"all": grouped, "unique": unique}

    return {
        "L1": _make(phone_col),
        # For L2/L3 we need the name columns to be present too
        "L2": _make([phone_col, "last_clean"]),
        "L3": _make([phone_col, "last_clean", "first_initial"]),
    }

print("\nBuilding NGP phone lookup tables...")
LOOKUPS = {}
for src_col, clean_col in NGP_PHONE_COLS:
    if clean_col in ngp.columns:
        LOOKUPS[clean_col] = build_lookups(ngp, clean_col)
        n_unique_L3 = len(LOOKUPS[clean_col]["L3"]["unique"])
        print(f"  {src_col:<18}: {n_unique_L3:,} unambiguous (phone+last+initial) entries")

# ===========================================================================
# SECTION 4.5: Build NGP name + state lookup table
# ===========================================================================
# This lookup is used as a fallback for rows that can't be matched by phone.
# Key: (last_clean, first_clean, state_clean)
# Value: list of VANIDs that share that name+state combination.
#
# We require full first name (not just initial) because NGP has ~165K records
# and first-initial matching produces too many false positives — different
# people who share a last name, state, and first initial are common enough
# to make initial-only matches unreliable.
#
# Only contacts with a state populated are included, since state is the
# anchor that makes this approach more precise than name-only.

print("\nBuilding NGP name+state lookup table...")

ngp_with_state = ngp.dropna(subset=["state_clean"])

# Group by (last, first, state) -> list of VANIDs
name_state_all = (
    ngp_with_state
    .groupby(["last_clean", "first_clean", "state_clean"])["VANID"]
    .apply(list)
    .to_dict()
)

# Separate out the unambiguous (exactly 1 VANID) entries
name_state_unique = {k: v for k, v in name_state_all.items() if len(v) == 1}

print(f"  Total name+state combinations in NGP:  {len(name_state_all):,}")
print(f"  Combinations with exactly 1 VANID:     {len(name_state_unique):,}")
print(f"  Combinations with 2+ VANIDs (ambiguous): "
      f"{len(name_state_all) - len(name_state_unique):,}")

# ===========================================================================
# SECTION 5: Match each CallTime row against all NGP phone fields
# ===========================================================================
# For every row in the call log we attempt a match at each strictness level
# against each NGP phone column, in priority order:
#   Cell Phone → HomePhone → Preferred Phone
# We take the first phone column that yields an unambiguous match.

def lookup_match(key, level_dict):
    """Return (vanid_or_nan, conflict_bool) for a given lookup key.

    key is either a plain string (L1: phone only) or a tuple (L2/L3).

    - key is None or contains None  → (NaN, False)  can't look up
    - Not found in NGP at all       → (NaN, False)  no match
    - Matches multiple VANIDs       → (NaN, True)   ambiguous — don't guess
    - Matches exactly 1 VANID       → (vanid, False) clean match
    """
    if key is None or (isinstance(key, tuple) and any(x is None for x in key)):
        return np.nan, False
    if key not in level_dict["all"]:
        return np.nan, False
    if key in level_dict["unique"]:
        return level_dict["unique"][key][0], False
    return np.nan, True   # multiple VANIDs → ambiguous

# We iterate over the priority-ordered phone sources. For each source we
# apply all three strictness levels so we can compare them later.
# Results land in columns named vanid_<source>_L<level>.
#
# NOTE: phone matching uses first_initial (first letter of first name), while
# the name+state fallback (Section 5.5) uses full first_clean. The reason:
# phone matching already has the phone number as a strong anchor, so the
# initial is enough to distinguish two people at the same number. Name+state
# has a weaker anchor (state from area code), so it needs full first name to
# avoid false positives across NGP's 165K records.

PHONE_PRIORITY = [
    ("phone_clean_cell",      "cell"),
    ("phone_clean_home",      "home"),
    ("phone_clean_preferred", "preferred"),
]

for clean_col, label in PHONE_PRIORITY:
    if clean_col not in LOOKUPS:
        continue
    for level in ["L1", "L2", "L3"]:
        vanid_col    = f"vanid_{label}_{level}"
        conflict_col = f"conflict_{label}_{level}"

        if level == "L1":
            # Key is just the phone string
            results = ct["phone_clean"].apply(
                lambda p: lookup_match(p, LOOKUPS[clean_col][level])
            )
        elif level == "L2":
            results = ct.apply(
                lambda r: lookup_match(
                    (r["phone_clean"], r["last_clean"]),
                    LOOKUPS[clean_col][level]
                ), axis=1
            )
        else:  # L3
            results = ct.apply(
                lambda r: lookup_match(
                    (r["phone_clean"], r["last_clean"], r["first_initial"]),
                    LOOKUPS[clean_col][level]
                ), axis=1
            )

        ct[vanid_col], ct[conflict_col] = zip(*results)

# ===========================================================================
# SECTION 5.5: Name + state matching (fallback for phone-unmatched rows)
# ===========================================================================
# For each CallTime row, look up (last_clean, first_clean, phone_state)
# in the NGP name+state lookup. We record:
#   vanid_name_state  — matched VANID if unique, NaN otherwise
#   name_state_count  — number of NGP records matching that key (0 = no match,
#                       1 = unique, 2+ = ambiguous)
#
# Full first name is required (not just initial) — see Section 4.5 comment.
#
# We run this on ALL rows (not just unmatched) so we can later compare
# accuracy against the known Contact NGP ID rows. The final assignment
# step (Section 8) only uses this result for rows that are still unmatched
# after the phone steps.

def lookup_name_state(row, lookup_all, lookup_unique):
    """Return (vanid_or_nan, count, conflict_bool) for a name+state lookup.

    count is the number of NGP records matching (last, first, state).
    A match is only accepted when count == 1.
    """
    last  = row["last_clean"]
    first = row["first_clean"]
    state = row["phone_state"]

    if any(pd.isna(x) or x is None for x in [last, first, state]):
        return np.nan, 0, False

    key = (last, first, state)
    if key not in lookup_all:
        return np.nan, 0, False
    count = len(lookup_all[key])
    if key in lookup_unique:
        return lookup_unique[key][0], 1, False
    return np.nan, count, True   # ambiguous

results_ns = ct.apply(
    lambda r: lookup_name_state(r, name_state_all, name_state_unique),
    axis=1
)
ct["vanid_name_state"], ct["name_state_count"], ct["name_state_conflict"] = zip(*results_ns)

# ===========================================================================
# SECTION 6: Compare match rates across levels and phone sources
# ===========================================================================

print("\n" + "="*65)
print(f"MATCH RATE COMPARISON -- PHONE  (n = {len(ct)} rows)")
print("="*65)

for clean_col, label in PHONE_PRIORITY:
    if clean_col not in LOOKUPS:
        continue
    print(f"\n  NGP source: {label.upper()}")
    for level, desc in [("L1", "phone only           "),
                         ("L2", "phone + last         "),
                         ("L3", "phone + last + initial")]:
        vanid_col    = f"vanid_{label}_{level}"
        conflict_col = f"conflict_{label}_{level}"
        matched   = ct[vanid_col].notna().sum()
        conflicts = ct[conflict_col].sum()
        unmatched = len(ct) - matched - conflicts
        print(f"    {desc}: matched={matched} ({100*matched/len(ct):.1f}%)  "
              f"conflict={conflicts}  unmatched={unmatched}")

# ---------------------------------------------------------------------------
# Name+state match rate report — all rows and unmatched-only subsets
# ---------------------------------------------------------------------------
print("\n" + "="*65)
print("MATCH RATE -- NAME + STATE (area code -> state crosswalk)")
print("="*65)

# Determine which rows are still unmatched after all phone steps
# (same logic as Section 8, but computed here for reporting)
phone_l3_cols = [f"vanid_{label}_L3" for _, label in PHONE_PRIORITY
                 if f"vanid_{label}_L3" in ct.columns]

def has_phone_match(row):
    """Return True if at least one phone-based L3 column found a VANID."""
    if pd.notna(row.get("Contact NGP ID")):
        return True
    return any(pd.notna(row[col]) for col in phone_l3_cols if col in row.index)

ct["_phone_matched"] = ct.apply(has_phone_match, axis=1)
unmatched_mask = ~ct["_phone_matched"]

print(f"\n  All {len(ct)} rows:")
ns_unique   = ct["vanid_name_state"].notna().sum()
ns_conflict = ct["name_state_conflict"].sum()
ns_none     = (ct["name_state_count"] == 0).sum()
print(f"    Unique match (name+state -> 1 VANID): {ns_unique} "
      f"({100*ns_unique/len(ct):.1f}%)")
print(f"    Ambiguous    (name+state -> 2+ VANIDs): {ns_conflict} "
      f"({100*ns_conflict/len(ct):.1f}%)")
print(f"    No match                             : {ns_none} "
      f"({100*ns_none/len(ct):.1f}%)")

sub = ct[unmatched_mask]
print(f"\n  {len(sub)} rows with no phone match (the ones that need this fallback):")
ns_u2 = sub["vanid_name_state"].notna().sum()
ns_c2 = sub["name_state_conflict"].sum()
ns_n2 = (sub["name_state_count"] == 0).sum()
print(f"    Unique match (name+state -> 1 VANID): {ns_u2} "
      f"({100*ns_u2/len(sub):.1f}% of unmatched)")
print(f"    Ambiguous    (name+state -> 2+ VANIDs): {ns_c2} "
      f"({100*ns_c2/len(sub):.1f}% of unmatched)")
print(f"    No match                             : {ns_n2} "
      f"({100*ns_n2/len(sub):.1f}% of unmatched)")

# Distribution of how many duplicates the ambiguous rows hit
print(f"\n  Duplicate count distribution (ambiguous name+state rows, unmatched subset):")
dup_dist = sub[sub["name_state_conflict"]]["name_state_count"].value_counts().sort_index()
if len(dup_dist):
    for count_val, n_rows in dup_dist.items():
        print(f"    {count_val} NGP candidates -> {n_rows} CallTime rows")
else:
    print("    (none)")

# Also report the state breakdown for the unmatched rows, to show which
# campaigns are driving the unmatched population
print(f"\n  State breakdown for the {len(sub)} unmatched rows:")
print(sub["phone_state"].value_counts(dropna=False).to_string())

# ===========================================================================
# SECTION 7: Validate against known Contact NGP IDs
# ===========================================================================
# Rows that already have a Contact NGP ID are ground truth. We check whether
# our phone matching finds the same VANID, using the strict L3 level.
# We also validate the name+state match for these rows.

print("\n" + "="*65)
print("VALIDATION: match results vs. existing Contact NGP ID")
print("="*65)

known = ct[ct["Contact NGP ID"].notna()].copy()
known["Contact NGP ID"] = known["Contact NGP ID"].astype(int)
print(f"\n  Rows with existing Contact NGP ID: {len(known)}")

# Phone validation
for clean_col, label in PHONE_PRIORITY:
    if clean_col not in LOOKUPS:
        continue
    vanid_col = f"vanid_{label}_L3"
    matched_known = known[known[vanid_col].notna()].copy()
    matched_known[vanid_col] = matched_known[vanid_col].astype(int)

    agree    = (matched_known[vanid_col] == matched_known["Contact NGP ID"]).sum()
    disagree = (matched_known[vanid_col] != matched_known["Contact NGP ID"]).sum()

    print(f"\n  Phone {label.upper()} (L3):")
    print(f"    Phone-matched {len(matched_known)} of {len(known)} known rows")
    print(f"    Agree with Contact NGP ID:    {agree}")
    print(f"    Disagree with Contact NGP ID: {disagree}")

    if disagree > 0:
        bad = matched_known[matched_known[vanid_col] != matched_known["Contact NGP ID"]]
        print("    Disagreeing rows (investigate these):")
        print(bad[["Contact Name", "phone_clean",
                   "Contact NGP ID", vanid_col]].to_string(index=False))

# Name+state validation
ns_known = known[known["vanid_name_state"].notna()].copy()
ns_known["vanid_name_state"] = ns_known["vanid_name_state"].astype(int)
ns_agree    = (ns_known["vanid_name_state"] == ns_known["Contact NGP ID"]).sum()
ns_disagree = (ns_known["vanid_name_state"] != ns_known["Contact NGP ID"]).sum()

print(f"\n  Name + state fallback:")
print(f"    Matched {len(ns_known)} of {len(known)} known rows")
print(f"    Agree with Contact NGP ID:    {ns_agree}")
print(f"    Disagree with Contact NGP ID: {ns_disagree}")

if ns_disagree > 0:
    bad_ns = ns_known[ns_known["vanid_name_state"] != ns_known["Contact NGP ID"]]
    print("    Disagreeing rows (investigate these):")
    print(bad_ns[["Contact Name", "phone_state",
                  "Contact NGP ID", "vanid_name_state"]].to_string(index=False))

# ===========================================================================
# SECTION 8: Assign final VANIDs
# ===========================================================================
# Priority order for final assignment:
#   1. Existing Contact NGP ID  (ground truth)
#   2. Cell Phone L3 match
#   3. HomePhone L3 match
#   4. Preferred Phone L3 match
#   5. Name + state match       (only when unique)
#   6. Unmatched
#
# L1/L2 columns remain in the output for auditability but are not used here.

def assign_vanid(row):
    """Return (vanid, match_method) using the priority order above."""
    if pd.notna(row["Contact NGP ID"]):
        return int(row["Contact NGP ID"]), "existing"
    for col, method in [
        ("vanid_cell_L3",      "phone_cell"),
        ("vanid_home_L3",      "phone_home"),
        ("vanid_preferred_L3", "phone_preferred"),
    ]:
        if col in row.index and pd.notna(row[col]):
            return int(row[col]), method
    if pd.notna(row.get("vanid_name_state")):
        return int(row["vanid_name_state"]), "name_state"
    return np.nan, "unmatched"

ct["vanid_assigned"], ct["match_method"] = zip(*ct.apply(assign_vanid, axis=1))

# Propagate the L3 conflict flag (True if any source had an ambiguous match
# or the name+state match was ambiguous)
conflict_cols = [f"conflict_{label}_L3"
                 for _, label in PHONE_PRIORITY
                 if f"conflict_{label}_L3" in ct.columns]
ct["match_conflict"] = ct[conflict_cols + ["name_state_conflict"]].any(axis=1)

# ===========================================================================
# SECTION 9: Join NoCall flag from NGP
# ===========================================================================
# NoCall = 1 means the contact has asked not to be called.
# We carry this flag through to the output so downstream scripts can
# surface it for review. These rows are NOT dropped — that decision
# belongs to whoever reviews the output.

if "NoCall" in ngp.columns:
    # Build a simple VANID → NoCall lookup from the NGP file
    nocall_map = ngp.set_index("VANID")["NoCall"].to_dict()

    ct["no_call"] = ct["vanid_assigned"].apply(
        lambda v: nocall_map.get(int(v), np.nan) if pd.notna(v) else np.nan
    )
    n_nocall = (ct["no_call"] == 1).sum()
    print(f"\nContacts flagged NoCall = 1 in matched rows: {n_nocall}")
else:
    ct["no_call"] = np.nan
    print("\nWARNING: NoCall column not found in NGP file")

# ===========================================================================
# SECTION 10: Summary and save output
# ===========================================================================

print("\n" + "="*65)
print("FINAL ASSIGNMENT SUMMARY")
print("="*65)
print(ct["match_method"].value_counts().to_string())
print(f"\nTotal rows:      {len(ct)}")
print(f"Assigned VANID:  {ct['vanid_assigned'].notna().sum()} "
      f"({100*ct['vanid_assigned'].notna().mean():.1f}%)")
print(f"Unmatched:       {(ct['match_method'] == 'unmatched').sum()}")

# Drop the internal helper column before saving
ct.drop(columns=["_phone_matched"], inplace=True)

# Columns to keep in the output file.
# Intermediate name/phone cleaning columns are dropped.
# All three per-source vanid columns are kept for auditability.
output_cols = [
    # Original call log fields (drop empty columns)
    "Call ID", "Date", "Duration (seconds)",
    "Contact ID", "Contact NGP ID",
    "Contact Name", "Contact Phone", "Contact Phone Type",
    "Contact Phone is Bad",
    "Campaign Phone", "Outcome",
    "Contribution Ask", "Contribution Ask Result",
    "Voicemail Template", "Note", "User",
    # Match results
    "vanid_assigned", "match_method", "match_conflict", "no_call",
    # Per-source L3 VANIDs and name+state details for auditability
    # name_state_conflict: True when 2+ NGP records share the same name+state
    # name_state_count: number of NGP records that matched (0 = no match)
    "vanid_cell_L3", "vanid_home_L3", "vanid_preferred_L3",
    "vanid_name_state", "name_state_count", "name_state_conflict",
]
output_cols = [c for c in output_cols if c in ct.columns]

ct[output_cols].to_csv(OUTPUT_FILE, index=False)
print(f"\nOutput saved to: {OUTPUT_FILE}")
