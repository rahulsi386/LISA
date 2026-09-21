from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sync_skills_metadata as registry


class RegistryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.metadata = self.root / "skills-metadata.json"
        for name, value in (("ROOT", self.root), ("METADATA_PATH", self.metadata)):
            context = patch.object(registry, name, value)
            context.start()
            self.addCleanup(context.stop)
        skill = self.root / "lisa-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            '---\nname: "lisa-skill"\ndescription: "New description"\n---\nNew instructions.\n', encoding="utf-8")

    def test_fresh_install_creates_registry(self):
        result = registry.synchronize(initialize=True, skills=["lisa-skill"])
        self.assertEqual(1, result["count"])
        entry = json.loads(self.metadata.read_text())[0]
        self.assertEqual("local-lisa-skill", entry["id"])
        self.assertEqual("local", entry["scope"])
        self.assertTrue(entry["enabled"])
        self.assertEqual("New instructions.\n", entry["instructions"])
        self.assertEqual(result, registry.synchronize(initialize=True, skills=["lisa-skill"]))

    def test_upgrade_preserves_settings_and_unrelated_entries(self):
        existing = {"id": "custom-id", "name": "lisa-skill", "enabled": False, "createdAt": "keep", "scope": "local", "extra": 42}
        unrelated = {"id": "other-id", "name": "other", "instructions": "Do not change", "enabled": False}
        self.metadata.write_text(json.dumps([existing, unrelated]), encoding="utf-8")
        registry.synchronize(initialize=True, skills=["lisa-skill"])
        saved = json.loads(self.metadata.read_text())
        self.assertEqual(unrelated, saved[1])
        for key, value in existing.items():
            self.assertEqual(value, saved[0][key])

    def test_install_adds_new_skill_without_replacing_registry(self):
        unrelated = {"name": "other", "id": "other-id", "enabled": False}
        self.metadata.write_text(json.dumps([unrelated]), encoding="utf-8")
        registry.synchronize(initialize=True, skills=["lisa-skill"])
        saved = json.loads(self.metadata.read_text())
        self.assertEqual(2, len(saved))
        self.assertEqual(unrelated, saved[0])

    def test_bad_registry_is_not_overwritten(self):
        for content in ('{}', '[{"name":"duplicate"},{"name":"duplicate"}]', '[{}]', 'invalid json'):
            with self.subTest(content=content):
                self.metadata.write_text(content, encoding="utf-8")
                with self.assertRaises((registry.MetadataError, json.JSONDecodeError)):
                    registry.synchronize(initialize=True, skills=["lisa-skill"])
                self.assertEqual(content, self.metadata.read_text())

    def test_missing_requested_skill_does_not_publish(self):
        with self.assertRaises(registry.MetadataError):
            registry.synchronize(initialize=True, skills=["missing"])
        self.assertFalse(self.metadata.exists())

    def test_normal_sync_still_rejects_unknown_entries(self):
        self.metadata.write_text('[]', encoding="utf-8")
        with self.assertRaises(registry.MetadataError):
            registry.synchronize()
        self.assertEqual('[]', self.metadata.read_text())


if __name__ == "__main__":
    unittest.main()