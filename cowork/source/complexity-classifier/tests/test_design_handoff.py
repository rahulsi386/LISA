from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "design_handoff_classifier", ROOT / "scripts" / "complexity_classifier.py"
)
classifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = classifier
SPEC.loader.exec_module(classifier)


class DesignHandoffTests(unittest.TestCase):
    def topology(self):
        return {
            "components": [
                {"id": "channel", "category": "channel"},
                {"id": "agent", "category": "agent"},
            ],
            "relationships": [{
                "id": "rel-route", "source_id": "channel", "target_id": "agent",
                "relationship_type": "invokes", "direction": "unidirectional",
                "interaction": "Route prompt", "implementation_mode": "real",
            }],
            "sequence_flows": [{
                "id": "seq-route", "source_id": "channel", "target_id": "agent",
                "message_type": "call", "relationship_id": "rel-route",
                "implementation_mode": "real",
            }],
            "presentation": {"primary_agent_id": "agent", "primary_path": ["channel", "agent"]},
        }

    def test_matching_modes_and_existing_path_pass(self):
        classifier._validate_design_handoff(self.topology())

    def test_legacy_contract_remains_accepted(self):
        topology = self.topology()
        topology.pop("presentation")
        topology["sequence_flows"][0].pop("relationship_id")
        topology["sequence_flows"][0].pop("implementation_mode")
        topology["relationships"][0].pop("implementation_mode")
        classifier._validate_design_handoff(topology)

    def test_invented_primary_path_and_nonagent_fail(self):
        for presentation in (
            {"primary_path": ["agent", "channel"]},
            {"primary_path": ["unknown"]},
            {"primary_agent_id": "channel"},
        ):
            with self.subTest(presentation=presentation):
                topology = self.topology()
                topology["presentation"] = presentation
                with self.assertRaises(classifier.ClassifierError):
                    classifier._validate_design_handoff(topology)

    def test_conflicting_mode_and_wrong_relationship_fail(self):
        for change in (
            {"implementation_mode": "simulated"},
            {"relationship_id": "rel-missing"},
            {"source_id": "agent", "target_id": "channel"},
        ):
            with self.subTest(change=change):
                topology = self.topology()
                topology["sequence_flows"][0].update(change)
                with self.assertRaises(classifier.ClassifierError):
                    classifier._validate_design_handoff(topology)

    def test_duplicate_interaction_fails_but_distinct_multiedges_survive(self):
        topology = self.topology()
        duplicate = copy.deepcopy(topology["relationships"][0])
        duplicate["id"] = "rel-duplicate"
        topology["relationships"].append(duplicate)
        with self.assertRaisesRegex(classifier.ClassifierError, "Duplicate"):
            classifier._validate_design_handoff(topology)
        duplicate["relationship_type"] = "publishes-to"
        duplicate["interaction"] = "Publish agent"
        classifier._validate_design_handoff(topology)

    def test_different_protocols_do_not_get_deduplicated(self):
        topology = self.topology()
        duplicate = copy.deepcopy(topology["relationships"][0])
        duplicate.update(id="rel-async", protocol="Managed event", synchronous=False)
        topology["relationships"][0].update(protocol="HTTPS", synchronous=True)
        topology["relationships"].append(duplicate)
        classifier._validate_design_handoff(topology)

    def test_schema_accepts_explicit_modes_and_presentation(self):
        import jsonschema
        schema = json.loads((ROOT / "resources" / "classification-model.schema.json").read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        definitions = schema["$defs"]
        validator = jsonschema.Draft202012Validator({
            "$defs": definitions, "$ref": "#/$defs/presentation"
        })
        validator.validate(self.topology()["presentation"])
        with self.assertRaises(jsonschema.ValidationError):
            validator.validate({"primary_path": ["agent", "agent"]})

    def test_unknown_capability_reference_is_not_silently_ignored(self):
        topology = self.topology()
        topology["sequence_flows"][0]["capability_id"] = "CAP-999"
        with self.assertRaisesRegex(classifier.ClassifierError, "unknown capability"):
            classifier._validate_design_handoff(topology, {"CAP-001"})


if __name__ == "__main__":
    unittest.main()
