from __future__ import annotations

import copy
import base64
import json
import shutil
import subprocess
import sys
import time
import unittest
import uuid
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "layout_engine.py"
VALIDATOR = ROOT / "scripts" / "Test-Diagrams.ps1"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def attrs(kind: str, x: float, y: float, width: float, height: float, **extra: str) -> dict:
    return {
        "data-kind": kind,
        "data-x": str(x), "data-y": str(y),
        "data-width": str(width), "data-height": str(height),
        **{key.replace("_", "-"): value for key, value in extra.items()},
    }


def text(parent: ET.Element, owner: str, value: str, x: int, y: int,
         width: int = 70, size: int = 14, role: str = "body") -> ET.Element:
    group = ET.SubElement(parent, "g", attrs(
        "text-box", x, y, width, 14, data_owner=owner, data_role=role,
    ))
    child = ET.SubElement(group, "text", {
        "x": str(x), "y": str(y + 13), "font-size": str(size), "font-family": "Inter",
    })
    child.text = value
    return group


def svg() -> ET.Element:
    root = ET.Element("svg", {"xmlns": "http://www.w3.org/2000/svg", "viewBox": "0 0 900 650"})
    defs = ET.SubElement(root, "defs")
    marker = ET.SubElement(defs, "marker", {
        "id": "arrow", "markerWidth": "10", "markerHeight": "10",
        "viewBox": "0 0 10 10", "refX": "10", "refY": "5", "orient": "auto",
    })
    ET.SubElement(marker, "path", {"d": "M 0 0 L 10 5 L 0 10 Z", "fill": "#123456"})
    legend = ET.SubElement(root, "g", {"data-kind": "legend"})
    text(legend, "legend", "Legend", 60, 600)
    text(root, "title", "Diagram title", 60, 40, 200, 24, "title")
    text(root, "summary", "Description", 60, 75, 170)
    return root


def route(parent: ET.Element, kind: str, points: list[tuple[int, int]],
          identity: str = "edge", source: str = "a", target: str = "b") -> ET.Element:
    group = ET.SubElement(parent, "g", {
        "data-kind": kind, "data-id": identity, "data-from": source, "data-to": target,
        "data-route": ";".join(f"{x},{y}" for x, y in points), "data-implementation-mode": "real",
    })
    ET.SubElement(group, "path", {
        "d": "M " + " L ".join(f"{x} {y}" for x, y in points),
        "stroke": "#123456", "stroke-width": "2", "fill": "none", "marker-end": "url(#arrow)",
    })
    return group


def diagrams() -> tuple[ET.Element, ET.Element]:
    architecture = svg()
    for identity, x, layer, kind in (("a", 100, "users", "actor"), ("b", 500, "channels", "channel")):
        container = ET.SubElement(architecture, "g", attrs(
            "container", x - 40, 120, 240, 230, data_id=layer, data_header_height="60",
        ))
        ET.SubElement(container, "rect", {"x": str(x - 40), "y": "120", "width": "240", "height": "230"})
        node = ET.SubElement(container, "g", attrs(
            "node", x, 200, 120, 100, data_component_id=identity, data_parent=layer,
            data_component_kind=kind, data_implementation_status="existing", data_members_count="0",
        ))
        text(node, identity, f"Product {identity}", x + 10, 210, role="product-title")
    route(architecture, "connector", [(220, 250), (500, 250)])
    label = ET.SubElement(architecture, "g", attrs(
        "connector-label", 320, 220, 90, 22, data_id="label-edge", data_owner="edge",
    ))
    text(label, "label-edge", "Request", 330, 224, 70, 11)
    sequence = svg()
    for identity, x in (("a", 100), ("b", 500)):
        card = ET.SubElement(sequence, "g", attrs(
            "lifeline", x, 120, 120, 80, data_component_id=identity,
        ))
        text(card, identity, f"Product {identity}", x + 10, 140, role="participant-title")
        ET.SubElement(card, "line", {
            "data-kind": "lifeline-line", "x1": str(x + 60), "x2": str(x + 60), "y1": "200", "y2": "560",
        })
    message = route(sequence, "message", [(160, 300), (560, 300)], "message-1")
    label = ET.SubElement(message, "g", attrs(
        "message-label", 310, 266, 100, 20, data_id="message-label-1", data_owner="message-1",
    ))
    text(label, "message-label-1", "1. Request", 320, 269, 80)
    return architecture, sequence


