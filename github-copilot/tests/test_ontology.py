from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path, PurePosixPath


PLUGIN = Path(__file__).resolve().parents[1]
REPOSITORY = PLUGIN.parent
ONTOLOGY = PLUGIN / "ontology"
NAMESPACE = "urn:lisa:copilot:ontology:"


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def values(value: object) -> list:
    return value if isinstance(value, list) else [value]


class OntologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads(
            (ONTOLOGY / "lisa-ontology.jsonld").read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
        )
        cls.context = cls.document["@context"]
        cls.graph = cls.document["@graph"]
        cls.nodes = {node["@id"]: node for node in cls.graph}

    def nodes_of_type(self, name: str) -> list[dict]:
        return [
            node for node in self.graph
            if name in values(node.get("@type", []))
        ]

    def test_self_contained_context_and_unique_identifiers(self) -> None:
        self.assertIsInstance(self.context, dict)
        self.assertEqual(1.1, self.context["@version"])
        self.assertEqual(NAMESPACE, self.context["@vocab"])
        self.assertEqual(NAMESPACE, self.context["lisa"])
        self.assertEqual(len(self.graph), len(self.nodes))
        for node in self.graph:
            with self.subTest(node=node["@id"]):
                self.assertRegex(node["@id"], r"^lisa:[A-Za-z][A-Za-z0-9-]*$")
                self.assertTrue(node.get("label"))
                self.assertTrue(node.get("@type"))
        for key, definition in self.context.items():
            with self.subTest(term=key):
                if key.startswith("@"):
                    self.assertIn(key, {"@version", "@vocab"})
                elif isinstance(definition, dict):
                    self.assertEqual("@id", definition["@type"])
                    self.assertIn(definition.get("@container"), {None, "@list", "@set"})
                else:
                    self.assertIsInstance(definition, str)

    def test_terms_types_and_object_references_are_declared(self) -> None:
        for node in self.graph:
            for type_id in values(node["@type"]):
                if type_id.startswith("lisa:"):
                    self.assertIn(type_id, self.nodes)
                    self.assertEqual("rdfs:Class", self.nodes[type_id]["@type"])
            for term, value in node.items():
                if term.startswith("@"):
                    continue
                definition = self.context.get(term)
                predicate = (
                    definition["@id"] if isinstance(definition, dict)
                    else definition or f"lisa:{term}"
                )
                with self.subTest(node=node["@id"], term=term):
                    if predicate.startswith("lisa:"):
                        self.assertIn(predicate, self.nodes)
                        self.assertEqual("rdf:Property", self.nodes[predicate]["@type"])
                    if isinstance(definition, dict) and definition["@type"] == "@id":
                        for target in values(value):
                            self.assertIsInstance(target, str)
                            if target.startswith("lisa:"):
                                self.assertIn(target, self.nodes)
                            else:
                                self.assertRegex(target, r"^(rdf|rdfs|owl|xsd|prov):")

    def test_literal_property_types(self) -> None:
        literal_types = {
            "xsd:string": str,
            "xsd:boolean": bool,
            "xsd:integer": int,
        }
        for node in self.graph:
            for term, value in node.items():
                definition = self.nodes.get(f"lisa:{term}", {})
                expected = literal_types.get(definition.get("range"))
                if expected is not None:
                    for item in values(value):
                        with self.subTest(node=node["@id"], term=term):
                            self.assertIs(type(item), expected)

    def test_object_property_domains_and_ranges(self) -> None:
        def is_instance(node: dict, expected: str) -> bool:
            pending = values(node["@type"]).copy()
            visited: set[str] = set()
            while pending:
                current = pending.pop()
                if current == expected:
                    return True
                if current not in visited:
                    visited.add(current)
                    pending.extend(values(self.nodes.get(current, {}).get("subClassOf", [])))
            return False

        for node in self.graph:
            for term, value in node.items():
                context = self.context.get(term)
                if not isinstance(context, dict) or not context["@id"].startswith("lisa:"):
                    continue
                definition = self.nodes[context["@id"]]
                with self.subTest(node=node["@id"], term=term):
                    self.assertTrue(is_instance(node, definition["domain"]))
                    if context.get("@container") == "@list":
                        self.assertEqual("rdf:List", definition["range"])
                        self.assertIsInstance(value, list)
                        expected = "lisa:StageDefinition"
                    else:
                        expected = definition["range"]
                    for target in values(value):
                        self.assertTrue(is_instance(self.nodes[target], expected), target)

    def test_source_references_exist_and_anchors_match(self) -> None:
        for source in self.nodes_of_type("lisa:SourceReference"):
            with self.subTest(source=source["@id"]):
                relative = PurePosixPath(source["sourcePath"])
                self.assertFalse(relative.is_absolute())
                self.assertNotIn("..", relative.parts)
                self.assertNotIn("scout", [part.casefold() for part in relative.parts])
                path = REPOSITORY.joinpath(*relative.parts)
                self.assertTrue(path.is_file(), str(path))
                lines = path.read_text(encoding="utf-8-sig").splitlines()
                start = source["lineStart"]
                end = source.get("lineEnd", len(lines))
                self.assertGreaterEqual(start, 1)
                self.assertGreaterEqual(end, start)
                self.assertLessEqual(end, len(lines))
                if "anchor" in source:
                    self.assertIn(source["anchor"], "\n".join(lines[start - 1:end]))

    def test_architecture_individuals_have_provenance(self) -> None:
        exempt_types = {
            "rdfs:Class", "rdf:Property", "lisa:SourceReference", "lisa:EnforcementLevel"
        }
        for node in self.graph:
            if set(values(node["@type"])) & exempt_types:
                continue
            with self.subTest(node=node["@id"]):
                self.assertTrue(node.get("source"))
                for source in values(node["source"]):
                    self.assertEqual("lisa:SourceReference", self.nodes[source]["@type"])

    def test_skill_and_contract_inventory_matches_packaged_source(self) -> None:
        packaged = {
            path.parent.name
            for path in (PLUGIN / "skills").glob("*/SKILL.md")
        }
        skills = self.nodes_of_type("lisa:Skill")
        self.assertEqual(packaged, {node["codeValue"] for node in skills})
        self.assertEqual(len(packaged), len(skills))
        self.assertEqual(
            len(packaged), len(self.nodes_of_type("lisa:ArtifactContract"))
        )
        for skill in skills:
            with self.subTest(skill=skill["codeValue"]):
                contract = json.loads(
                    (PLUGIN / "skills" / skill["codeValue"] / "resources"
                     / "artifact-contract.json").read_text(encoding="utf-8")
                )
                modeled = self.nodes[skill["artifactContract"]]
                self.assertEqual(contract["skill"], modeled["codeValue"])
                self.assertEqual(contract["stage"], modeled["category"])
                self.assertEqual(contract["rootFolder"], modeled.get("rootFolder"))
                self.assertEqual(contract["producesArtifacts"], modeled["producesArtifacts"])
                self.assertEqual(contract.get("manifest"), modeled.get("manifestName"))
                self.assertEqual(contract["allowedStatuses"], modeled["allowedStatus"])

    def test_stage_registry_and_order_match_checkpoint_code(self) -> None:
        tree = ast.parse(
            (PLUGIN / "skills" / "workflow_checkpoint.py").read_text(encoding="utf-8")
        )
        assignment = next(
            node for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "STAGES"
                    for target in node.targets)
        )
        stages = list(ast.literal_eval(assignment.value))
        order = self.nodes["lisa:cad-workflow"]["stageOrder"]
        self.assertEqual(stages, [self.nodes[node]["codeValue"] for node in order])
        self.assertEqual(len(stages), len(set(order)))
        self.assertEqual(len(stages), len(self.nodes_of_type("lisa:StageDefinition")))
        for stage in order:
            owners = [node for node in self.nodes_of_type("lisa:Skill")
                      if node.get("performsStage") == stage]
            self.assertEqual(1, len(owners), stage)
            marker = self.nodes[self.nodes[stage]["completionMarker"]]
            self.assertEqual("lisa:ArtifactSpec", marker["@type"])
        for name in ("cad-orchestrator", "video-generator"):
            self.assertNotIn("performsStage", self.nodes[f"lisa:skill-{name}"])

    def test_status_vocabularies_match_schemas(self) -> None:
        schema = json.loads(
            (PLUGIN / "skills" / "workflow-checkpoint.schema.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(
            schema["properties"]["status"]["enum"],
            self.nodes["lisa:workflow-statuses"]["allowedStatus"],
        )
        self.assertEqual(
            schema["properties"]["completedStages"]["additionalProperties"]
            ["properties"]["status"]["enum"],
            self.nodes["lisa:stage-completion-statuses"]["allowedStatus"],
        )
        observations = json.loads(
            (PLUGIN / "skills" / "agent-evaluator" / "resources"
             / "evaluation-observations.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            observations["properties"]["optimizerHandoff"]["properties"]
            ["evaluationDecision"]["enum"],
            self.nodes["lisa:evaluation-decisions"]["allowedStatus"],
        )

    def test_host_target_and_marker_distinctions(self) -> None:
        self.assertEqual(
            {"lisa:host-copilot-cli", "lisa:host-agency"},
            {node["@id"] for node in self.nodes_of_type("lisa:ExecutionHost")},
        )
        self.assertEqual(
            {"Standard", "GitHub Copilot", "Copilot chat"},
            {node["codeValue"] for node in self.nodes_of_type("lisa:Harness")},
        )
        self.assertNotIn("hasHarness", self.nodes["lisa:platform-cowork"])
        self.assertEqual(
            "lisa:artifact-publication-record",
            self.nodes["lisa:stage-publication"]["completionMarker"],
        )
        self.assertEqual(
            "publication-manifest.json",
            self.nodes["lisa:contract-artifact-publisher"]["manifestName"],
        )
        cleanup_marker = self.nodes[
            self.nodes["lisa:stage-cleanup"]["completionMarker"]
        ]
        self.assertTrue(cleanup_marker["pathPattern"].startswith(".lisa/"))
        self.assertFalse(
            self.nodes["lisa:contract-postpublish-cleanup"]["producesArtifacts"]
        )

    def test_local_documentation_links_resolve(self) -> None:
        document = (ONTOLOGY / "README.md").read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document):
            if target.startswith(("https://", "http://", "#")):
                continue
            relative, _, fragment = target.partition("#")
            path = (ONTOLOGY / relative).resolve()
            with self.subTest(link=target):
                self.assertTrue(path.is_file(), str(path))
                if fragment:
                    self.assertRegex(fragment, r"^L[1-9][0-9]*$")
                    self.assertLessEqual(
                        int(fragment[1:]),
                        len(path.read_text(encoding="utf-8-sig").splitlines()),
                    )


if __name__ == "__main__":
    unittest.main()
