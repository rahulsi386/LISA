from __future__ import annotations

import copy
import importlib.util
import struct
import unittest
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("designer_semantics", ROOT / "scripts" / "solution_designer.py")
designer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(designer)
FIXTURE = ROOT / "tests" / "fixtures" / "complexity-classification_20260813_120000.json"


def fixture_png(width=640, height=480, color=64) -> bytes:
    """Synthetic raster for schema/transaction tests, never an inspected diagram."""
    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value))
    pixels = (b"\0" + bytes([color, 90, 180]) * width) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def fixture_browser_evidence(module, run: dict, inspection: dict) -> None:
    """Fabricated, explicitly tagged test receipt; not a browser or visual inspection."""
    root = Path(run["stage_design"])
    slug = run["scenario_slug"]
    context = module._json_load(root / "run-report.json")["inspectionContext"]
    names = ["design-model.json", "preview.html"] + [
        f"{prefix}_{slug}.{extension}" for prefix in ("SA", "SD") for extension in ("svg", "png")
    ]
    hashes = {name: module._sha256_file(root / name) for name in names}
    screenshots, diagrams = {}, {}
    for number, key in enumerate(("architecture", "sequence", "preview")):
        filename = f"inspection-{key}.png"
        (root / filename).write_bytes(fixture_png(color=110 + number))
        asset = "preview.html" if key == "preview" else f"{'SA' if key == 'architecture' else 'SD'}_{slug}.png"
        screenshots[key] = {"path": filename, "sha256": module._sha256_file(root / filename),
                            "width": 640, "height": 480, "viewed_asset": asset}
        if key != "preview":
            width, height = module._png_dimensions(root / asset)
            ratio = min(1, 640 / width)
            diagrams[key] = {
                "src": asset, "decoded": True, "natural_width": width, "natural_height": height,
                "display_width": width * ratio, "display_height": height * ratio,
                "actual_width": width, "actual_height": height,
                "actual_size_checked": True, "fit_width_restored": True,
            }
    evidence = {
        "schema_version": "1.0", "collector": "playwright", "test_fixture": True,
        "assurance": "browser-observations-not-attestation", **context,
        "captured_at": inspection["inspected_at"], "artifact_sha256": hashes,
        "viewport": {"width": 640, "height": 480, "device_scale_factor": 1},
        "screenshots": screenshots, "diagrams": diagrams,
        "links": [{"href": name, "sha256": hashes[name], "opened": True, "decoded": True}
                  for name in names if name.endswith((".png", ".svg"))],
    }
    module._atomic_write_json(root / "browser-evidence.json", evidence)
    inspection["browser_evidence"] = {"path": "browser-evidence.json",
                                    "sha256": module._sha256_file(root / "browser-evidence.json")}


