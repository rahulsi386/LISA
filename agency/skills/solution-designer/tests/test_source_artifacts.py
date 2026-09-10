from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import source_artifacts as sources


class SourceArtifactTests(unittest.TestCase):
    def setUp(self):
        self.work = ROOT / "tests" / (".source-artifacts-" + uuid.uuid4().hex)
        self.work.mkdir()
        self.addCleanup(shutil.rmtree, self.work)
        self.model_path = self.work / "design-model.json"
        self.output = self.work / "design"
        component = {
            "layer": "agent-platform", "kind": "agent", "status": "to-create",
            "implementationStatus": "simulate", "buildOwner": "agent-builder",
            "pocScope": "represented", "productionStatus": "gap",
            "iconKey": "generic-component", "description": "Exact description",
            "evidenceIds": ["E-001", "E-002"],
        }
        self.model = {
            "scenarioSlug": "Source_Test", "title": "Source stage test",
            "summary": "One model, the same two diagrams.",
            "complexity": "High", "referenceKeys": ["architecture-diagrams"],
            "coverage": {"nativeBuildPercent": 0, "pocDemonstrationPercent": 100},
            "components": [
                {**component, "id": "requester", "name": "Requester"},
                {**component, "id": "agent", "name": "Exact agent name"},
            ],
            "relationships": [
                {"id": "r-" + mode, "from": "requester", "to": "agent", "label": "Exact action",
                 "style": "call", "implementationMode": mode, "evidenceIds": ["E-001"]}
                for mode in sources.MODES
            ],
            "sequence": [
                {"id": "s-" + mode, "from": "requester", "to": "agent", "label": "Exact message",
                 "type": "call", "implementationMode": mode, "phase": "Execution", "evidenceIds": ["E-002"]}
                for mode in sources.MODES
            ],
        }
        self.model["relationships"].append({
            "id": "r-self", "from": "agent", "to": "agent", "label": "Reason locally",
            "style": "call", "implementationMode": "real",
        })
        self.model["sequence"].append({
            "id": "s-self", "from": "agent", "to": "agent", "label": "Reason locally",
            "type": "self", "implementationMode": "real", "phase": "Response",
        })
        self.save_model()

    def save_model(self):
        self.model_path.write_text(json.dumps(self.model, ensure_ascii=False), encoding="utf-8")

    def cli(self, command="generate", expected=0):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "source_artifacts.py"), command,
             "--model", str(self.model_path), "--output", str(self.output)],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def generate(self):
        self.save_model()
        return sources.generate(self.model_path, self.output)

    def source_path(self, kind):
        return self.output / sources.Design(self.model).filenames[kind]

    def refresh_report_hash(self, kind):
        path = self.output / "source-report.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["sources"][kind].update(
            sha256=sources.sha256(self.source_path(kind)), bytes=self.source_path(kind).stat().st_size,
        )
        if kind == "drawio":
            report["stageDetails"][1]["inputSha256"] = report["sources"][kind]["sha256"]
        path.write_text(json.dumps(report), encoding="utf-8")

    def test_cli_creates_two_editable_pages_then_mermaid_with_hashed_stage_order(self):
        report = self.cli()
        self.assertEqual(report, self.cli("validate"))
        self.assertEqual(report["stages"], ["drawio", "mermaid"])
        self.assertEqual([stage["order"] for stage in report["stageDetails"]], [1, 2])
        self.assertEqual(report["artifactOrder"], [
            "Design_Source_Test.drawio", "SA_Source_Test.mmd", "SD_Source_Test.mmd", "source-report.json",
        ])
        self.assertEqual(report["model"]["sha256"], hashlib.sha256(self.model_path.read_bytes()).hexdigest())
        for entry in report["sources"].values():
            self.assertEqual(entry["sha256"], sources.sha256(self.output / entry["path"]))
            self.assertEqual(Path(entry["path"]).name, entry["path"])
        self.assertEqual(report["stageDetails"][1]["inputSha256"], report["sources"]["drawio"]["sha256"])
        document = ET.parse(self.source_path("drawio")).getroot()
        self.assertEqual([page.get("name") for page in document], list(sources.PAGES))
        for index, page in enumerate(document):
            cells = page.findall("mxGraphModel/root/mxCell")
            identities = {cell.get("id") for cell in cells}
            nodes = [cell for cell in cells if cell.get("lisaRole") == ("component" if index == 0 else "participant")]
            self.assertEqual([node.get("lisaId") for node in nodes], ["requester", "agent"])
            self.assertTrue(all(node.get("vertex") == "1" for node in nodes))
            edges = [cell for cell in cells if cell.get("edge") == "1"]
            self.assertEqual(len(edges), len(self.model["relationships" if index == 0 else "sequence"]))
            for edge in edges:
                self.assertIn(edge.get("source"), identities)
                self.assertIn(edge.get("target"), identities)
                self.assertIn("edgeStyle=orthogonalEdgeStyle;", edge.get("style"))
            self.assertFalse(page.findall(".//svg"))
            self.assertFalse(any("image=" in cell.get("style", "") for cell in cells))

    def test_packaged_models_remain_compatible_and_sources_are_deterministic(self):
        for fixture in (ROOT / "resources" / "design-model.example.json",
                        ROOT / "tests" / "fixtures" / "procurement-reference-model.json"):
            with self.subTest(fixture=fixture.name):
                self.model = json.loads(fixture.read_text(encoding="utf-8"))
                first_report = self.generate()
                first_bytes = {key: self.source_path(key).read_bytes() for key in first_report["sources"]}
                self.assertEqual(first_report, self.generate())
                self.assertEqual(first_bytes, {key: self.source_path(key).read_bytes() for key in first_report["sources"]})

    def test_exact_sources_and_model_validate_after_copy_to_candidate_directory(self):
        report = self.generate()
        candidate = self.work / ".candidates" / "Balanced" / "design"
        candidate.mkdir(parents=True)
        copied_model = candidate / self.model_path.name
        shutil.copy2(self.model_path, copied_model)
        for name in report["artifactOrder"]:
            shutil.copy2(self.output / name, candidate / name)
        self.assertEqual(sources.validate(copied_model, candidate), report)
        self.assertEqual(report["model"]["path"], copied_model.name)
        self.assertEqual(report["model"]["sha256"], sources.sha256(copied_model))
        report_text = (candidate / "source-report.json").read_text(encoding="utf-8")
        self.assertNotIn(str(self.work), report_text)
        self.assertEqual((candidate / "source-report.json").read_bytes(),
                         (self.output / "source-report.json").read_bytes())
        for entry in report["sources"].values():
            self.assertEqual(Path(entry["path"]).name, entry["path"])
            self.assertEqual(entry["sha256"], sources.sha256(candidate / entry["path"]))

    def test_exact_names_evidence_status_modes_and_disclosure_are_visible_and_injection_safe(self):
        dangerous = 'end; --> "quoted" <script>alert(1)</script> & \'quote\'\nclick n0001 "bad"; Ω 東京 😀 #59; <br/>\u0085\u2028\u2029  '
        self.model["components"][1]["name"] = dangerous
        self.model["components"][1]["description"] = dangerous
        self.model["components"][1]["evidenceIds"] = [dangerous]
        self.model["sequence"][1]["label"] = dangerous
        self.model["sequence"][1]["simulationDisclosure"] = "No data was transmitted to the external system."
        self.model["relationships"][1]["label"] = dangerous
        report = self.generate()
        self.assertEqual(report["validation"], "passed")
        document = ET.parse(self.source_path("drawio")).getroot()
        labels = [cell.get("value", "") for cell in document.findall(".//mxCell")]
        self.assertTrue(any(value.startswith(dangerous) for value in labels))
        self.assertFalse(document.findall(".//script"))
        self.assertTrue(any("implementationStatus: simulate" in value for value in labels))
        self.assertTrue(any("No data was transmitted to the external system." in value for value in labels))
        architecture = self.source_path("architectureMermaid").read_text(encoding="utf-8")
        sequence = self.source_path("sequenceMermaid").read_text(encoding="utf-8")
        self.assertNotIn("<script>", architecture + sequence)
        self.assertNotIn("\nclick ", architecture + sequence)
        architecture_events = sources.parse_mermaid(architecture, "flowchart LR")
        sequence_events = sources.parse_mermaid(sequence, "sequenceDiagram")
        self.assertTrue(any(event[0] == "node" and event[2].startswith(dangerous) for event in architecture_events))
        self.assertIn(("participant", "p0002", dangerous), sequence_events)
        self.assertTrue(any(event[0] == "message" and event[-1].startswith("Simulated: " + dangerous) for event in sequence_events))
        for text in [dangerous, "end END End", "#34; #101;nd", "a\r\nb\tc", "A --> B;"]:
            self.assertEqual(sources.mermaid_unescape(sources.mermaid_escape(text)), text)

    def test_complete_per_occurrence_ids_modes_and_directed_multiedges(self):
        for collection in ("relationships", "sequence"):
            legacy = copy.deepcopy(self.model[collection][0])
            legacy.pop("id")
            self.model[collection].extend([copy.deepcopy(legacy), copy.deepcopy(legacy)])
        self.model["relationships"][2].update({"from": "agent", "to": "requester"})
        report = self.generate()
        for collection in ("relationships", "sequence"):
            coverage = report["coverage"][collection]
            self.assertEqual(len(coverage), len(self.model[collection]))
            self.assertEqual(len({item["id"] for item in coverage}), len(coverage))
            self.assertEqual([item["implementationMode"] for item in coverage],
                             [item["implementationMode"] for item in self.model[collection]])
            self.assertEqual([item["id"] for item in coverage[:6]],
                             [item["id"] for item in self.model[collection][:6]])
        events = sources.parse_mermaid(self.source_path("architectureMermaid").read_text(encoding="utf-8"), "flowchart LR")
        edges = [event for event in events if event[0] == "edge"]
        self.assertEqual(len(edges), len(self.model["relationships"]))
        self.assertEqual(edges[2][1:3], ("n0002", "n0001"))
        self.assertEqual(edges[-2][1:3], edges[-1][1:3])
        self.assertNotEqual(edges[-2][-1], edges[-1][-1])

    def test_self_messages_phases_fragments_and_branches_are_balanced(self):
        fragments = ["alt accepted", "alt accepted", "else rejected", "else rejected", "Unspecified boundary", None]
        for record, fragment in zip(self.model["sequence"], fragments):
            record["fragment"] = fragment
        self.generate()
        text = self.source_path("sequenceMermaid").read_text(encoding="utf-8")
        events = sources.parse_mermaid(text, "sequenceDiagram")
        self.assertIn(("fragment", "alt", "accepted"), events)
        self.assertIn(("fragment", "else", "rejected"), events)
        self.assertEqual(sum(event[0] == "end" for event in events), 2)
        self.assertIn(("group",), events)
        self.assertFalse(any(event[:2] == ("fragment", "opt") for event in events))
        self.assertTrue(any(event[0] == "note" and event[-1] == "Phase: Response" for event in events))
        self.assertTrue(any(event[0] == "message" and event[1] == event[2] == "p0002" for event in events))
        for block, branch in (("par", "and"), ("critical", "option"), ("loop", None), ("opt", None), ("break", None)):
            with self.subTest(block=block):
                self.model["sequence"][0]["fragment"] = block + " condition"
                for item in self.model["sequence"][1:]:
                    item["fragment"] = (branch + " alternative") if branch else (block + " condition")
                self.generate()
                sources.parse_mermaid(self.source_path("sequenceMermaid").read_text(encoding="utf-8"), "sequenceDiagram")

    def test_bidirectional_relationship_has_two_arrowheads_but_one_canonical_occurrence(self):
        self.model["relationships"][0]["direction"] = "bidirectional"
        self.model["relationships"][1]["direction"] = "unidirectional"
        report = self.generate()
        self.assertEqual(len(report["coverage"]["relationships"]), len(self.model["relationships"]))
        self.assertEqual(report["coverage"]["relationships"][0]["direction"], "bidirectional")
        tree = ET.parse(self.source_path("drawio"))
        edges = tree.findall(".//mxCell[@lisaRole='relationship']")
        self.assertEqual(len(edges), len(self.model["relationships"]))
        self.assertIn("startArrow=block;", edges[0].get("style"))
        self.assertIn("endArrow=block;", edges[0].get("style"))
        self.assertNotIn("startArrow=block;", edges[1].get("style"))
        path = self.source_path("architectureMermaid")
        text = path.read_text(encoding="utf-8")
        events = sources.parse_mermaid(text, "flowchart LR")
        links = [event for event in events if event[0] == "edge"]
        self.assertEqual(links[0][1:4], ("n0001", "n0002", "<-->"))
        self.assertEqual(links[1][1:4], ("n0001", "n0002", "-->"))
        self.assertEqual(len(links), len(self.model["relationships"]))
        path.write_text(text.replace(" <-->|", " -->|", 1), encoding="utf-8")
        self.refresh_report_hash("architectureMermaid")
        with self.assertRaisesRegex(sources.SourceValidationError, "directed multiedges"):
            sources.validate(self.model_path, self.output)

    def test_explicit_participant_order_is_preserved_without_extra_architecture_nodes(self):
        self.model["components"].append({**self.model["components"][0], "id": "unused", "name": "Unused control"})
        self.model["sequenceParticipants"] = ["agent", "requester"]
        report = self.generate()
        self.assertEqual(report["coverage"]["componentIds"], ["requester", "agent", "unused"])
        self.assertEqual(report["coverage"]["participantIds"], ["agent", "requester"])
        events = sources.parse_mermaid(self.source_path("sequenceMermaid").read_text(encoding="utf-8"), "sequenceDiagram")
        self.assertEqual([event[2] for event in events if event[0] == "participant"], ["Exact agent name", "Requester"])

    def test_extended_topology_fields_remain_visible_without_synthesizing_branches(self):
        details = {
            "roleDescription": "Coordinates the evidenced request",
            "productService": "Exact product/service", "hostingRuntime": "Exact managed runtime",
            "deploymentBoundary": "Customer tenant", "trustBoundaries": ["External service boundary"],
            "inventoryNames": ["Exact tool API v1", "Exact customer record store"],
            "members": ["Exact grouped member"], "allowedToolScope": "represented",
            "productionGaps": ["Customer-managed authentication required"],
            "presentation": {"primary": True},
        }
        self.model["components"][1].update(details)
        self.model["relationships"][0]["relationshipType"] = "request-routing"
        self.model["sequence"][0].update({
            "order": 1, "relationshipId": "r-real", "condition": "An approval is required",
            "actionControl": {"humanApprovalRequired": True, "owner": "Customer"},
        })
        self.generate()
        recovered = sources.validate_drawio(
            self.source_path("drawio"), sources.Design(self.model), sources.sha256(self.model_path),
        )
        self.assertEqual(recovered.model, self.model)
        architecture = sources.parse_mermaid(
            self.source_path("architectureMermaid").read_text(encoding="utf-8"), "flowchart LR",
        )
        label = next(event[2] for event in architecture if event[:2] == ("node", "n0002"))
        for key, value in details.items():
            self.assertIn(f"{key}: {sources.display(value)}", label)
        sequence = sources.parse_mermaid(
            self.source_path("sequenceMermaid").read_text(encoding="utf-8"), "sequenceDiagram",
        )
        self.assertFalse(any(event[0] in {"fragment", "group"} for event in sequence))
        first_message = next(event[-1] for event in sequence if event[0] == "message")
        self.assertIn("relationshipId: r-real", first_message)
        self.assertIn("condition: An approval is required", first_message)
        self.assertIn("actionControl:", first_message)

    def test_nested_raw_simulation_disclosures_are_preserved_never_inferred(self):
        disclosure = "No data was transmitted to the external system."
        self.model["sequence"][1].update({
            "branchKind": "simulation", "simulationDisclosure": None,
            "actionControl": {"simulation_disclosure": disclosure, "approval_required": True},
        })
        self.model["actionControls"] = [{
            "capabilityId": "CAP-001",
            "buildContract": {"simulation_disclosure": disclosure},
        }]
        report = self.generate()
        self.assertEqual(report["coverage"]["participantIds"], ["requester", "agent"])
        sequence = sources.parse_mermaid(
            self.source_path("sequenceMermaid").read_text(encoding="utf-8"), "sequenceDiagram",
        )
        message = [event[-1] for event in sequence if event[0] == "message"][1]
        self.assertTrue(message.startswith("Simulated: "))
        self.assertIn("branchKind: simulation", message)
        self.assertIn("simulationDisclosure: null", message)
        self.assertIn('"simulation_disclosure":"' + disclosure + '"', message)
        self.assertFalse(any(event[0] in {"fragment", "group"} for event in sequence))
        document = ET.parse(self.source_path("drawio")).getroot()
        context = document.find(".//mxCell[@lisaRole='context']").get("value")
        self.assertIn('"buildContract":{"simulation_disclosure":"' + disclosure + '"}', context)
        self.model.pop("actionControls")
        self.model["sequence"][1].pop("actionControl")
        self.generate()
        sequence = sources.parse_mermaid(
            self.source_path("sequenceMermaid").read_text(encoding="utf-8"), "sequenceDiagram",
        )
        message = [event[-1] for event in sequence if event[0] == "message"][1]
        self.assertTrue(message.startswith("Simulated: "))
        self.assertNotIn(disclosure, message)
        self.assertNotIn("success", message.casefold())

    def test_drawio_visible_label_tamper_fails_even_with_refreshed_report_hash(self):
        self.generate()
        path = self.source_path("drawio")
        tree = ET.parse(path)
        node = tree.find(".//mxCell[@lisaRole='component']")
        node.set("value", node.get("value").replace("Requester", "Renamed requester"))
        tree.write(path, encoding="utf-8", xml_declaration=True)
        self.refresh_report_hash("drawio")
        failure = self.cli("validate", expected=1)
        self.assertIn("visible label", failure["validationIssues"][0])

    def test_drawio_actual_edge_endpoint_tamper_fails_without_metadata_changes(self):
        self.generate()
        path = self.source_path("drawio")
        tree = ET.parse(path)
        edge = tree.find(".//mxCell[@lisaRole='relationship']")
        edge.set("target", edge.get("source"))
        tree.write(path, encoding="utf-8", xml_declaration=True)
        self.refresh_report_hash("drawio")
        with self.assertRaisesRegex(sources.SourceValidationError, "edge/mode"):
            sources.validate(self.model_path, self.output)

    def test_drawio_sequence_anchor_and_visible_time_tampering_fail(self):
        for attribute, value in (("x", "75"), ("y", "0")):
            with self.subTest(attribute=attribute):
                self.generate()
                path = self.source_path("drawio")
                tree = ET.parse(path)
                anchor = tree.find(".//mxCell[@id='sd-message-0001-to']/mxGeometry")
                anchor.set(attribute, value)
                tree.write(path, encoding="utf-8", xml_declaration=True)
                self.refresh_report_hash("drawio")
                with self.assertRaisesRegex(sources.SourceValidationError, "anchor"):
                    sources.validate(self.model_path, self.output)

    def test_mermaid_edge_loss_and_disclosure_tampering_cannot_hide_behind_hashes(self):
        for kind, change in (
            ("architectureMermaid", lambda text: text.replace("n0001 -->|", "n0002 -->|", 1)),
            ("sequenceMermaid", lambda text: text.replace("Simulated: ", "", 1)),
            ("sequenceMermaid", lambda text: text + "    click p0001 call danger()\n"),
        ):
            with self.subTest(kind=kind):
                self.generate()
                path = self.source_path(kind)
                path.write_text(change(path.read_text(encoding="utf-8")), encoding="utf-8")
                self.refresh_report_hash(kind)
                with self.assertRaises(sources.SourceValidationError):
                    sources.validate(self.model_path, self.output)

    def test_hash_and_stage_checks_are_recomputed(self):
        self.generate()
        path = self.source_path("architectureMermaid")
        path.write_text(path.read_text(encoding="utf-8").replace("    ", "  "), encoding="utf-8")
        with self.assertRaisesRegex(sources.SourceValidationError, "hashes"):
            sources.validate(self.model_path, self.output)
        self.generate()
        report_path = self.output / "source-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["stages"].reverse()
        report_path.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(sources.SourceValidationError, "stage order"):
            sources.validate(self.model_path, self.output)
        self.generate()
        self.model["components"][0]["evidenceIds"].append("NEW-EVIDENCE")
        self.save_model()
        with self.assertRaisesRegex(sources.SourceValidationError, "provenance"):
            sources.validate(self.model_path, self.output)

    def test_gates_run_in_order_and_failure_never_publishes_success_report(self):
        self.output.mkdir()
        with mock.patch.object(sources, "validate_drawio", side_effect=sources.SourceValidationError("drawio gate")):
            with self.assertRaisesRegex(sources.SourceValidationError, "drawio gate"):
                sources.generate(self.model_path, self.output)
        self.assertTrue(self.source_path("drawio").is_file())
        self.assertFalse(self.source_path("architectureMermaid").exists())
        self.assertFalse(self.source_path("sequenceMermaid").exists())
        self.assertFalse((self.output / "source-report.json").exists())
        self.generate()
        with mock.patch.object(sources, "validate_mermaid", side_effect=sources.SourceValidationError("mermaid gate")):
            with self.assertRaisesRegex(sources.SourceValidationError, "mermaid gate"):
                sources.generate(self.model_path, self.output)
        self.assertFalse((self.output / "source-report.json").exists())

    def test_unsafe_ids_missing_endpoints_and_invalid_xml_are_rejected(self):
        for mutate in (
            lambda model: model.update(scenarioSlug="../outside"),
            lambda model: model["relationships"][0].update({"to": "unknown"}),
            lambda model: model["sequence"][0].update(implementationMode="live"),
            lambda model: model["components"][0].update(name="bad\x00name"),
            lambda model: model["relationships"][1].update(id=model["relationships"][0]["id"]),
        ):
            candidate = copy.deepcopy(self.model)
            mutate(candidate)
            with self.assertRaises(sources.SourceValidationError):
                sources.Design(candidate)


if __name__ == "__main__":
    unittest.main()