def find(root: ET.Element, kind: str) -> ET.Element:
    return next(element for element in root.iter() if element.get("data-kind") == kind)


def crosses(points: list[dict], box: dict, padding: float = 0) -> bool:
    left, top = box["x"] - padding, box["y"] - padding
    right, bottom = left + box["width"] + padding * 2, top + box["height"] + padding * 2
    for a, b in zip(points, points[1:]):
        if a["x"] == b["x"]:
            if left <= a["x"] <= right and max(a["y"], b["y"]) >= top and min(a["y"], b["y"]) <= bottom:
                return True
        elif top <= a["y"] <= bottom and max(a["x"], b["x"]) >= left and min(a["x"], b["x"]) <= right:
            return True
    return False


class LocalWorkspace(unittest.TestCase):
    def setUp(self) -> None:
        # Keep every intermediate under the project, never the OS temporary directory.
        self.work = ROOT / "tests" / f".geometry-{uuid.uuid4().hex}"
        self.work.mkdir()
        self.addCleanup(self.cleanup_workspace)

    def cleanup_workspace(self) -> None:
        for attempt in range(6):
            try:
                shutil.rmtree(self.work)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.1 * (attempt + 1))


class RoutingGeometryTests(LocalWorkspace):
    def model(self) -> dict:
        return {
            "canvasWidth": 1000, "canvasHeight": 700,
            "nodes": [
                {"id": "a", "x": 100, "y": 200, "width": 120, "height": 100},
                {"id": "b", "x": 700, "y": 200, "width": 120, "height": 100},
            ],
            "edges": [{"id": "edge", "sourceId": "a", "targetId": "b", "label": "Request",
                       "labelWidth": 100, "labelHeight": 24}],
        }

    def run_layout(self, model: dict, success: bool = True) -> dict:
        source, output = self.work / "input.json", self.work / "output.json"
        source.write_text(json.dumps(model), encoding="utf-8")
        output.unlink(missing_ok=True)
        process = subprocess.run([sys.executable, str(HELPER), str(source), str(output)], capture_output=True, text=True, timeout=120)
        self.assertTrue(output.is_file(), process.stderr or process.stdout)
        result = json.loads(output.read_text(encoding="utf-8"))
        if success:
            self.assertEqual(0, process.returncode, f"{result}\n{process.stderr}")
            self.assertFalse(result["issues"])
        else:
            self.assertNotEqual(0, process.returncode, result)
            self.assertTrue(result["issues"])
        return result

    def assert_geometry(self, model: dict, result: dict) -> None:
        nodes = {node["id"]: node for node in model["nodes"]}
        for item in result["routes"]:
            for a, b in zip(item["points"], item["points"][1:]):
                self.assertTrue(a["x"] == b["x"] or a["y"] == b["y"], item)
                self.assertNotEqual(a, b)
            for key, point in (("sourceId", item["points"][0]), ("targetId", item["points"][-1])):
                box = nodes[item[key]]
                self.assertTrue(
                    box["x"] - 1 <= point["x"] <= box["x"] + box["width"] + 1 and
                    box["y"] - 1 <= point["y"] <= box["y"] + box["height"] + 1
                )
                self.assertLessEqual(min(abs(point["x"] - box["x"]), abs(point["x"] - box["x"] - box["width"]),
                                         abs(point["y"] - box["y"]), abs(point["y"] - box["y"] - box["height"])), 1)
            for box in model["nodes"]:
                own = box["id"] in (item["sourceId"], item["targetId"])
                self.assertFalse(crosses(item["points"], box, -0.1 if own else 1), (item, box))
            label = {
                "x": item["labelX"] - item["labelWidth"] / 2, "y": item["labelY"] - item["labelHeight"] / 2,
                "width": item["labelWidth"], "height": item["labelHeight"],
            }
            for other in result["routes"]:
                self.assertFalse(crosses(other["points"], label, 4), (item, other))

    def test_default_route_is_boundary_anchored_and_label_clears_own_arrow(self) -> None:
        model = self.model()
        result = self.run_layout(model)
        self.assert_geometry(model, result)
        self.assertEqual([{"x": 220, "y": 250}, {"x": 700, "y": 250}], result["routes"][0]["points"])

    def test_opposite_direction_edges_get_distinct_lanes(self) -> None:
        model = self.model()
        model["edges"].append({"id": "return", "sourceId": "b", "targetId": "a",
                               "labelWidth": 100, "labelHeight": 24})
        result = self.run_layout(model)
        self.assert_geometry(model, result)
        self.assertLessEqual(result["metrics"]["oppositeLaneLength"], 24)
        self.assertLessEqual(result["rerouteAttempts"], 60)
        model["edges"].reverse()
        model["nodes"].reverse()
        self.assertEqual(result, self.run_layout(model))

    def test_global_cost_avoids_a_transverse_route_crossing(self) -> None:
        model = self.model()
        model["nodes"].extend([
            {"id": "c", "x": 400, "y": 60, "width": 120, "height": 100},
            {"id": "d", "x": 400, "y": 500, "width": 120, "height": 100},
        ])
        model["edges"].append({"id": "vertical", "sourceId": "c", "targetId": "d",
                               "labelWidth": 90, "labelHeight": 24})
        result = self.run_layout(model)
        self.assert_geometry(model, result)
        self.assertEqual(result["metrics"]["crossings"], 0)
        self.assertEqual(result["metrics"]["oppositeLaneLength"], 0)

    def test_port_hints_are_honored_and_order_independent(self) -> None:
        for source, target in (("right", "left"), ("top", "bottom"), ("south", "north"), ("west", "east")):
            with self.subTest(source=source, target=target):
                model = self.model()
                model["edges"][0].update(sourcePort=source, targetPort=target)
                result = self.run_layout(model)
                self.assert_geometry(model, result)
                first, last = result["routes"][0]["points"][0], result["routes"][0]["points"][-1]
                expected = {
                    "right": (220, 250), "top": (160, 200), "south": (160, 300), "west": (100, 250),
                    "left": (700, 250), "bottom": (760, 300), "north": (760, 200), "east": (820, 250),
                }
                self.assertEqual(expected[source], (first["x"], first["y"]))
                self.assertEqual(expected[target], (last["x"], last["y"]))
                model["nodes"].reverse()
                self.assertEqual(result, self.run_layout(model))

    def test_routes_and_all_labels_clear_obstacles_and_foreign_segments(self) -> None:
        model = self.model()
        model["nodes"].extend([
            {"id": "obstacle", "x": 430, "y": 160, "width": 140, "height": 190},
            {"id": "c", "x": 100, "y": 460, "width": 120, "height": 100},
            {"id": "d", "x": 700, "y": 460, "width": 120, "height": 100},
        ])
        model["edges"].append({"id": "other", "sourceId": "c", "targetId": "b", "label": "Other",
                               "labelWidth": 150, "labelHeight": 40})
        result = self.run_layout(model)
        self.assert_geometry(model, result)

    def test_side_offsets_distribute_common_source_and_target_fanout(self) -> None:
        model = self.model()
        model["nodes"][0]["height"] = model["nodes"][1]["height"] = 280
        model["edges"] = [
            {"id": f"edge-{i}", "sourceId": "a", "targetId": "b", "label": f"Request {i}",
             "labelWidth": 100, "labelHeight": 24,
             "sourceSide": "right", "targetSide": "left", "sourceOffset": offset, "targetOffset": offset}
            for i, offset in enumerate((0.25, 0.5, 0.75))
        ]
        result = self.run_layout(model)
        self.assert_geometry(model, result)
        for item, offset in zip(result["routes"], (0.25, 0.5, 0.75)):
            expected_y = 200 + 280 * offset
            self.assertEqual({"x": 220, "y": expected_y}, item["points"][0])
            self.assertEqual({"x": 700, "y": expected_y}, item["points"][-1])
            self.assertEqual(2, len(item["points"]))
        model["edges"].reverse()
        self.assertEqual(result, self.run_layout(model))

    def test_top_and_bottom_offsets_run_left_to_right(self) -> None:
        model = self.model()
        model["edges"][0].update(sourceSide="top", targetSide="bottom", sourceOffset=0.25, targetOffset=0.75)
        result = self.run_layout(model)
        self.assert_geometry(model, result)
        self.assertEqual({"x": 130, "y": 200}, result["routes"][0]["points"][0])
        self.assertEqual({"x": 790, "y": 300}, result["routes"][0]["points"][-1])

    def test_invalid_offsets_are_not_silently_ignored(self) -> None:
        for side, offset in (("east", -0.1), ("east", 1.1), ("auto", 0.25), (None, 0.25)):
            with self.subTest(side=side, offset=offset):
                model = self.model()
                model["edges"][0].update(sourceSide=side, sourceOffset=offset)
                self.run_layout(model, success=False)

    def test_renderer_routing_exclusion_is_an_obstacle(self) -> None:
        model = self.model()
        model["routingExclusions"] = [{"x": 400, "y": 180, "width": 130, "height": 150}]
        result = self.run_layout(model)
        self.assert_geometry(model, result)
        self.assertFalse(crosses(result["routes"][0]["points"], model["routingExclusions"][0]))

    def test_label_finds_narrow_free_interval_along_vertical_route(self) -> None:
        model = self.model()
        model["nodes"] = [
            {"id": "a", "x": 84, "y": 260, "width": 272, "height": 225},
            {"id": "b", "x": 84, "y": 617, "width": 272, "height": 225},
        ]
        model["canvasHeight"] = 1000
        model["edges"][0].update(sourcePort="east", targetPort="east", labelWidth=100, labelHeight=31)
        model["labelExclusions"] = [{"x": 60, "y": 555, "width": 320, "height": 54}]
        result = self.run_layout(model)
        self.assert_geometry(model, result)

    def test_failed_label_is_explicit_and_has_no_fabricated_position(self) -> None:
        model = self.model()
        model["labelExclusions"] = [{"x": 0, "y": 0, "width": 1000, "height": 700}]
        result = self.run_layout(model, success=False)
        self.assertNotIn("labelX", result["routes"][0])
        self.assertNotIn("labelY", result["routes"][0])

    def test_labels_do_not_float_to_distant_free_space(self) -> None:
        model = self.model()
        model["edges"][0].update(sourceSide="right", targetSide="left")
        model["labelExclusions"] = [{"x": 0, "y": 190, "width": 1000, "height": 120}]
        self.run_layout(model, success=False)

    def test_short_auto_route_moves_to_clear_lane_instead_of_floating_label(self) -> None:
        model = self.model()
        model["nodes"][1]["x"] = 364
        model["edges"][0].update(labelWidth=142, labelHeight=31)
        result = self.run_layout(model)
        self.assert_geometry(model, result)
        self.assertGreaterEqual(len(result["routes"][0]["points"]), 4)
        self.assertEqual(result, self.run_layout(model))

    def test_label_reroute_never_discards_explicit_port_hints(self) -> None:
        model = self.model()
        model["nodes"][1]["x"] = 364
        model["edges"][0].update(labelWidth=142, labelHeight=31, sourceSide="right", targetSide="left")
        result = self.run_layout(model, success=False)
        self.assertEqual([{"x": 220, "y": 250}, {"x": 364, "y": 250}], result["routes"][0]["points"])

    def test_invalid_port_and_duplicate_edge_fail(self) -> None:
        model = self.model()
        model["edges"][0]["sourcePort"] = "diagonal"
        self.run_layout(model, success=False)
        model = self.model()
        model["edges"].append(copy.deepcopy(model["edges"][0]))
        self.run_layout(model, success=False)

    def test_self_route_remains_orthogonal_and_outside_card(self) -> None:
        model = self.model()
        model["edges"][0]["targetId"] = "a"
        self.assert_geometry(model, self.run_layout(model))

    def test_invalid_canvas_nodes_and_labels_fail_closed(self) -> None:
        for change in ("canvas", "duplicate", "outside", "label", "nonfinite"):
            with self.subTest(change=change):
                model = self.model()
                if change == "canvas":
                    model["canvasWidth"] = 0
                elif change == "duplicate":
                    model["nodes"].append(copy.deepcopy(model["nodes"][0]))
                elif change == "outside":
                    model["nodes"][0]["x"] = -10
                elif change == "nonfinite":
                    model["nodes"][0]["width"] = float("inf")
                else:
                    model["edges"][0]["labelWidth"] = -1
                self.run_layout(model, success=False)

    def test_impossible_barrier_is_not_crossed(self) -> None:
        model = self.model()
        model["routingExclusions"] = [{"x": 400, "y": 0, "width": 150, "height": 700}]
        self.run_layout(model, success=False)

    def test_thirty_node_chain_is_deterministic_and_has_valid_geometry(self) -> None:
        model = self.model()
        model["canvasWidth"] = 10000
        model["nodes"] = [
            {"id": f"node-{index:02}", "x": 100 + index * 300, "y": 200, "width": 120, "height": 100}
            for index in range(30)
        ]
        model["edges"] = [
            {"id": f"edge-{index:02}", "sourceId": f"node-{index:02}", "targetId": f"node-{index+1:02}",
             "sourceSide": "right", "targetSide": "left", "labelWidth": 80, "labelHeight": 24}
            for index in range(29)
        ]
        result = self.run_layout(model)
        self.assert_geometry(model, result)
        model["edges"].reverse()
        model["nodes"].reverse()
        self.assertEqual(result, self.run_layout(model))


