"""Step 4: remove notes that already exist in NGP before bulk upload.

The ``prepare`` command writes ``Data/vanids_to_pull.csv`` and fingerprints
the planned upload. After the corresponding NGP notes export is obtained, the
``dedupe`` command requires that export explicitly and refuses to continue if
the planned upload changed after preparation.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from pipeline_utils import (
    extract_call_timestamps,
    normalize_note_text,
    normalize_vanid,
)

DEFAULT_ROOT = os.environ.get(
    "CALLTIME_NGP_ROOT",
    r"C:\Users\willl\Documents\bluebonnet 2026",
)
DEFAULT_NGP_VANID_COLUMN = "VANID"
DEFAULT_NGP_NOTE_COLUMN = "NoteText"
MANIFEST_FILENAME = "duplicate_check_manifest.json"
RESULT_FILENAMES = (
    "identified_duplicate_notes.csv",
    "possible_duplicate_notes.csv",
    "ngp_upload_deduped.csv",
)

UPLOAD_COLUMNS = [
    "VANID",
    "ContactName",
    "DateEntered",
    "EnteredBy",
    "NoteCategory",
    "NoteTags",
    "IsPinned",
    "NoteText",
    "Suppressions",
]


def validate_columns(frame: pd.DataFrame, required: list[str], source: str) -> None:
    """Raise a readable error when an input file is missing required columns."""
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(
            f"{source} is missing required column(s): {missing}. "
            f"Columns present: {list(frame.columns)}"
        )


def load_planned_upload(path: Path) -> pd.DataFrame:
    """Load and validate the step-03 upload candidate."""
    upload = pd.read_csv(path)
    validate_columns(upload, UPLOAD_COLUMNS, str(path))

    if upload["VANID"].isna().any():
        count = int(upload["VANID"].isna().sum())
        raise ValueError(f"{path} contains {count} row(s) with a blank VANID")

    upload = upload.copy()
    upload["_vanid_normalized"] = upload["VANID"].map(normalize_vanid)
    upload["_note_normalized"] = upload["NoteText"].map(normalize_note_text)

    empty_notes = upload["_note_normalized"].eq("")
    if empty_notes.any():
        raise ValueError(
            f"{path} contains {int(empty_notes.sum())} row(s) with blank NoteText"
        )
    return upload


def write_vanid_pull_file(upload: pd.DataFrame, output_path: Path) -> None:
    """Write unique normalized VANIDs for scoping the manual NGP notes export."""
    unique_vanids = sorted(
        upload["_vanid_normalized"].unique(),
        key=int,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"VANID": unique_vanids}).to_csv(output_path, index=False)


def sha256_file(path: Path) -> str:
    """Return a stable fingerprint for a file without loading it all at once."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(
    upload: pd.DataFrame, upload_path: Path, manifest_path: Path
) -> None:
    """Record exactly which planned upload the VANID pull list represents."""
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "upload_file": str(upload_path.resolve()),
        "upload_sha256": sha256_file(upload_path),
        "upload_rows": len(upload),
        "unique_vanids": int(upload["_vanid_normalized"].nunique()),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def clear_previous_results(data_dir: Path) -> list[Path]:
    """Remove generated results that no longer represent the prepared upload."""
    removed = []
    for filename in RESULT_FILENAMES:
        path = data_dir / filename
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


