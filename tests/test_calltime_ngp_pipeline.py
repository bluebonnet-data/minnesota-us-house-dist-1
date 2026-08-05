import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PIPELINE_DIR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "Cleaning_CallTime_for_NGP_upload"
)
sys.path.insert(0, str(PIPELINE_DIR))

from pipeline_utils import (  # noqa: E402
    extract_call_timestamps,
    find_dnc_phrase,
    is_nocall_flagged,
    normalize_note_text,
    normalize_vanid,
)


def load_step04_module():
    spec = importlib.util.spec_from_file_location(
        "check_duplicate_notes",
        PIPELINE_DIR / "04_check_duplicate_notes.py",
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


STEP04 = load_step04_module()


def upload_row(
    vanid: object, note_text: str, contact_name: str = "Test Contact"
) -> dict:
    return {
        "VANID": vanid,
        "ContactName": contact_name,
        "DateEntered": "5/28/2026",
        "EnteredBy": "Tester, T",
        "NoteCategory": "",
        "NoteTags": "",
        "IsPinned": "No",
        "NoteText": note_text,
        "Suppressions": "",
    }


class DncTests(unittest.TestCase):
    def test_common_nocall_encodings(self):
        for value in (1, True, "1", "true", "TRUE", "yes", "Y"):
            with self.subTest(value=value):
                self.assertTrue(is_nocall_flagged(value))

        for value in (0, False, "0", "false", "no", "", None, float("nan")):
            with self.subTest(value=value):
                self.assertFalse(is_nocall_flagged(value))

    def test_dnc_phrases_are_detected_case_insensitively(self):
        phrases = (
            "Please DO NOT CALL again",
            "don't call this person",
            "requested no calls",
            "remove me from the calling list",
            "requested not to be called",
        )
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertIsNotNone(find_dnc_phrase(phrase))

    def test_unrelated_notes_are_not_flagged(self):
        for note in (None, "", "Left voicemail", "Asked us to call next Tuesday"):
            with self.subTest(note=note):
                self.assertIsNone(find_dnc_phrase(note))

    def test_step03_combines_ngp_and_note_based_dnc_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "Data"
            data_dir.mkdir()
            pd.DataFrame(
                [
                    {
                        "Contact Name": "Existing Flag",
                        "Contact ID": 1,
                        "VANID": 101,
                        "Contact Phone": "5551112222",
                        "Notes": "Left voicemail",
                    },
                    {
                        "Contact Name": "Note Flag",
                        "Contact ID": 2,
                        "VANID": 102,
                        "Contact Phone": "5552223333",
                        "Notes": "Requested no calls",
                    },
                    {
                        "Contact Name": "No Flag",
                        "Contact ID": 3,
                        "VANID": 103,
                        "Contact Phone": "5553334444",
                        "Notes": "Asked us to call next week",
                    },
                ]
            ).to_csv(data_dir / "call_notes_condensed.csv", index=False)
            pd.DataFrame(
                [
                    {"Contact ID": 1, "Date": "2026-05-28 13:15:00", "no_call": "Yes"},
                    {"Contact ID": 2, "Date": "2026-05-28 14:15:00", "no_call": "No"},
                    {"Contact ID": 3, "Date": "2026-05-28 15:15:00", "no_call": "No"},
                ]
            ).to_csv(data_dir / "call_log_with_vanid.csv", index=False)

            environment = os.environ.copy()
            environment["CALLTIME_NGP_ROOT"] = str(root)
            result = subprocess.run(
                [sys.executable, str(PIPELINE_DIR / "03_format_ngp_upload.py")],
                capture_output=True,
                check=False,
                env=environment,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = pd.read_csv(data_dir / "ngp_upload_ready.csv")

        suppressions = output.set_index("VANID")["Suppressions"]
        self.assertEqual(suppressions.loc[101], "Do not call")
        self.assertEqual(suppressions.loc[102], "Do not call")
        self.assertTrue(pd.isna(suppressions.loc[103]))
        self.assertIn("Matched phrase: 'Requested no calls'", result.stdout)


class NormalizationTests(unittest.TestCase):
    def test_note_normalization_handles_unicode_case_and_whitespace(self):
        self.assertEqual(
            normalize_note_text("  ＨＥＬＬＯ\n  World  "),
            normalize_note_text("hello world"),
        )

    def test_vanid_normalization(self):
        self.assertEqual(normalize_vanid("145647880.0"), "145647880")
        with self.assertRaises(ValueError):
            normalize_vanid("145.5")

    def test_call_timestamp_extraction(self):
        note = "Call Date: 5/28/2026 12:03 AM; one | Call Date: 5/28/2026 1:15 PM; two"
        self.assertEqual(
            extract_call_timestamps(note),
            {"2026-05-28T00:03", "2026-05-28T13:15"},
        )


class DuplicateWorkflowTests(unittest.TestCase):
    def setUp(self):
        rows = [
            upload_row(101, "Hello   WORLD", "Exact Duplicate"),
            upload_row(102, "Call Date: 5/28/2026 1:15 PM; New detail", "Possible"),
            upload_row(103, "A genuinely new note", "Clean"),
        ]
        self.upload = pd.DataFrame(rows)
        self.upload["_vanid_normalized"] = self.upload["VANID"].map(normalize_vanid)
        self.upload["_note_normalized"] = self.upload["NoteText"].map(
            normalize_note_text
        )

        notes = pd.DataFrame(
            {
                "VANID": [101, 102, 999],
                "NoteText": [
                    " hello world ",
                    "Call Date: 5/28/2026 1:15 PM; Different detail",
                    "A genuinely new note",
                ],
            }
        )
        notes["_vanid_normalized"] = notes["VANID"].map(normalize_vanid)
        notes["_note_normalized"] = notes["NoteText"].map(normalize_note_text)
        notes["_call_timestamps"] = notes["NoteText"].map(extract_call_timestamps)
        self.notes = notes

    def test_confirmed_and_possible_duplicates_are_classified_safely(self):
        duplicates, possible, clean = STEP04.classify_upload_rows(
            self.upload, self.notes
        )

        self.assertEqual(duplicates["VANID"].tolist(), [101])
        self.assertEqual(possible["VANID"].tolist(), [102])
        self.assertEqual(clean["VANID"].tolist(), [102, 103])
        self.assertEqual(
            possible.iloc[0]["matching_call_timestamps"], "2026-05-28T13:15"
        )

    def test_reports_and_final_upload_are_always_written_with_stable_schemas(self):
        duplicates, possible, clean = STEP04.classify_upload_rows(
            self.upload, self.notes
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            paths = STEP04.write_results(duplicates, possible, clean, Path(temp_dir))
            final = pd.read_csv(paths["final"])
            duplicate_report = pd.read_csv(paths["duplicates"])
            possible_report = pd.read_csv(paths["possible"])

        self.assertEqual(final.columns.tolist(), STEP04.UPLOAD_COLUMNS)
        self.assertIn("duplicate_reason", duplicate_report.columns)
        self.assertIn("possible_duplicate_reason", possible_report.columns)
        self.assertNotIn("is_duplicate", final.columns)

    def test_same_text_on_a_different_vanid_is_not_a_duplicate(self):
        row = pd.DataFrame([upload_row(999, "hello world")])
        row["_vanid_normalized"] = row["VANID"].map(normalize_vanid)
        row["_note_normalized"] = row["NoteText"].map(normalize_note_text)
        duplicates, _, clean = STEP04.classify_upload_rows(row, self.notes)
        self.assertTrue(duplicates.empty)
        self.assertEqual(len(clean), 1)

    def test_prepare_then_dedupe_requires_an_explicit_export(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "Data"
            raw_dir = root / "Raw Data"
            data_dir.mkdir()
            pd.DataFrame([upload_row(101, "Existing note")]).to_csv(
                data_dir / "ngp_upload_ready.csv", index=False
            )
            (data_dir / "ngp_upload_deduped.csv").write_text(
                "stale result\n", encoding="utf-8"
            )

            with contextlib.redirect_stdout(io.StringIO()):
                prepare_status = STEP04.main(["prepare", "--root", str(root)])

            self.assertEqual(prepare_status, 0)
            self.assertTrue((data_dir / "vanids_to_pull.csv").exists())
            self.assertTrue((data_dir / STEP04.MANIFEST_FILENAME).exists())
            self.assertFalse((data_dir / "ngp_upload_deduped.csv").exists())

            raw_dir.mkdir()
            pd.DataFrame([{"VANID": 101, "NoteText": " existing NOTE "}]).to_csv(
                raw_dir / "ngp_notes_export_20260528.csv", index=False
            )
            with contextlib.redirect_stdout(io.StringIO()):
                dedupe_status = STEP04.main(
                    [
                        "dedupe",
                        "--root",
                        str(root),
                        "--ngp-notes-file",
                        str(raw_dir / "ngp_notes_export_20260528.csv"),
                    ]
                )

            self.assertEqual(dedupe_status, 0)
            self.assertTrue((data_dir / "identified_duplicate_notes.csv").exists())
            self.assertTrue((data_dir / "possible_duplicate_notes.csv").exists())
            self.assertTrue((data_dir / "ngp_upload_deduped.csv").exists())

    def test_dedupe_refuses_an_upload_changed_after_prepare(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "Data"
            data_dir.mkdir()
            upload_path = data_dir / "ngp_upload_ready.csv"
            pd.DataFrame([upload_row(101, "Original note")]).to_csv(
                upload_path, index=False
            )
            with contextlib.redirect_stdout(io.StringIO()):
                STEP04.main(["prepare", "--root", str(root)])

            pd.DataFrame([upload_row(101, "Changed note")]).to_csv(
                upload_path, index=False
            )
            notes_path = root / "notes.csv"
            pd.DataFrame([{"VANID": 101, "NoteText": "Original note"}]).to_csv(
                notes_path, index=False
            )

            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, "changed after"):
                    STEP04.main(
                        [
                            "dedupe",
                            "--root",
                            str(root),
                            "--ngp-notes-file",
                            str(notes_path),
                        ]
                    )


if __name__ == "__main__":
    unittest.main()