def topology_classification() -> dict:
    classification = designer._json_load(FIXTURE)
    nodes = [
        ("requester", "Analyst", "actor", "existing"),
        ("teams", "Microsoft Teams", "channel", "existing"),
        ("agent", "Exact Agent Runtime", "agent", "configure"),
        ("tool", "External Analytics API", "tool", "build"),
    ]
    components = [{
        "id": identifier, "name": name, "category": category, "lifecycle": lifecycle,
        "product_service": "Microsoft Copilot Studio" if category == "agent" else name,
        "hosting_runtime": "Exact runtime", "deployment_boundary": "power-platform-environment",
        "role": "Exact role", "inventory_names": [name + " original inventory name"],
        "evidence_ids": ["REQ-001"], "reference_ids": ["REF-001"], "source_refs": ["source:1"],
    } for identifier, name, category, lifecycle in nodes]
    relationships = [{
        "id": f"rel-{number}", "source_id": source, "target_id": target,
        "relationship_type": "invokes", "interaction": "Exact interaction",
        "evidence_ids": ["REQ-001"],
    } for number, (source, target) in enumerate((("requester", "teams"), ("teams", "agent"), ("agent", "tool")), 1)]
    flows = [{
        "id": f"seq-{number}", "order": number, "phase": "Action", "source_id": source,
        "target_id": target, "action": "Exact action", "message_type": "call", "condition": None,
        "relationship_id": f"rel-{number}", "evidence_ids": ["REQ-001"],
    } for number, (source, target) in enumerate((("requester", "teams"), ("teams", "agent"), ("agent", "tool")), 1)]
    classification["solution_topology"] = {
        "architecture_summary": "Exact architecture summary.", "components": components,
        "relationships": relationships, "sequence_flows": flows,
        "trust_boundaries": [{"id": "trust-tenant", "component_ids": ["agent", "teams"], "controls": ["Exact control"]}],
        "presentation": {"primary_path": ["requester", "teams", "agent", "tool"], "primary_agent_id": "agent"},
    }
    classification["delivery_assessment"] = {
        "allowed_tools": ["Microsoft Copilot Studio", "Microsoft Teams"],
        "poc_scope": {"included_capability_ids": ["CAP-CORE", "CAP-EXTERNAL"]},
        "capabilities": [
            {"id": "CAP-CORE", "component_ids": ["teams", "agent"], "poc_treatment": "configure",
             "build_owner": "agent-builder", "implementation_status": "configurable"},
            {"id": "CAP-EXTERNAL", "component_ids": ["agent", "tool"], "poc_treatment": "static-sample-data",
             "build_owner": "external-team", "implementation_status": "demonstrable-only"},
        ],
        "production_readiness_gaps": [{"id": "PRG-ONE", "capability_ids": ["CAP-EXTERNAL"],
                                       "description": "External integration remains unavailable"}],
    }
    return classification


