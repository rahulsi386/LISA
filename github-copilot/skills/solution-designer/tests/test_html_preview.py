from __future__ import annotations

import json
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PreviewParser(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.feed(source)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append((tag, dict(attrs)))

    def resources(self) -> set[str]:
        return {
            value for _, attrs in self.elements
            for key, value in attrs.items()
            if key in {"href", "src"} and value and not value.startswith("#")
        }


class HtmlPreviewTests(unittest.TestCase):
    def render(self, model: dict, options: dict | None = None) -> str:
        result = subprocess.run(
            ["node", "-e", "const {createPreview}=require('./preview');"
             f"process.stdout.write(createPreview({json.dumps(model)},{json.dumps(options or {})}));"],
            cwd=ROOT / "renderer", capture_output=True, text=True, encoding="utf-8",
            timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def model(self) -> dict:
        return {
            "scenarioSlug": "Procurement_Test", "title": "Procurement",
            "summary": "Grounded guidance and controlled actions.", "complexity": "High",
            "coverage": {"nativeBuildPercent": 70, "pocDemonstrationPercent": 90},
        }

    def test_review_has_three_images_six_portable_files_and_no_scripts(self):
        html = self.render(self.model())
        parsed = PreviewParser(html)
        self.assertEqual(parsed.resources(), {
            f"{kind}_Procurement_Test.{extension}"
            for kind in ("BA", "SA", "SD") for extension in ("svg", "png")
        })
        images = [attrs for tag, attrs in parsed.elements if tag == "img"]
        self.assertEqual([image["src"] for image in images], [
            "BA_Procurement_Test.png", "SA_Procurement_Test.png", "SD_Procurement_Test.png",
        ])
        self.assertTrue(all(image.get("alt") for image in images))
        self.assertTrue(all(image.get("loading") == "eager" and image.get("decoding") == "sync" for image in images))
        self.assertFalse(any(tag in {"script", "iframe", "object", "base"} for tag, _ in parsed.elements))
        self.assertIn("default-src 'none'", html)
        self.assertIn("<title>Procurement | Architecture Review</title>", html)
        self.assertEqual(html, self.render(self.model()))

    def test_review_sections_follow_the_architecture_review_style(self):
        model = self.model()
        model.update({
            "components": [{"id": "agent", "name": "Procurement agent", "productService": "Copilot Studio",
                            "deploymentBoundary": "power-platform", "buildOwner": "agent-builder",
                            "implementationStatus": "configure", "layer": "agent-platform"}],
            "relationships": [],
            "sequence": [{"order": 1, "from": "user", "to": "agent", "label": "Ask for guidance",
                          "type": "call", "implementationMode": "real", "phase": "Request"}],
            "capabilityAssessments": [
                {"id": "CAP-001", "name": "Answer policy questions", "poc_treatment": "configure",
                 "business_priority": "must", "component_ids": ["agent"]},
                {"id": "CAP-002", "name": "Create purchase order", "poc_treatment": "simulate",
                 "business_priority": "should", "component_ids": ["agent"]},
            ],
            "productionReadinessGaps": [{"id": "PRG-ERP", "capability_ids": ["CAP-002"],
                                         "description": "ERP write access is not approved",
                                         "poc_impact": "Simulated", "production_impact": "Blocks production",
                                         "owner": "Customer"}],
            "architecturePrinciples": [{"dimension": "secure", "decision": "Least privilege everywhere."}],
            "decision": {
                "agenticPlatform": "Copilot Studio", "harness": "Standard", "codeTier": "Low-code",
                "summary": "Copilot Studio fully fits after Cowork was assessed.",
                "suitability": {"recommendation": "agentic", "summary": "Ambiguous questions need reasoning.",
                                "deterministicAlternative": "A keyword search portal."},
                "comparison": [
                    {"platform": "Microsoft Cowork", "fit": "not-fit", "selected": False, "pros": ["Personal work"],
                     "cons": ["Not shared"], "rationale": "Not a shared assistant."},
                    {"platform": "Copilot Studio", "fit": "full", "selected": True, "pros": ["Managed"],
                     "cons": ["Licensing"], "rationale": "First full fit."},
                ],
            },
        })
        html = self.render(model)
        for expected in (
            "Architecture review / decision brief", "Recommended decision",
            "Copilot Studio fully fits after Cowork was assessed.", "01 / Delivery path",
            "P1 / BUILD", "P2 / DEMONSTRATE", "Two views of one solution.", "Business overview",
            "Engineering view", "03 / Interaction sequence", "GATE 01 / PRG-ERP",
            "ERP write access is not approved", "05 / Platform decision", "An agent is warranted.",
            "Selected</span>", "Least privilege everywhere.", "Component index / 1 components",
            "Capability-to-component mapping",
        ):
            self.assertIn(expected, html)
        nav = [attrs["href"] for tag, attrs in PreviewParser(html).elements if tag == "a" and attrs.get("href", "").startswith("#")]
        self.assertEqual(nav, ["#main", "#delivery", "#solution-architecture", "#sequences", "#gates", "#decision", "#reference"])

    def test_model_text_is_escaped_in_text_and_image_attributes(self):
        model = self.model()
        model["title"] = 'Buying <script>alert("x")</script> & "quotes" \u00e9'
        model["summary"] = '<img src="https://example.invalid/x" onerror="alert(1)">'
        html = self.render(model)
        parsed = PreviewParser(html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp;", html)
        self.assertIn("\u00e9", html)
        self.assertEqual(sum(tag == "img" for tag, _ in parsed.elements), 3)
        self.assertFalse(any(tag == "script" for tag, _ in parsed.elements))
        self.assertFalse(any(key.startswith("on") for _, attrs in parsed.elements for key in attrs))
        self.assertTrue(all(not value.startswith("http") for value in parsed.resources()))
        self.assertEqual(
            next(attrs["alt"] for tag, attrs in parsed.elements if tag == "img"),
            model["title"] + " - Business architecture",
        )

    def test_view_controls_are_independent_and_accessible_without_javascript(self):
        parsed = PreviewParser(self.render(self.model()))
        inputs = [attrs for tag, attrs in parsed.elements if tag == "input"]
        labels = [attrs.get("for") for tag, attrs in parsed.elements if tag == "label"]
        checkboxes = [box for box in inputs if box["type"] == "checkbox"]
        radios = [box for box in inputs if box["type"] == "radio"]
        self.assertEqual({box["id"] for box in checkboxes}, {"business-native", "architecture-native", "sequence-native"})
        self.assertEqual([box["id"] for box in radios], ["view-business", "view-engineering"])
        self.assertIn("checked", radios[0])
        self.assertTrue(all(box["name"] == "architecture-view" for box in radios))
        self.assertEqual({box["id"] for box in inputs}, set(labels))
        regions = [attrs for _, attrs in parsed.elements if attrs.get("class") == "diagram-stage"]
        self.assertEqual(len(regions), 3)
        self.assertTrue(all(region.get("tabindex") == "0" and region.get("aria-label") for region in regions))
        ids = {attrs.get("id") for _, attrs in parsed.elements}
        self.assertTrue(all(region.get("aria-describedby") in ids for region in regions))
        html = self.render(self.model())
        self.assertIn(".native-size:checked~.diagram-stage img{max-width:none;", html)
        self.assertIn("#view-business:checked~.views .view-business", html)
        self.assertIn("#view-engineering:checked~.views .view-architecture", html)
        self.assertIn("no JavaScript", html)

    def test_source_downloads_are_local_optional_and_keep_exactly_three_figures(self):
        metadata = {
            "drawio": {"path": "Design_Procurement_Test.drawio"},
            "architectureMermaid": {"path": "SA_Procurement_Test.mmd"},
            "sequenceMermaid": {"path": "SD_Procurement_Test.mmd"},
        }
        for options in (
            {"sources": True}, {"sources": metadata}, {"sourceReport": {"sources": metadata}},
            {"sources": {"validation": "passed", "sources": metadata}},
        ):
            with self.subTest(options=options):
                html = self.render(self.model(), options)
                parsed = PreviewParser(html)
                self.assertEqual(parsed.resources(), {
                    "Design_Procurement_Test.drawio",
                    *(f"{kind}_Procurement_Test.{extension}" for kind in ("BA", "SA", "SD")
                      for extension in ("svg", "png", "mmd")),
                })
                self.assertEqual(sum(tag == "figure" for tag, _ in parsed.elements), 3)
                self.assertEqual(sum(tag == "img" for tag, _ in parsed.elements), 3)
                downloads = [attrs for tag, attrs in parsed.elements if tag == "a" and attrs.get("href", "").endswith((".mmd", ".drawio"))]
                self.assertTrue(all("download" in attrs for attrs in downloads))
        self.assertFalse(any(path.endswith(".mmd") for path in PreviewParser(self.render(
            self.model(), {"sources": {"drawio": metadata["drawio"]}}
        )).resources()))

    def test_source_metadata_never_supplies_unsafe_external_or_traversal_paths(self):
        model = self.model()
        model["sourceReport"] = {"sources": {
            "drawio": {"path": "../../outside.drawio"},
            "architectureMermaid": {"path": "https://example.invalid/external.mmd"},
            "sequenceMermaid": {"path": 'x" onclick="bad'},
        }}
        html = self.render(model)
        parsed = PreviewParser(html)
        self.assertTrue(all("/" not in resource and "\\" not in resource for resource in parsed.resources()))
        self.assertNotIn("example.invalid", html)
        self.assertFalse(any(key.startswith("on") for _, attrs in parsed.elements for key in attrs))

    def test_decoded_png_dimensions_are_preserved_as_intrinsic_image_attributes(self):
        result = subprocess.run(
            ["node", "-e", "const {PNG}=require('pngjs');const {createPreview}=require('./preview');"
             "function dims(w,h){const image=new PNG({width:w,height:h});image.data.fill(255);"
             "const decoded=PNG.sync.read(PNG.sync.write(image));"
             "return {width:decoded.width,height:decoded.height};}"
             f"process.stdout.write(createPreview({json.dumps(self.model())},"
             "{business:dims(321,99),architecture:dims(123,45),sequence:dims(67,189)}));"],
            cwd=ROOT / "renderer", capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        images = [attrs for tag, attrs in PreviewParser(result.stdout).elements if tag == "img"]
        self.assertEqual([(image.get("width"), image.get("height")) for image in images], [("321", "99"), ("123", "45"), ("67", "189")])
        self.assertTrue(all(image["decoding"] == "sync" and image["loading"] == "eager" for image in images))
        for options in ({}, {"architecture": {"width": -1, "height": 20}},
                        {"architecture": {"width": '1" onload="bad', "height": 20}},
                        {"sequence": {"width": 10.5, "height": 20}}):
            with self.subTest(options=options):
                images = [attrs for tag, attrs in PreviewParser(self.render(self.model(), options)).elements if tag == "img"]
                self.assertTrue(all("width" not in image and "height" not in image for image in images))

    def test_unsafe_scenario_filenames_are_rejected(self):
        result = subprocess.run(
            ["node", "-e", "const {createPreview}=require('./preview');"
             "const invalid=['../escape','bad/name','bad\\\\name','x\\\" onclick=\\\"x'];"
             "console.log(JSON.stringify(invalid.map(scenarioSlug=>{"
             "try {createPreview({scenarioSlug});return false;} catch(error) {"
             "return error.message==='Invalid preview scenario slug';}})));"],
            cwd=ROOT / "renderer", capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(json.loads(result.stdout)))


if __name__ == "__main__":
    unittest.main()
