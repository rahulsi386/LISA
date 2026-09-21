from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILLS = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILLS))
import analysis_handoff as handoff
from review_batches import ReviewBatchError, write_review_batches
from lisa_path_resolver import LisaConfigError
from resolve_skill_inputs import resolve_inputs


class AnalysisHandoffTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, dict]:
        requirements = root / "requirements"
        requirements.mkdir()
        analysis = root / "output" / "analysis"
        analysis.mkdir(parents=True)
        ledger = analysis / "requirement-analysis_20260908_163312.json"
        ledger.write_text(json.dumps({"run_id": "RA-20260908_163312-0123ABCD",
                                     "findings": [{"finding_id": "REQ-1234567890"}]}),
                          encoding="utf-8")
        ledger.with_suffix(".md").write_text("# Analysis\n", encoding="utf-8")
        sources = [{"source_id": "SRC-1", "sha256": "0" * 64}]
        source_manifest = {
            "schema_version": "1.0", "run_id": "RA-20260908_163312-0123ABCD",
            "requirements_root": str(requirements), "sources": sources,
            "source_count": len(sources), "manifest_sha256": handoff._canonical_hash(sources),
        }
        manifest = handoff.build_validated_manifest(
            source_manifest, ledger, ledger.with_suffix(".md"), "2026-09-08T16:33:12+05:30",
        )
        self.write_manifest(ledger, manifest)
        return ledger, manifest

    def write_manifest(self, ledger: Path, manifest: dict) -> Path:
        path = ledger.with_name(f"{ledger.stem}-manifest.json")
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def test_validated_handoff_preserves_inventory_and_binds_both_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, expected = self.fixture(root)
            ledger, actual = handoff.load_validated_analysis(
                path, expected_requirements_root=root / "requirements",
            )
            self.assertEqual(expected, actual)
            self.assertEqual(actual["run_id"], ledger["run_id"])
            self.assertEqual(1, actual["source_count"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                             actual["publication"]["ledger"]["sha256"])

    def test_absent_pending_or_invalid_markers_never_commit_analysis(self) -> None:
        for mutation in ("missing", "prepared", "failed", "version", "run", "timestamp"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                path, manifest = self.fixture(Path(temporary))
                if mutation == "missing":
                    del manifest["publication"]
                elif mutation in {"prepared", "failed"}:
                    manifest["publication"]["status"] = mutation
                elif mutation == "version":
                    manifest["publication"]["schema_version"] = "0"
                elif mutation == "run":
                    manifest["publication"]["run_id"] = "RA-20260908_163313-0123ABCD"
                else:
                    manifest["publication"]["validated_at_local"] = "2026-09-08T16:33:12"
                self.write_manifest(path, manifest)
                with self.assertRaises(handoff.AnalysisHandoffError):
                    handoff.load_validated_analysis(path)

    def test_missing_tampered_or_redirected_artifacts_are_rejected(self) -> None:
        for mutation in ("manifest-missing", "ledger-missing", "markdown-missing",
                         "ledger-edited", "markdown-edited", "relative-escape",
                         "absolute-path", "different-sibling", "inventory", "count", "run"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                path, manifest = self.fixture(Path(temporary))
                if mutation == "manifest-missing":
                    path.with_name(f"{path.stem}-manifest.json").unlink()
                elif mutation in {"ledger-missing", "markdown-missing"}:
                    (path if mutation.startswith("ledger") else path.with_suffix(".md")).unlink()
                elif mutation in {"ledger-edited", "markdown-edited"}:
                    target = path if mutation.startswith("ledger") else path.with_suffix(".md")
                    target.write_text("changed", encoding="utf-8")
                else:
                    if mutation == "relative-escape":
                        manifest["publication"]["ledger"]["path"] = "..\\outside.json"
                    elif mutation == "absolute-path":
                        manifest["publication"]["ledger"]["path"] = str(path)
                    elif mutation == "different-sibling":
                        manifest["publication"]["markdown"]["path"] = "other.md"
                    elif mutation == "inventory":
                        manifest["sources"][0]["sha256"] = "f" * 64
                    elif mutation == "count":
                        manifest["source_count"] = 2
                    else:
                        altered = {"run_id": "RA-20260908_163313-0123ABCD"}
                        path.write_text(json.dumps(altered), encoding="utf-8")
                        manifest["publication"]["ledger"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                    self.write_manifest(path, manifest)
                with self.assertRaises(handoff.AnalysisHandoffError):
                    handoff.load_validated_analysis(path)

    def test_handoff_cannot_cross_project_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, _ = self.fixture(root)
            with self.assertRaisesRegex(handoff.AnalysisHandoffError, "root differs"):
                handoff.load_validated_analysis(
                    path, expected_requirements_root=root / "other" / "requirements",
                )

    def test_shared_resolver_requires_the_same_handoff_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, _ = self.fixture(root)
            config = root / "lisa-config.json"
            config.write_text(json.dumps({"basePath": "."}), encoding="utf-8")
            result = resolve_inputs("complexity-classifier", config)
            self.assertEqual(str(path), result["analysis"])
            self.assertEqual(str(path.with_name(f"{path.stem}-manifest.json")), result["analysisManifest"])
            newer = path.with_name("requirement-analysis_20260908_163313.json")
            newer.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            newer_time = path.stat().st_mtime_ns + 1_000_000_000
            os.utime(newer, ns=(newer_time, newer_time))
            with self.assertRaises(LisaConfigError):
                resolve_inputs("complexity-classifier", config)

    def test_handoff_rejects_manifest_changed_during_load(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path, _ = self.fixture(Path(temporary))
            original = handoff._read
            count = 0

            def changing_read(candidate: Path) -> bytes:
                nonlocal count
                payload = original(candidate)
                if candidate.name.endswith("-manifest.json"):
                    count += 1
                    if count == 2:
                        return payload + b"\n"
                return payload

            with patch.object(handoff, "_read", side_effect=changing_read):
                with self.assertRaisesRegex(handoff.AnalysisHandoffError, "changed while loading"):
                    handoff.load_validated_analysis(path)

    def test_builder_rejects_different_sibling_and_links_are_never_followed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path, manifest = self.fixture(Path(temporary))
            with self.assertRaisesRegex(handoff.AnalysisHandoffError, "matching ledger sibling"):
                handoff.build_validated_manifest(manifest, path, path.parent / "other.md",
                                                 "2026-09-08T16:33:12+05:30")
            original = Path.is_symlink
            with patch.object(Path, "is_symlink",
                              new=lambda candidate: candidate == path or original(candidate)):
                with self.assertRaisesRegex(handoff.AnalysisHandoffError, "cannot use links"):
                    handoff.load_validated_analysis(path)


class ReviewBatchTests(unittest.TestCase):
    def read_records(self, directory: Path, index: dict) -> list[dict]:
        records: list[dict] = []
        active: dict | None = None
        parts: list[str] = []
        expected_part = 1
        fragments = 0
        for batch in index["batches"]:
            payload = (directory / batch["path"]).read_bytes()
            self.assertLessEqual(len(payload), index["max_bytes"])
            self.assertEqual(len(payload), batch["byte_count"])
            self.assertEqual(hashlib.sha256(payload).hexdigest(), batch["sha256"])
            self.assertEqual(f"B-{batch['sha256']}", batch["batch_id"])
            for fragment in json.loads(payload)["records"]:
                value = {key: item for key, item in fragment.items() if key not in {"part", "final_part", "text"}}
                if active is None:
                    active = value
                self.assertEqual(active, value)
                self.assertEqual(expected_part, fragment["part"])
                parts.append(fragment["text"])
                fragments += 1
                expected_part += 1
                if fragment["final_part"]:
                    records.append({**active, "text": "".join(parts)})
                    active, parts, expected_part = None, [], 1
        self.assertIsNone(active)
        self.assertEqual(index["fragment_count"], fragments)
        self.assertEqual(index["record_count"], len(records))
        return records

    def test_late_records_and_repeated_values_are_retained(self) -> None:
        records = [
            {"record_id": f"R-{row:05d}", "text": f"System {row} | No | No | Yes",
             "source_id": "SRC-1", "locator": f"Sheet Requirements, row {row}"}
            for row in range(1, 1201)
        ]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            index = write_review_batches(directory, iter(records), max_bytes=1024)
            self.assertGreater(len(index["batches"]), 1)
            self.assertEqual(records, self.read_records(directory, index))
            page = index["first_page"]
            paths: list[str] = []
            page_count = 0
            while page:
                payload = (directory / page).read_bytes()
                self.assertLessEqual(len(payload), index["max_bytes"])
                value = json.loads(payload)
                paths.extend(item["path"] for item in value["batches"])
                page = value["next_page"]
                page_count += 1
            self.assertGreater(page_count, 1)
            self.assertEqual([item["path"] for item in index["batches"]], paths)
            self.assertLessEqual(Path(index["overview_path"]).stat().st_size, 1024)

    def test_oversized_escaped_unicode_text_round_trips_losslessly(self) -> None:
        records = [
            {"record_id": "large", "text": ('\u6f22\u5b57 \U0001f642 e\u0301 | No | No | \\"\r\n\t' * 600),
             "aliases": ["row 1", "row 7"]},
            {"record_id": "empty", "text": ""},
            {"record_id": "last", "text": "Purchases above 25000 require finance approval."},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            index = write_review_batches(directory, records, max_bytes=512)
            self.assertGreater(index["fragment_count"], len(records))
            self.assertEqual(records, self.read_records(directory, index))

    def test_batch_ids_are_deterministic_across_run_directories(self) -> None:
        records = [{"record_id": "R-1", "text": "A complete requirement.", "source_id": "SRC-1"}]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            left = write_review_batches(root / "run1", records)
            right = write_review_batches(root / "run2", records)
            self.assertEqual(left["batches"], right["batches"])
            self.assertEqual(left["content_sha256"], right["content_sha256"])
            changed = write_review_batches(root / "run3", [{**records[0], "text": "A changed requirement."}])
            self.assertNotEqual(left["content_sha256"], changed["content_sha256"])

    def test_invalid_records_and_oversized_metadata_fail_explicitly(self) -> None:
        cases = [
            [{"record_id": "a", "text": ""}, {"record_id": "a", "text": "same id"}],
            [{"record_id": "", "text": "missing id"}],
            [{"record_id": "a", "text": None}],
            [{"record_id": "a", "text": "x", "part": 1}],
            [{"record_id": "a", "text": "", "metadata": "x" * 2000}],
            [{"record_id": "a", "text": "nonempty", "metadata": "x" * 2000}],
        ]
        for records in cases:
            with self.subTest(records=records), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                with self.assertRaises(ReviewBatchError):
                    write_review_batches(directory, records, max_bytes=512)
                self.assertFalse((directory / "index.json").exists())

    def test_empty_review_and_minimum_budget_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            empty = write_review_batches(directory / "empty", [], max_bytes=256)
            self.assertEqual([], empty["batches"])
            self.assertEqual("", empty["first_page"])
            small = write_review_batches(directory / "small", [{"record_id": "a", "text": "x" * 1000}],
                                         max_bytes=256)
            self.assertEqual([{"record_id": "a", "text": "x" * 1000}],
                             self.read_records(directory / "small", small))
            for budget in (0, 255, True, 256.5):
                with self.assertRaises(ReviewBatchError):
                    write_review_batches(directory, [], max_bytes=budget)


if __name__ == "__main__":
    unittest.main()