class ModelSemanticTests(unittest.TestCase):
    def test_current_packaged_example_satisfies_strict_model_semantics(self):
        designer._validate_model_semantics(designer._json_load(ROOT / "resources" / "design-model.example.json"))

    def model(self, classification=None):
        return designer._build_design_model(FIXTURE, classification or topology_classification())

    def test_runtime_does_not_inherit_external_sample_capability(self):
        model = self.model()
        agent = next(item for item in model["components"] if item["id"] == "agent")
        self.assertEqual(("configure", "agent-builder"), (agent["implementationStatus"], agent["buildOwner"]))
        self.assertEqual(["real", "real", "simulated"], [item["implementationMode"] for item in model["relationships"]])
        self.assertEqual([item["implementationMode"] for item in model["relationships"]],
                         [item["implementationMode"] for item in model["sequence"]])

    def test_explicit_component_delivery_metadata_overrides_independently(self):
        classification = topology_classification()
        classification["solution_topology"]["components"][2].update(
            build_owner="customer", poc_scope="represented", production_status="gap",
        )
        agent = self.model(classification)["components"][2]
        self.assertEqual("configure", agent["implementationStatus"])
        self.assertEqual(("customer", "represented", "gap"),
                         (agent["buildOwner"], agent["pocScope"], agent["productionStatus"]))

    def test_runtime_status_is_not_capability_status_and_conflicting_aliases_fail(self):
        classification = topology_classification()
        component = classification["solution_topology"]["components"][2]
        component["implementation_status"] = "native"
        with self.assertRaisesRegex(designer.DesignerError, "invalid runtime implementation_status"):
            self.model(classification)
        component.update(implementation_status="configure", poc_treatment="simulate")
        with self.assertRaisesRegex(designer.DesignerError, "disagree"):
            self.model(classification)

    def test_exact_contract_fields_and_all_inventory_names_are_preserved(self):
        classification = topology_classification()
        model = self.model(classification)
        self.assertEqual(classification["solution_topology"]["trust_boundaries"], model["trustBoundaries"])
        self.assertEqual(classification["solution_topology"]["presentation"], model["presentation"])
        self.assertEqual(classification["delivery_assessment"]["capabilities"], model["capabilityAssessments"])
        for original, normalized in zip(classification["solution_topology"]["components"], model["components"]):
            self.assertEqual(original["role"], normalized["roleDescription"])
            self.assertEqual(original["hosting_runtime"], normalized["hostingRuntime"])
            self.assertEqual(original["deployment_boundary"], normalized["deploymentBoundary"])
            self.assertTrue(set(original["inventory_names"]).issubset(normalized["members"]))
            self.assertEqual(original["reference_ids"], normalized["referenceIds"])
        self.assertNotIn("productionGaps", model["components"][0])
        self.assertIn("productionGaps", model["components"][-1])
        self.assertEqual(["rel-1", "rel-2", "rel-3"], [item["id"] for item in model["relationships"]])
        self.assertEqual(["rel-1", "rel-2", "rel-3"], [item["relationshipId"] for item in model["sequence"]])

    def test_explicit_modes_are_shared_and_disagreement_fails_closed(self):
        classification = topology_classification()
        classification["solution_topology"]["relationships"][1]["implementation_mode"] = "manual"
        model = self.model(classification)
        self.assertEqual("manual", model["sequence"][1]["implementationMode"])
        classification["solution_topology"]["sequence_flows"][1]["implementation_mode"] = "real"
        with self.assertRaisesRegex(designer.DesignerError, "disagree"):
            self.model(classification)

    def test_reverse_call_cannot_borrow_forward_relationship(self):
        model = self.model()
        model["sequence"][0]["from"], model["sequence"][0]["to"] = "teams", "requester"
        with self.assertRaisesRegex(designer.DesignerError, "directed endpoints"):
            designer._validate_model_semantics(model)
        model["sequence"][0]["type"] = "response"
        designer._validate_model_semantics(model)

    def test_self_calls_require_typed_identical_executable_endpoints(self):
        model = self.model()
        for message in (
            {"from": "agent", "to": "teams", "type": "self"},
            {"from": "agent", "to": "agent", "type": "call"},
            {"from": "requester", "to": "requester", "type": "self"},
        ):
            candidate = copy.deepcopy(model)
            candidate["sequence"].append({**message, "order": 4, "label": "Local step", "implementationMode": "real"})
            with self.assertRaisesRegex(designer.DesignerError, "Self-call"):
                designer._validate_model_semantics(candidate)

    def test_failure_branches_preserved_not_invented_from_prose(self):
        classification = topology_classification()
        flow = classification["solution_topology"]["sequence_flows"][-1]
        flow.update(branch_kind="timeout", condition="when unavailable", simulation_disclosure="Sample only; no external transmission.")
        model = self.model(classification)
        self.assertEqual(3, len(model["sequence"]))
        self.assertEqual("timeout", model["sequence"][-1]["branchKind"])
        self.assertEqual("when unavailable", model["sequence"][-1]["condition"])
        self.assertEqual(flow["simulation_disclosure"], model["sequence"][-1]["simulationDisclosure"])

    def test_high_impact_contract_omissions_require_classifier_repair(self):
        classification = topology_classification()
        capability = classification["delivery_assessment"]["capabilities"][-1]
        capability.update(action_impact="high-impact-write", build_contract={
            "approval_required": True, "error_result": "Reject failed action", "timeout_behavior": "Stop on timeout",
            "simulation_disclosure": "Sample only; no external transmission.",
        })
        with self.assertRaisesRegex(designer.DesignerError, "Classifier repair required.*approval request.*rejection branch.*simulation branch.*timeout branch"):
            self.model(classification)

    def test_complete_classified_approval_and_failure_contract_is_preserved(self):
        classification = topology_classification()
        topology = classification["solution_topology"]
        human = copy.deepcopy(topology["components"][0])
        human.update(id="approver", name="Approval authority", category="human-approval", lifecycle="existing")
        topology["components"].append(human)
        topology["relationships"].append({
            "id": "rel-approval", "source_id": "agent", "target_id": "approver",
            "relationship_type": "approves", "interaction": "Request approval",
            "implementation_mode": "manual", "evidence_ids": ["REQ-001"],
        })
        capability = classification["delivery_assessment"]["capabilities"][-1]
        capability["component_ids"].append("approver")
        capability.update(action_impact="high-impact-write", build_contract={
            "approval_required": True, "error_result": "Reject failed action", "timeout_behavior": "Stop on timeout",
            "simulation_disclosure": "Sample only; no external transmission.",
        })
        action = topology["sequence_flows"].pop()
        def step(identity, source, target, message_type, relationship, branch=None):
            item = {"id": identity, "order": len(topology["sequence_flows"]) + 1,
                    "phase": "Human decision" if "approver" in (source, target) else "Action",
                    "source_id": source, "target_id": target, "message_type": message_type,
                    "relationship_id": relationship, "capability_id": "CAP-EXTERNAL",
                    "action": identity, "condition": branch, "evidence_ids": ["REQ-001"]}
            if branch:
                item["branch_kind"] = branch
            topology["sequence_flows"].append(item)
            return item
        step("seq-approval", "agent", "approver", "approval", "rel-approval")
        step("seq-approved", "approver", "agent", "response", "rel-approval", "success")
        action["order"] = 5
        topology["sequence_flows"].append(action)
        step("seq-failure", "tool", "agent", "response", "rel-3", "failure")
        step("seq-rejected", "approver", "agent", "response", "rel-approval", "rejection")
        step("seq-timeout", "tool", "agent", "response", "rel-3", "timeout")
        step("seq-simulation", "tool", "agent", "response", "rel-3", "simulation")["simulation_disclosure"] = "Sample only; no external transmission."
        model = self.model(classification)
        self.assertEqual(len(topology["sequence_flows"]), len(model["sequence"]))
        self.assertEqual("success", model["sequence"][3]["branchKind"])
        invalid = copy.deepcopy(model)
        invalid["sequence"][3].pop("branchKind")
        with self.assertRaisesRegex(designer.DesignerError, "successful approval result before action"):
            designer._validate_model_semantics(invalid)
        invalid = copy.deepcopy(model)
        invalid["actionControls"] = []
        with self.assertRaisesRegex(designer.DesignerError, "disagree with source capability"):
            designer._validate_model_semantics(invalid)

    def test_unknown_trust_boundary_component_and_duplicate_relationship_id_fail(self):
        model = self.model()
        model["trustBoundaries"][0]["component_ids"].append("missing")
        with self.assertRaisesRegex(designer.DesignerError, "Trust boundary"):
            designer._validate_model_semantics(model)
        model = self.model()
        model["relationships"][1]["id"] = model["relationships"][0]["id"]
        with self.assertRaisesRegex(designer.DesignerError, "IDs must be unique"):
            designer._validate_model_semantics(model)

    def test_legacy_topology_ids_and_modes_are_deterministic(self):
        classification = topology_classification()
        for item in classification["solution_topology"]["relationships"]:
            del item["id"]
        for item in classification["solution_topology"]["sequence_flows"]:
            del item["id"], item["relationship_id"]
        self.assertEqual(self.model(classification), self.model(classification))
        self.assertTrue(all(item["relationshipId"].startswith("legacy-rel-") for item in self.model(classification)["sequence"]))

    def test_legacy_high_impact_contract_needs_classifier_sequence_repair(self):
        classification = topology_classification()
        del classification["solution_topology"]
        classification["delivery_assessment"]["capabilities"][-1].update(
            action_impact="high-impact-write", build_contract={
                "approval_required": True, "timeout_behavior": "Stop on timeout",
                "error_result": "No action was performed", "simulation_disclosure": "Sample data only",
            },
        )
        with self.assertRaisesRegex(designer.DesignerError, "Classifier repair required.*explicit capability-linked sequence"):
            self.model(classification)

    def test_legacy_projection_does_not_create_conditional_branches_from_prose(self):
        model = designer._build_design_model(FIXTURE, designer._json_load(FIXTURE))
        self.assertTrue(all(message.get("fragment") is None for message in model["sequence"]))


if __name__ == "__main__":
    unittest.main()
