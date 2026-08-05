"""Shared normalization helpers for the CallTime to NGP upload pipeline."""

import re
import unicodedata
from decimal import Decimal, InvalidOperation

DNC_NOTE_PATTERNS = [
    r"\bdo not call\b",
    r"\bdon['’]?t call\b",
    r"\bdo not phone\b",
    r"\bdon['’]?t phone\b",
    r"\bdo not contact (?:me|them|him|her)?\s*(?:by )?phone\b",
    r"\bno phone calls?\b",
    r"\bno phone\b",
    r"\bno more calls?\b",
    r"\brequested (?:no calls?|not to be called)\b",
    r"\bremove\s+(?:me|them|him|her)?\s*(?:from\s+)?(?:the\s+)?call(?:ing)?\s+list\b",
    r"\btake\s+(?:me|them|him|her)?\s*(?:off|out of)\s+(?:the\s+)?call(?:ing)?\s+list\b",
    r"\bstop call(?:ing)?\b",
]

DNC_NOTE_RE = re.compile("|".join(DNC_NOTE_PATTERNS), flags=re.IGNORECASE)

# Call timestamps are used only to surface possible duplicates for review.
# They are deliberately not sufficient to exclude a row from the final upload.
CALL_TIMESTAMP_RE = re.compile(
    r"\bCall Date:\s*"
    r"(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?:\s*(?P<ampm>AM|PM))?",
    flags=re.IGNORECASE,
)


def is_nocall_flagged(value: object) -> bool:
    """Return whether a common NGP export value represents a true NoCall flag."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y"}
    try:
        return bool(value == 1 or value is True)
    except TypeError:
        return False


def find_dnc_phrase(note_text: object) -> str | None:
    """Return the phrase that triggered DNC review, or ``None`` if none matched."""
    if note_text is None:
        return None
    match = DNC_NOTE_RE.search(str(note_text))
    return match.group(0).strip() if match else None


def normalize_vanid(value: object) -> str:
    """Return a VANID as an integer string, rejecting null or fractional values."""
    if value is None:
        raise ValueError("VANID cannot be blank")

    text = str(value).strip()
    if not text or text.casefold() in {"nan", "none", "null", "<na>"}:
        raise ValueError("VANID cannot be blank")

    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid VANID: {value!r}") from exc

    if not number.is_finite() or number != number.to_integral_value():
        raise ValueError(f"VANID must be a whole number: {value!r}")
    return str(int(number))


def normalize_note_text(value: object) -> str:
    """Normalize note text for conservative duplicate comparison."""
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKC", str(value)).casefold()
    return " ".join(normalized.split())


def extract_call_timestamps(note_text: object) -> set[str]:
    """Extract canonical call timestamps embedded by step 02."""
    if note_text is None:
        return set()

    timestamps: set[str] = set()
    for match in CALL_TIMESTAMP_RE.finditer(str(note_text)):
        hour = int(match.group("hour"))
        ampm = (match.group("ampm") or "").upper()
        if ampm:
            hour = hour % 12 + (12 if ampm == "PM" else 0)
        timestamps.add(
            f"{int(match.group('year')):04d}-{int(match.group('month')):02d}-"
            f"{int(match.group('day')):02d}T{hour:02d}:{int(match.group('minute')):02d}"
        )
    return timestamps
