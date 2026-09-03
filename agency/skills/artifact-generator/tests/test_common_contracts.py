from __future__ import annotations

import sys
import unittest
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS_ROOT))

from validate_artifact_contracts import canonical_stage_root, validate_all  # noqa: E402


class CommonArtifactContractTests(unittest.TestCase):
    def test_all_local_skills_use_valid_common_contracts(self) -> None:
        contracts = validate_all()
        self.assertEqual(10, len(contracts))
        self.assertEqual(
            {
                "analysis",
                "classification",
                "design",
                "build",
                "evaluation",
                "optimization",
                "artifacts",
                "publication",
                "cleanup",
                "orchestration",
            },
            {contract["stage"] for contract in contracts},
        )
        for contract in contracts:
            root = contract["rootFolder"]
            if root is not None:
                self.assertEqual(root.lower(), root)

    def test_legacy_stage_folder_is_migrated_without_data_loss(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "Output"
            legacy = output / "Analysis"
            legacy.mkdir(parents=True)
            (legacy / "artifact.json").write_text("{}\n", encoding="utf-8")
            canonical = canonical_stage_root(output, "analysis")
            self.assertEqual("analysis", canonical.name)
            self.assertTrue((canonical / "artifact.json").is_file())


if __name__ == "__main__":
    unittest.main()
