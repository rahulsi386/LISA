from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from cleanup_output import (  # noqa: E402
    CONFIRMATION,
    CleanupError,
    PartialCleanupError,
    execute_cleanup,
    inventory,
    resolve_output,
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class CleanupOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "ProjectLISA"
        self.config = self.project / "config" / "lisa-config.json"
        self.output = self.project / "output"
        self.output.mkdir(parents=True)
        write_json(
            self.config,
            {
                "basePath": "..",
                "custName": "Fixture Customer",
            },
        )
        (self.output / "root.txt").write_text("root\n", encoding="utf-8")
        (self.output / ".hidden").write_text("hidden\n", encoding="utf-8")
        nested = self.output / "stage" / "nested"
        nested.mkdir(parents=True)
        (nested / "data.json").write_text('{"ok": true}\n', encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_inventory_is_read_only(self) -> None:
        result = inventory(self.config)
        self.assertEqual(len(result.files), 3)
        self.assertEqual(len(result.directories), 2)
        self.assertGreater(result.total_bytes, 0)
        self.assertEqual(len(result.fingerprint), 64)
        self.assertTrue((self.output / "root.txt").is_file())
        self.assertTrue(result.public()["requiresConfirmation"])

    def test_exact_consent_deletes_contents_and_preserves_root(self) -> None:
        plan = inventory(self.config)
        result = execute_cleanup(self.config, plan.fingerprint, CONFIRMATION)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["deletedFiles"], 3)
        self.assertTrue(self.output.is_dir())
        self.assertEqual(list(self.output.iterdir()), [])

    def test_wrong_confirmation_is_rejected_without_deletion(self) -> None:
        plan = inventory(self.config)
        with self.assertRaises(CleanupError):
            execute_cleanup(self.config, plan.fingerprint, "yes")
        self.assertTrue((self.output / "root.txt").is_file())

    def test_fingerprint_drift_requires_new_consent(self) -> None:
        plan = inventory(self.config)
        (self.output / "new.txt").write_text("new\n", encoding="utf-8")
        with self.assertRaises(CleanupError):
            execute_cleanup(self.config, plan.fingerprint, CONFIRMATION)
        self.assertTrue((self.output / "root.txt").is_file())
        self.assertTrue((self.output / "new.txt").is_file())

    def test_empty_root_needs_no_confirmation(self) -> None:
        shutil.rmtree(self.output)
        self.output.mkdir()
        result = inventory(self.config).public()
        self.assertFalse(result["requiresConfirmation"])
        self.assertEqual(result["fileCount"], 0)
        self.assertEqual(result["directoryCount"], 0)

    def test_supports_absolute_base_path(self) -> None:
        write_json(
            self.config,
            {"custName": "Fixture Customer", "basePath": str(self.project.resolve())},
        )
        _, _, resolved = resolve_output(self.config)
        self.assertEqual(self.output.resolve(), resolved)

    def test_resolves_output_from_relative_base_path(self) -> None:
        _, _, resolved = resolve_output(self.config)
        self.assertEqual(resolved, self.output.resolve())

    def test_requires_base_path(self) -> None:
        write_json(self.config, {"custName": "Fixture Customer"})
        with self.assertRaises(CleanupError):
            resolve_output(self.config)

    def test_rejects_symlink_when_supported(self) -> None:
        target = self.project / "outside.txt"
        target.write_text("outside\n", encoding="utf-8")
        link = self.output / "link.txt"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("Symbolic links are unavailable")
        with self.assertRaises(CleanupError):
            inventory(self.config)
        self.assertTrue(target.is_file())

    def test_deletes_read_only_file(self) -> None:
        path = self.output / "readonly.txt"
        path.write_text("read only\n", encoding="utf-8")
        os.chmod(path, stat.S_IREAD)
        plan = inventory(self.config)
        result = execute_cleanup(self.config, plan.fingerprint, CONFIRMATION)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(self.output.is_dir())

    def test_partial_failure_reports_deleted_progress(self) -> None:
        plan = inventory(self.config)
        real_unlink = Path.unlink
        calls = 0

        def fail_second(path: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise CleanupError("simulated deletion failure")
            real_unlink(path)

        with patch("cleanup_output.unlink_file", side_effect=fail_second):
            with self.assertRaises(PartialCleanupError) as captured:
                execute_cleanup(self.config, plan.fingerprint, CONFIRMATION)
        error = captured.exception
        self.assertEqual(error.deleted_files, 1)
        self.assertGreater(error.deleted_bytes, 0)
        self.assertTrue(error.output_root.is_dir())


if __name__ == "__main__":
    unittest.main()