def validate_manifest(upload_path: Path, manifest_path: Path) -> dict:
    """Ensure dedupe is using the exact upload that was prepared."""
    if not manifest_path.exists():
        raise ValueError(
            f"Preparation manifest not found: {manifest_path}. "
            "Run this script with the 'prepare' command first."
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {"upload_file", "upload_sha256", "upload_rows", "unique_vanids"}
    missing = sorted(required - manifest.keys())
    if missing:
        raise ValueError(f"Preparation manifest is missing field(s): {missing}")

    if manifest["upload_file"] != str(upload_path.resolve()):
        raise ValueError(
            "The upload file path does not match the preparation manifest. "
            "Run 'prepare' again for this upload file."
        )

    if manifest["upload_sha256"] != sha256_file(upload_path):
        raise ValueError(
            "ngp_upload_ready.csv changed after the VANID list was prepared. "
            "Run 'prepare' again and pull a new NGP notes export."
        )
    return manifest


def load_ngp_notes(
    path: Path,
    vanid_column: str,
    note_column: str,
    separator: str = ",",
    encoding: str = "utf-8-sig",
) -> pd.DataFrame:
    """Load an NGP notes export and normalize its comparison fields."""
    notes = pd.read_csv(path, sep=separator, encoding=encoding)
    validate_columns(notes, [vanid_column, note_column], str(path))
    notes = notes[[vanid_column, note_column]].dropna().copy()
    notes = notes.rename(columns={vanid_column: "VANID", note_column: "NoteText"})
    notes["_vanid_normalized"] = notes["VANID"].map(normalize_vanid)
    notes["_note_normalized"] = notes["NoteText"].map(normalize_note_text)
    notes = notes[notes["_note_normalized"].ne("")].copy()
    notes["_call_timestamps"] = notes["NoteText"].map(extract_call_timestamps)
    return notes


def classify_upload_rows(
    upload: pd.DataFrame,
    ngp_notes: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split planned rows into duplicates, possible duplicates, and clean rows."""
    existing_pairs = set(
        zip(ngp_notes["_vanid_normalized"], ngp_notes["_note_normalized"])
    )

    timestamps_by_vanid: dict[str, set[str]] = {}
    for vanid, timestamps in zip(
        ngp_notes["_vanid_normalized"], ngp_notes["_call_timestamps"]
    ):
        timestamps_by_vanid.setdefault(vanid, set()).update(timestamps)

    working = upload.copy()
    working["is_duplicate"] = [
        (vanid, note) in existing_pairs
        for vanid, note in zip(
            working["_vanid_normalized"], working["_note_normalized"]
        )
    ]

    overlapping_timestamps: list[str] = []
    for _, row in working.iterrows():
        planned = extract_call_timestamps(row["NoteText"])
        existing = timestamps_by_vanid.get(row["_vanid_normalized"], set())
        overlapping_timestamps.append(", ".join(sorted(planned & existing)))
    working["matching_call_timestamps"] = overlapping_timestamps

    duplicate_mask = working["is_duplicate"]
    possible_mask = ~duplicate_mask & working["matching_call_timestamps"].ne("")

    duplicates = working.loc[duplicate_mask, UPLOAD_COLUMNS].copy()
    duplicates["duplicate_reason"] = "same VANID and normalized NoteText"

    possible = working.loc[possible_mask, UPLOAD_COLUMNS].copy()
    possible["possible_duplicate_reason"] = "same VANID and call timestamp"
    possible["matching_call_timestamps"] = working.loc[
        possible_mask, "matching_call_timestamps"
    ]

    clean = working.loc[~duplicate_mask, UPLOAD_COLUMNS].copy()
    return duplicates, possible, clean


def write_results(
    duplicates: pd.DataFrame,
    possible: pd.DataFrame,
    clean: pd.DataFrame,
    output_dir: Path,
) -> dict[str, Path]:
    """Write review reports and the only CSV that should be uploaded to NGP."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "duplicates": output_dir / "identified_duplicate_notes.csv",
        "possible": output_dir / "possible_duplicate_notes.csv",
        "final": output_dir / "ngp_upload_deduped.csv",
    }
    duplicates.to_csv(paths["duplicates"], index=False, encoding="utf-8")
    possible.to_csv(paths["possible"], index=False, encoding="utf-8")
    clean.to_csv(paths["final"], index=False, encoding="utf-8")
    return paths


def add_upload_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root", default=DEFAULT_ROOT, help="Folder containing Data and Raw Data"
    )
    parser.add_argument("--upload-file", help="Override Data/ngp_upload_ready.csv")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser(
        "prepare",
        help="Write the VANID pull list and fingerprint the planned upload",
    )
    add_upload_arguments(prepare)

    dedupe = commands.add_parser(
        "dedupe",
        help="Compare a specific NGP notes export and write the final upload",
    )
    add_upload_arguments(dedupe)
    dedupe.add_argument(
        "--ngp-notes-file", required=True, help="Current NGP notes export"
    )
    dedupe.add_argument("--ngp-vanid-column", default=DEFAULT_NGP_VANID_COLUMN)
    dedupe.add_argument("--ngp-note-column", default=DEFAULT_NGP_NOTE_COLUMN)
    dedupe.add_argument(
        "--ngp-separator",
        choices=("comma", "tab"),
        default="comma",
        help="Delimiter used by the NGP notes export",
    )
    dedupe.add_argument("--ngp-encoding", default="utf-8-sig")
    return parser