@unittest.skipUnless(POWERSHELL, "PowerShell is unavailable")
class SvgGeometryValidationTests(LocalWorkspace):
    def validate(self, architecture: ET.Element, sequence: ET.Element, expected: str | None = None,
                 shell: str | None = None) -> dict:
        design = self.work / "design"
        design.mkdir(exist_ok=True)
        sa, sd, report = design / "SA_Test.svg", design / "SD_Test.svg", design / "diagram-validation.json"
        ET.ElementTree(architecture).write(sa, encoding="utf-8", xml_declaration=True)
        ET.ElementTree(sequence).write(sd, encoding="utf-8", xml_declaration=True)
        process = subprocess.run([
            shell or POWERSHELL, "-NoProfile", "-File", str(VALIDATOR),
            "-SolutionArchitecture", str(sa), "-SequenceDiagram", str(sd), "-OutputPath", str(report),
        ], capture_output=True, text=True, timeout=60)
        self.assertTrue(report.exists(), f"{process.stdout}\n{process.stderr}")
        result = json.loads(report.read_text(encoding="utf-8-sig"))
        if expected is None:
            self.assertEqual(0, process.returncode, f"{result}\n{process.stderr}")
            self.assertEqual("passed", result["validation"])
        else:
            self.assertNotEqual(0, process.returncode)
            self.assertEqual("failed", result["validation"])
            self.assertIn(expected, "\n".join(result["issues"]))
        return result

    def test_valid_pair_allows_card_text_and_decorative_container_backgrounds(self) -> None:
        self.validate(*diagrams())

    def test_open_canvas_semantic_layers_preserve_parent_and_bounds_checks(self) -> None:
        sa, sd = diagrams()
        layers = [e for e in sa.iter() if e.get("data-kind") == "container"]
        for layer in layers:
            layer.set("data-kind", "semantic-layer")
            layer.attrib.pop("data-header-height")
            for child in list(layer):
                if child.tag == "rect":
                    layer.remove(child)
        self.validate(sa, sd)
        node = next(e for e in sa.iter() if e.get("data-kind") == "node")
        node.set("data-x", "30")
        self.validate(sa, sd, "outside parent bounds")

    def test_embedded_png_product_asset_is_allowed_but_remote_images_are_not(self) -> None:
        sa, sd = diagrams()
        image = ET.SubElement(sa, "image", {
            "href": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX7sAAAAASUVORK5CYII=",
            "x": "75", "y": "140", "width": "24", "height": "24",
        })
        self.validate(sa, sd)
        image.set("href", "https://example.invalid/icon.png")
        self.validate(sa, sd, "embedded SVG or PNG")

    def test_utf8_without_bom_survives_windows_powershell_51(self) -> None:
        shell = shutil.which("powershell.exe")
        if not shell:
            self.skipTest("Windows PowerShell 5.1 is unavailable")
        sa, sd = diagrams()
        summary = next(e for e in sd.iter() if e.get("data-owner") == "summary")
        summary[0].text = "購買部門の承認"
        self.validate(sa, sd, shell=shell)
        summary[0].text += "\u2026"
        report = self.validate(sa, sd, "truncated with an ellipsis", shell=shell)
        self.assertIn("購買部門の承認\u2026", "\n".join(report["issues"]))

    def test_embedded_image_intrinsic_dimensions_and_safe_xml_parsing(self) -> None:
        sa, sd = diagrams()
        image = ET.SubElement(sa, "image", {"x": "75", "y": "140", "width": "24", "height": "24"})
        for svg_source, valid in (
            ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"/>', True),
            ('<svg xmlns="http://www.w3.org/2000/svg" width="24px" height="16px"/>', True),
            ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 0 24"/>', False),
            ('<!DOCTYPE svg [<!ENTITY x "24">]><svg width="&x;" height="24"/>', False),
        ):
            with self.subTest(svg=svg_source):
                image.set("href", "data:image/svg+xml;base64," + base64.b64encode(svg_source.encode()).decode())
                self.validate(sa, sd, None if valid else "Invalid embedded image")
        png = bytearray(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX7sAAAAASUVORK5CYII="
        ))
        png[16:20] = b"\0\0\0\0"
        png[29:33] = zlib.crc32(png[12:29]).to_bytes(4, "big")
        image.set("href", "data:image/png;base64," + base64.b64encode(png).decode())
        self.validate(sa, sd, "intrinsic dimensions")
        png[29] ^= 1
        image.set("href", "data:image/png;base64," + base64.b64encode(png).decode())
        self.validate(sa, sd, "checksum failed")
        image.set("href", "data:image/png;base64," + base64.b64encode(b"not a PNG").decode())
        self.validate(sa, sd, "Truncated PNG")

    def test_packaged_official_icon_dimensions_are_accepted(self) -> None:
        sa, sd = diagrams()
        manifest = json.loads((ROOT / "resources" / "icon-manifest.json").read_text(encoding="utf-8-sig"))
        for icon in manifest["icons"]:
            path = ROOT / "resources" / icon["file"]
            mime = "image/png" if path.suffix.lower() == ".png" else "image/svg+xml"
            ET.SubElement(sa, "image", {
                "href": f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode(),
                "x": "75", "y": "140", "width": "24", "height": "24",
            })
        self.validate(sa, sd)
        windows_powershell = shutil.which("powershell.exe")
        if windows_powershell and windows_powershell != POWERSHELL:
            self.validate(sa, sd, shell=windows_powershell)

    def test_endpoint_gap_is_rejected(self) -> None:
        sa, sd = diagrams()
        connector = find(sa, "connector")
        connector.set("data-route", "225,250;495,250")
        connector[0].set("d", "M 225 250 L 495 250")
        self.validate(sa, sd, "not anchored")

    def test_rendered_path_cannot_disagree_with_metadata(self) -> None:
        sa, sd = diagrams()
        find(sa, "connector")[0].set("d", "M 230 250 L 490 250")
        self.validate(sa, sd, "rendered path differs")

    def test_label_own_arrow_and_padding_collision_are_rejected(self) -> None:
        for y in (245, 225):
            with self.subTest(y=y):
                sa, sd = diagrams()
                find(sa, "connector-label").set("data-y", str(y))
                self.validate(sa, sd, "4px clearance")

    def test_label_background_cannot_cover_title_or_foreign_text(self) -> None:
        sa, sd = diagrams()
        text(sa, "note", "Unrelated note", 325, 220, 80)
        self.validate(sa, sd, "overlaps unrelated text")

    def test_route_cannot_cross_text_even_without_label_background(self) -> None:
        sa, sd = diagrams()
        text(sa, "note", "Crossing note", 440, 246, 50)
        self.validate(sa, sd, "crosses text")

    def test_sequence_only_typography_is_always_checked(self) -> None:
        sa, sd = diagrams()
        find(sd, "message-label")[0][0].set("font-size", "10")
        self.validate(sa, sd, "sub-11px")

    def test_product_titles_have_stronger_minimum(self) -> None:
        sa, sd = diagrams()
        product = next(e for e in sa.iter() if e.get("data-role") == "product-title")
        product[0].set("font-size", "13")
        self.validate(sa, sd, "sub-14px")
        product.attrib.pop("data-role")
        self.validate(sa, sd, "sub-14px")

    def test_diagonal_segment_is_rejected_even_with_only_endpoint_nodes(self) -> None:
        sa, sd = diagrams()
        connector = find(sa, "connector")
        connector.set("data-route", "220,250;500,270")
        connector[0].set("d", "M 220 250 L 500 270")
        self.validate(sa, sd, "non-orthogonal")

    def test_endpoint_route_cannot_reenter_its_source_card(self) -> None:
        sa, sd = diagrams()
        connector = find(sa, "connector")
        connector.set("data-route", "220,250;180,250;180,310;500,310;500,250")
        connector[0].set("d", "M 220 250 L 180 250 L 180 310 L 500 310 L 500 250")
        self.validate(sa, sd, "crosses card 'a'")

    def test_far_label_and_actual_lifeline_geometry_fail(self) -> None:
        sa, sd = diagrams()
        label = find(sa, "connector-label")
        label.set("data-y", "370")
        label[0].set("data-y", "374")
        self.validate(sa, sd, "floats more than")
        sa, sd = diagrams()
        find(sd, "lifeline-line").set("x1", "170")
        self.validate(sa, sd, "Invalid lifeline")

    def test_inline_font_style_and_tspan_cannot_bypass_minimum(self) -> None:
        sa, sd = diagrams()
        label_text = find(sd, "message-label")[0][0]
        label_text.set("style", "font-size:9px")
        self.validate(sa, sd, "sub-11px")
        label_text.attrib.pop("style")
        ET.SubElement(label_text, "tspan", {"font-size": "8"}).text = "tiny"
        self.validate(sa, sd, "sub-11px")

    def test_title_description_overlap_is_rejected(self) -> None:
        sa, sd = diagrams()
        summary = next(e for e in sd.iter() if e.get("data-owner") == "summary")
        summary.set("data-y", "40")
        self.validate(sa, sd, "Visible text overlaps")

    def test_exact_glyph_bounds_need_no_extra_inset_inside_own_card(self) -> None:
        sa, sd = diagrams()
        card = find(sd, "lifeline")
        caption = text(card, "a", "Existing", 110, 185, width=70, size=11)
        caption.set("data-height", "14.5")
        self.validate(sa, sd)
        caption.set("data-height", "15.5")
        self.validate(sa, sd, "exceeds its own card")

    def test_missing_measurement_and_nonfinite_geometry_fail_with_report(self) -> None:
        sa, sd = diagrams()
        ET.SubElement(sd, "text", {"font-size": "14"}).text = "Unmeasured"
        self.validate(sa, sd, "lacks measured")
        sa, sd = diagrams()
        find(sd, "text-box").set("data-width", "NaN")
        self.validate(sa, sd, "Non-finite")

    def test_zero_width_whitespace_is_harmless_but_visible_glyph_is_invalid(self) -> None:
        sa, sd = diagrams()
        spacer = text(sd, "spacer", " ", 320, 300, width=0)
        spacer.set("data-height", "0")
        self.validate(sa, sd)
        spacer[0].text = "Visible"
        self.validate(sa, sd, "Box dimensions must be positive")

    def test_self_message_and_arrowhead_visibility(self) -> None:
        sa, sd = diagrams()
        message = find(sd, "message")
        message.set("data-to", "a")
        message.set("data-route", "160,300;930,300;930,330;160,330")
        message[0].set("d", "M 160 300 L 930 300 L 930 330 L 160 330")
        self.validate(sa, sd, "outside canvas")
        sa, sd = diagrams()
        marker = next(e for e in sd.iter() if e.tag == "marker")
        marker[0].set("fill", "none")
        self.validate(sa, sd, "invisible arrowhead")

    def test_phase_and_fragment_headings_reserve_separate_rows(self) -> None:
        sa, sd = diagrams()
        phase = ET.SubElement(sd, "g", attrs("phase", 60, 240, 700, 180, data_id="phase"))
        text(phase, "phase", "Phase one", 80, 245, 100, 14, "phase-title")
        fragment = ET.SubElement(sd, "g", attrs("fragment", 74, 265, 650, 120, data_id="fragment"))
        text(fragment, "fragment", "alt [condition]", 80, 270, 100, 12, "fragment-title")
        self.validate(sa, sd, "reserved fragment heading row")

    def test_sequence_route_may_cross_intermediate_lifeline(self) -> None:
        sa, sd = diagrams()
        container = ET.SubElement(sa, "g", attrs(
            "container", 60, 380, 300, 190, data_id="extra", data_header_height="30",
        ))
        node = ET.SubElement(container, "g", attrs(
            "node", 100, 420, 120, 100, data_component_id="c", data_parent="extra",
            data_component_kind="service", data_implementation_status="build", data_members_count="0",
        ))
        text(node, "c", "Product c", 110, 430, role="product-title")
        card = ET.SubElement(sd, "g", attrs("lifeline", 300, 120, 120, 80, data_component_id="c"))
        text(card, "c", "Product c", 310, 140, role="participant-title")
        ET.SubElement(card, "line", {
            "data-kind": "lifeline-line", "x1": "360", "x2": "360", "y1": "200", "y2": "560",
        })
        self.validate(sa, sd)

    def test_nonshared_crossing_requires_bridge_at_exact_intersection(self) -> None:
        sa, sd = diagrams()
        label = find(sa, "connector-label")
        label.set("data-x", "225")
        label[0].set("data-x", "235")
        label[0][0].set("x", "235")
        container = ET.SubElement(sa, "g", attrs(
            "container", 296, 85, 128, 510, data_id="crossing-layer", data_header_height="30",
        ))
        for identity, y in (("c", 120), ("d", 450)):
            card = ET.SubElement(container, "g", attrs(
                "node", 320, y, 80, 70, data_component_id=identity, data_parent="crossing-layer",
                data_component_kind="service", data_implementation_status="build", data_members_count="0",
            ))
            text(card, identity, identity, 325, y + 10, width=60, role="product-title")
        crossing = route(sa, "connector", [(360, 190), (360, 450)], "vertical-edge", "c", "d")
        self.validate(sa, sd, "cross without a bridge")
        bridge = ET.SubElement(crossing, "g", {
            "data-kind": "connector-bridge", "data-x": "361", "data-y": "250",
        })
        ET.SubElement(bridge, "circle", {"cx": "360", "cy": "250", "r": "6", "fill": "white"})
        ET.SubElement(bridge, "path", {
            "d": "M 360 243 Q 370 250 360 257", "fill": "none", "stroke": "#123456", "stroke-width": "2",
        })
        self.validate(sa, sd, "cross without a bridge")
        bridge.set("data-x", "360")
        self.validate(sa, sd)

    def test_semantic_checks_and_legend_are_preserved(self) -> None:
        sa, sd = diagrams()
        find(sa, "node").set("data-implementation-status", "unknown")
        find(sd, "message").set("data-implementation-mode", "simulated")
        sd.remove(find(sd, "legend"))
        result = self.validate(sa, sd, "implementation status")
        self.assertIn("not visibly disclosed", "\n".join(result["issues"]))
        self.assertIn("exactly one visible legend", "\n".join(result["issues"]))


if __name__ == "__main__":
    unittest.main()
