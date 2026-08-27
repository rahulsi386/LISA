from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = SKILL_ROOT.parent
sys.path.insert(0, str(SKILLS_ROOT))

from validate_artifact_contracts import validate_contract  # noqa: E402

INSTRUCTIONS = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")

# The delivery order the orchestrator must preserve.
STAGE_ORDER = [
    "/requirement-analyzer",
    "/complexity-classifier",
    "/solution-designer",
    "/agent-builder",
    "/agent-evaluator",
    "/agent-optimizer",
    "/artifact-generator",
    "/artifact-publisher",
]


class CadOrchestratorContractTests(unittest.TestCase):
    def test_contract_is_valid_and_produces_no_artifacts(self) -> None:
        contract = validate_contract(SKILL_ROOT)
        self.assertEqual("cad-orchestrator", contract["skill"])
        self.assertEqual("orchestration", contract["stage"])
        self.assertIsNone(contract["rootFolder"])
        self.assertFalse(contract["producesArtifacts"])
        self.assertEqual([], contract["files"])

    def test_every_stage_skill_appears_exactly_once_in_order(self) -> None:
        positions = []
        for skill in STAGE_ORDER:
            found = [m.start() for m in re.finditer(re.escape(skill + "`"), INSTRUCTIONS)]
            self.assertEqual(1, len(found), f"{skill} must appear exactly once")
            positions.append(found[0])
        self.assertEqual(
            sorted(positions), positions, "stage skills are out of delivery order"
        )

    def test_cleanup_is_gated_and_last(self) -> None:
        cleanup = INSTRUCTIONS.index("/postpublish-cleanup")
        publisher = INSTRUCTIONS.index("/artifact-publisher`")
        self.assertGreater(cleanup, publisher, "cleanup must follow publication")
        self.assertIn("(Delete/Cancel)", INSTRUCTIONS)
        self.assertIn("DELETE OUTPUT", INSTRUCTIONS)
        self.assertIn("never bypass, pre-answer, or infer it", INSTRUCTIONS)

    def test_router_does_not_hardcode_machine_paths(self) -> None:
        self.assertNotIn("C:\\Users", INSTRUCTIONS)
        self.assertNotIn("c:\\users", INSTRUCTIONS.lower())

    def test_execution_policy_is_stated_once_not_per_stage(self) -> None:
        # The anti-stall policy was duplicated per stage in the automation it replaces.
        self.assertEqual(1, INSTRUCTIONS.count("90 seconds"))
        self.assertIn("bounded phases", INSTRUCTIONS)
        self.assertIn("Do not delegate a whole skill", INSTRUCTIONS)

    def test_states_that_stage_skills_win_on_conflict(self) -> None:
        self.assertIn("the stage skill wins", INSTRUCTIONS)

    def test_classification_human_review_gate(self) -> None:
        self.assertIn("### 4.1 Classification review", INSTRUCTIONS)
        self.assertIn('"question": "How should the classification stage proceed?"', INSTRUCTIONS)
        self.assertIn('--unit-id "classification-decision"', INSTRUCTIONS)
        self.assertIn("Do not advance to design before acceptance.", INSTRUCTIONS)

    def test_build_human_review_gate(self) -> None:
        self.assertIn("### 4.2 Build review", INSTRUCTIONS)
        self.assertIn('"question": "How should the build stage proceed?"', INSTRUCTIONS)
        self.assertIn('--unit-id "build-decision"', INSTRUCTIONS)
        self.assertIn("Do not advance to evaluation before acceptance.", INSTRUCTIONS)

    def test_human_review_choices_and_stop_rule(self) -> None:
        for title in ("Accept", "Revise", "Cancel"):
            self.assertEqual(2, INSTRUCTIONS.count(f'"title": "{title}"'))
        self.assertGreaterEqual(
            INSTRUCTIONS.count("Stop immediately after the call."), 2
        )
        self.assertIn("--status WAITING", INSTRUCTIONS)
        self.assertIn("--status CANCELLED", INSTRUCTIONS)

    def test_revision_collects_free_text_and_starts_new_stage_run(self) -> None:
        self.assertIn('"question": "What should be revised in the classification?"', INSTRUCTIONS)
        self.assertIn('"question": "What should be revised in the build?"', INSTRUCTIONS)
        self.assertIn("without `answers`", INSTRUCTIONS)
        self.assertIn("with a new stage run ID", INSTRUCTIONS)


if __name__ == "__main__":
    unittest.main()