def resolve_upload_paths(args: argparse.Namespace) -> tuple[Path, Path, Path]:
    data_dir = Path(args.root) / "Data"
    upload_path = (
        Path(args.upload_file)
        if args.upload_file
        else data_dir / "ngp_upload_ready.csv"
    )
    return data_dir, upload_path, data_dir / MANIFEST_FILENAME


def prepare_command(args: argparse.Namespace) -> int:
    data_dir, upload_path, manifest_path = resolve_upload_paths(args)
    vanid_path = data_dir / "vanids_to_pull.csv"

    print(f"Loading planned upload: {upload_path}")
    upload = load_planned_upload(upload_path)
    write_vanid_pull_file(upload, vanid_path)
    removed_results = clear_previous_results(data_dir)
    write_manifest(upload, upload_path, manifest_path)
    print(
        f"  {len(upload)} planned note(s) across {upload['_vanid_normalized'].nunique()} contact(s)"
    )
    print(f"  VANID pull list written to: {vanid_path}")
    print(f"  Preparation manifest written to: {manifest_path}")
    if removed_results:
        print(f"  Cleared {len(removed_results)} result file(s) from the previous run")
    print("\nExport existing NGP notes for exactly these VANIDs, then run:")
    print("  04_check_duplicate_notes.py dedupe --ngp-notes-file <export.csv>")
    return 0


def dedupe_command(args: argparse.Namespace) -> int:
    data_dir, upload_path, manifest_path = resolve_upload_paths(args)
    notes_path = Path(args.ngp_notes_file)

    print(f"Validating preparation manifest: {manifest_path}")
    manifest = validate_manifest(upload_path, manifest_path)
    upload = load_planned_upload(upload_path)
    if len(upload) != manifest["upload_rows"]:
        raise ValueError("Upload row count does not match the preparation manifest")

    separator = "," if args.ngp_separator == "comma" else "\t"
    print(f"\nLoading existing NGP notes: {notes_path}")
    ngp_notes = load_ngp_notes(
        notes_path,
        args.ngp_vanid_column,
        args.ngp_note_column,
        separator=separator,
        encoding=args.ngp_encoding,
    )
    print(f"  {len(ngp_notes)} usable existing note(s) loaded")

    duplicates, possible, clean = classify_upload_rows(upload, ngp_notes)
    paths = write_results(duplicates, possible, clean, data_dir)

    print("\nDuplicate check complete:")
    print(f"  Confirmed duplicates excluded: {len(duplicates)}")
    print(f"  Possible duplicates to review: {len(possible)}")
    print(f"  Rows in final upload:          {len(clean)}")
    print(f"  Duplicate report: {paths['duplicates']}")
    print(f"  Possible-duplicate report: {paths['possible']}")
    print(f"  FINAL FILE TO UPLOAD: {paths['final']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "prepare":
        return prepare_command(args)
    return dedupe_command(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
