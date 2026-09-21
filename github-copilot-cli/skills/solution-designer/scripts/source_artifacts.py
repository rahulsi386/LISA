"""Offline editable sources: canonical model -> validated Draw.io -> validated Mermaid.

Only a small, deliberately escaped Mermaid grammar is emitted and accepted. Source
validation reads visible labels, directed edges, participant anchors, and ordering;
embedded metadata and the report's previous validation result are not trusted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PAGES = ("Solution Architecture", "Sequence Diagram")
MODES = {
    "real": "#2563eb", "simulated": "#0891b2", "manual": "#b45309",
    "deferred": "#64748b", "blocked": "#dc2626",
}
PLAIN = "html=0;whiteSpace=wrap;fontFamily=Arial;fontSize=14;"
NODE_STYLE = PLAIN + "rounded=1;fillColor=#ffffff;strokeColor=#94a3b8;align=left;spacing=12;"
TEXT_STYLE = PLAIN + "text;strokeColor=none;fillColor=none;align=left;verticalAlign=top;"


class SourceValidationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SourceValidationError(message)


def canonical_json(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return text.replace("\u0085", "\\u0085").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def display(value: Any) -> str:
    return value if isinstance(value, str) else canonical_json(value)


def fields_label(record: dict, excluded: set[str]) -> str:
    return "\n".join(f"{key}: {display(value)}" for key, value in record.items() if key not in excluded)


def component_label(record: dict) -> str:
    parts = [record["name"]]
    if record.get("description"):
        parts.append(record["description"])
    parts.append(fields_label(record, {"name", "description"}))
    return "\n".join(part for part in parts if part)


def interaction_label(item: dict) -> str:
    record = item["record"]
    label = record["label"]
    if record["implementationMode"] == "simulated" and not label.startswith("Simulated:"):
        label = "Simulated: " + label
    # Occurrence identity is explicit even for identical legacy multiedges.
    return f"{label}\nSource ID: {item['id']}\nOrder: {item['order']}\n" + fields_label(record, {"label"})


def identified(records: list[dict], prefix: str) -> list[dict]:
    explicit = [record["id"] for record in records if "id" in record]
    require(all(isinstance(value, str) and value for value in explicit), f"Invalid {prefix} ID")
    require(len(set(explicit)) == len(explicit), f"Duplicate canonical {prefix} IDs")
    reserved = set(explicit)
    result = []
    for index, record in enumerate(records, 1):
        identity = record.get("id")
        if identity is None:
            identity = f"{prefix}-{index:04d}"
            while identity in reserved:
                identity += "-legacy"
        reserved.add(identity)
        result.append({"id": identity, "order": index, "record": record})
    return result


@dataclass
class Design:
    model: dict

    def __post_init__(self) -> None:
        require(isinstance(self.model, dict), "Model must be an object")
        require(bool(re.fullmatch(r"[A-Za-z0-9_]+", self.model.get("scenarioSlug", ""))), "Invalid scenario slug")
        for key in ("components", "relationships", "sequence"):
            require(isinstance(self.model.get(key), list), f"Model {key} must be an array")
            require(all(isinstance(item, dict) for item in self.model[key]), f"Invalid {key} record")
        self.components = self.model["components"]
        self.component_ids = [component.get("id") for component in self.components]
        require(bool(self.components), "No architecture components")
        require(all(isinstance(identity, str) and identity for identity in self.component_ids), "Invalid component ID")
        require(len(set(self.component_ids)) == len(self.component_ids), "Duplicate component IDs")
        require(all(isinstance(item.get("name"), str) and item["name"] for item in self.components), "Missing exact component name")
        self.relationships = identified(self.model["relationships"], "relationship")
        self.sequence = identified(self.model["sequence"], "sequence")
        require(bool(self.sequence), "No sequence messages")
        for kind, items, key, allowed in (
            ("relationship", self.relationships, "style", {"call", "response", "optional", "tbd"}),
            ("sequence", self.sequence, "type", {"call", "response", "self", "approval"}),
        ):
            for item in items:
                record = item["record"]
                require(record.get("from") in self.component_ids and record.get("to") in self.component_ids,
                        f"Unknown {kind} endpoint: {item['id']}")
                require(isinstance(record.get("label"), str) and bool(record["label"]), f"Missing {kind} label")
                require(record.get("implementationMode") in MODES, f"Invalid {kind} implementation mode")
                require(record.get(key) in allowed, f"Invalid {kind} {key}")
                if kind == "relationship":
                    require(record.get("direction", "unidirectional") in {"unidirectional", "bidirectional"},
                            f"Invalid relationship direction: {item['id']}")
                if record.get("type") == "self":
                    require(record["from"] == record["to"], f"Self message has different endpoints: {item['id']}")
                for field in ("phase", "fragment"):
                    require(record.get(field) is None or isinstance(record[field], str), f"Invalid {field}")
        used = {item["record"][end] for item in self.sequence for end in ("from", "to")}
        participants = self.model.get("sequenceParticipants")
        if participants is None:
            self.participant_ids = [identity for identity in self.component_ids if identity in used]
        else:
            require(isinstance(participants, list), "sequenceParticipants must be an array")
            self.participant_ids = [
                item.get("componentId", item.get("id")) if isinstance(item, dict) else item
                for item in participants
            ]
            require(all(identity in self.component_ids for identity in self.participant_ids), "Unknown participant")
            require(len(set(self.participant_ids)) == len(self.participant_ids), "Duplicate participants")
            require(used <= set(self.participant_ids), "Message endpoint missing from explicit participants")
        self.context = {key: value for key, value in self.model.items()
                        if key not in {"components", "relationships", "sequence"}}
        # XML 1.0 cannot represent control characters or isolated surrogates.
        text = canonical_json(self.model)
        require(not re.search(r"[\ud800-\udfff\ufffe\uffff]", text), "Model contains invalid XML Unicode")
        self._check_strings(self.model)

    @staticmethod
    def _check_strings(value: Any) -> None:
        if isinstance(value, str):
            require(not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value), "Model contains invalid XML control characters")
        elif isinstance(value, dict):
            for key, child in value.items():
                Design._check_strings(key)
                Design._check_strings(child)
        elif isinstance(value, list):
            for child in value:
                Design._check_strings(child)

    @property
    def participants(self) -> list[dict]:
        by_id = {item["id"]: item for item in self.components}
        return [by_id[identity] for identity in self.participant_ids]

    @property
    def filenames(self) -> dict[str, str]:
        slug = self.model["scenarioSlug"]
        return {"drawio": f"Design_{slug}.drawio", "architectureMermaid": f"SA_{slug}.mmd",
                "sequenceMermaid": f"SD_{slug}.mmd"}


def context_label(design: Design) -> str:
    return fields_label(design.context, set())


def text_height(label: str, width: int = 320) -> int:
    return 32 + 18 * sum(max(1, math.ceil(len(line) / max(1, (width - 24) // 8)))
                         for line in label.split("\n"))


def cell(root: ET.Element, identity: str, label: str, role: str, style: str,
         x: float, y: float, width: float, height: float, *, parent: str = "1",
         record: Any = None, **attrs: str) -> ET.Element:
    attributes = {"id": identity, "value": label, "vertex": "1", "parent": parent,
                  "style": style, "lisaRole": role, **attrs}
    if record is not None:
        attributes["lisaRecord"] = canonical_json(record)
    element = ET.SubElement(root, "mxCell", attributes)
    ET.SubElement(element, "mxGeometry", {
        "x": str(x), "y": str(y), "width": str(width), "height": str(height), "as": "geometry",
    })
    return element


def edge_style(record: dict) -> str:
    dashed = record["implementationMode"] != "real" or record.get("style", record.get("type")) in {"response", "optional", "tbd"}
    start_arrow = "startArrow=block;startFill=1;" if record.get("direction") == "bidirectional" else ""
    return (PLAIN + "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;"
            "jettySize=auto;endArrow=block;endFill=1;strokeWidth=2;"
            f"strokeColor={MODES[record['implementationMode']]};dashed={int(dashed)};"
            + start_arrow + "labelBackgroundColor=#ffffff;")


def edge(root: ET.Element, identity: str, item: dict, source: str, target: str,
         role: str, points: list[tuple[float, float]] | None = None) -> None:
    element = ET.SubElement(root, "mxCell", {
        "id": identity, "value": interaction_label(item), "edge": "1", "parent": "1",
        "source": source, "target": target, "style": edge_style(item["record"]),
        "lisaRole": role, "lisaId": item["id"], "lisaOrder": str(item["order"]),
        "lisaRecord": canonical_json(item["record"]),
    })
    geometry = ET.SubElement(element, "mxGeometry", {"relative": "1", "as": "geometry"})
    if points:
        array = ET.SubElement(geometry, "Array", {"as": "points"})
        for x, y in points:
            ET.SubElement(array, "mxPoint", {"x": str(x), "y": str(y)})


def drawio_tree(design: Design, model_hash: str) -> ET.Element:
    document = ET.Element("mxfile", {
        "host": "app.diagrams.net", "type": "device", "compressed": "false",
        "lisaVersion": "1", "lisaModelSha256": model_hash, "lisaContext": canonical_json(design.context),
    })
    context = context_label(design)
    context_height = text_height(context, 1200)
    for page_index, page_name in enumerate(PAGES):
        diagram = ET.SubElement(document, "diagram", {"id": f"lisa-{page_index + 1}", "name": page_name})
        graph = ET.SubElement(diagram, "mxGraphModel", {"grid": "1", "gridSize": "10", "page": "0", "math": "0"})
        root = ET.SubElement(graph, "root")
        ET.SubElement(root, "mxCell", {"id": "0"})
        ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
        cell(root, "context", context, "context", TEXT_STYLE, 40, 20, 1200, context_height)
        if page_index == 0:
            positions = {}
            y = context_height + 80
            for start in range(0, len(design.components), 4):
                row = design.components[start:start + 4]
                row_height = max(text_height(component_label(item)) for item in row)
                for column, record in enumerate(row):
                    x = 40 + column * 440
                    identity = "sa-node-" + record["id"]
                    positions[record["id"]] = (x, y, row_height)
                    cell(root, identity, component_label(record), "component", NODE_STYLE,
                         x, y, 320, row_height, record=record, lisaId=record["id"])
                y += row_height + 180
            for index, item in enumerate(design.relationships, 1):
                record = item["record"]
                x, sy, height = positions[record["from"]]
                tx, ty, _ = positions[record["to"]]
                lane = 40 + index * 18
                points = [(x + 320 + lane, sy + height / 2), (tx + 160, ty - lane)]
                if record["from"] == record["to"]:
                    points = [(x + 320 + lane, sy + 60), (x + 320 + lane, sy + height - 60)]
                edge(root, f"sa-edge-{index:04d}", item, "sa-node-" + record["from"],
                     "sa-node-" + record["to"], "relationship", points)
        else:
            _sequence_cells(root, design, context_height + 80)
    return document


def _sequence_cells(root: ET.Element, design: Design, top: int) -> None:
    header_height = max(text_height(component_label(record), 300) for record in design.participants)
    schedule = []
    bands = []
    y = header_height + 60
    previous_phase = previous_fragment = None
    width = max(300, len(design.participants) * 400 - 100)
    for index, item in enumerate(design.sequence, 1):
        record = item["record"]
        for field, previous in (("phase", previous_phase), ("fragment", previous_fragment)):
            value = record.get(field)
            if value and value != previous:
                height = text_height(value, width)
                bands.append((field, index, value, top + y, height))
                y += height + 16
        half_message_height = max(50, math.ceil(text_height(interaction_label(item), max(320, width // 2)) / 2) + 20)
        y += half_message_height
        schedule.append((item, y))
        y += half_message_height + 70
        previous_phase, previous_fragment = record.get("phase"), record.get("fragment")
    for index, record in enumerate(design.participants):
        identity = "sd-participant-" + record["id"]
        cell(root, identity, component_label(record), "participant",
             NODE_STYLE + f"swimlane;startSize={header_height};horizontal=1;swimlaneFillColor=none;",
             40 + index * 400, top, 300, y + 40, record=record, lisaId=record["id"])
        cell(root, "sd-lifeline-" + record["id"], "", "lifeline",
             PLAIN + "shape=line;direction=south;strokeColor=#94a3b8;dashed=1;",
             150, header_height, 1, y - header_height, parent=identity)
    for field, index, value, band_y, height in bands:
        cell(root, f"sd-{field}-{index:04d}", f"{field.title()}: {value}", field,
             TEXT_STYLE, 40, band_y, width, height, record=value, lisaOrder=str(index))
    participant_index = {identity: index for index, identity in enumerate(design.participant_ids)}
    anchor_style = PLAIN + "ellipse;fillColor=none;strokeColor=none;opacity=0;"
    for item, row in schedule:
        record = item["record"]
        identity = f"sd-message-{item['order']:04d}"
        for end in ("from", "to"):
            offset = 24 if end == "to" and record["from"] == record["to"] else 0
            cell(root, identity + "-" + end, "", "anchor", anchor_style, 149, row + offset, 2, 2,
                 parent="sd-participant-" + record[end], lisaParticipant=record[end])
        points = None
        if record["from"] == record["to"]:
            index = participant_index[record["from"]]
            x = 40 + index * 400 + 150
            loop_x = x + (80 if index < len(design.participants) - 1 else -80)
            points = [(loop_x, top + row + 1), (loop_x, top + row + 25)]
        edge(root, identity, item, identity + "-from", identity + "-to", "message", points)


def write_drawio(path: Path, design: Design, model_hash: str) -> None:
    document = drawio_tree(design, model_hash)
    ET.indent(document, space="  ")
    path.write_bytes(ET.tostring(document, encoding="utf-8", xml_declaration=True))


def validate_drawio(path: Path, design: Design, model_hash: str) -> Design:
    raw = path.read_bytes()
    require(b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper(), "Draw.io XML entities are forbidden")
    try:
        actual = ET.fromstring(raw)
    except ET.ParseError as error:
        raise SourceValidationError(f"Invalid Draw.io XML: {error}") from error
    expected = drawio_tree(design, model_hash)
    require(actual.tag == "mxfile" and actual.attrib == expected.attrib, "Draw.io model provenance differs")
    require([page.get("name") for page in actual] == list(PAGES), "Draw.io must have exactly the two canonical pages")
    extracted: dict[str, list] = {"component": [], "relationship": [], "message": []}
    for actual_page, expected_page in zip(actual, expected):
        require(actual_page.tag == "diagram" and actual_page.attrib == expected_page.attrib, "Invalid Draw.io page")
        require(len(actual_page) == 1 and actual_page[0].tag == "mxGraphModel", "Draw.io pages must be editable, uncompressed mxGraphModel")
        graph = actual_page[0]
        require(graph.attrib == expected_page[0].attrib and len(graph) == 1 and graph[0].tag == "root", "Invalid editable graph")
        actual_cells = list(graph[0])
        expected_cells = list(expected_page[0][0])
        require(all(item.tag == "mxCell" for item in actual_cells), "Noneditable Draw.io content")
        require([item.get("id") for item in actual_cells] == [item.get("id") for item in expected_cells],
                "Draw.io component, participant, or multiedge occurrence/order differs")
        actual_by_id = {item.get("id"): item for item in actual_cells}
        message_rows = []
        for item, reference in zip(actual_cells, expected_cells):
            identity = item.get("id")
            require(item.attrib == reference.attrib, f"Draw.io visible label/edge/mode/record differs: {identity}")
            role = item.get("lisaRole")
            if not role:
                require(len(item) == 0, "Unexpected Draw.io root content")
                continue
            require(len(item) == 1 and item[0].tag == "mxGeometry", f"Invalid Draw.io geometry: {identity}")
            geometry = item[0]
            require(geometry.get("as") == "geometry", f"Missing editable geometry: {identity}")
            for part in geometry.iter():
                require(part.tag in {"mxGeometry", "Array", "mxPoint"}, f"Unsupported Draw.io shape: {identity}")
                for key in ("x", "y", "width", "height"):
                    if key in part.attrib:
                        require(math.isfinite(float(part.attrib[key])), f"Invalid geometry number: {identity}")
                require(part.text is None or not part.text.strip(), "Unexpected geometry text")
            if item.get("vertex") == "1":
                require(float(geometry.get("width", "0")) > 0 and float(geometry.get("height", "0")) > 0,
                        f"Invisible Draw.io vertex: {identity}")
            if item.get("edge") == "1":
                require(geometry.get("relative") == "1", f"Unanchored Draw.io edge: {identity}")
                for end in ("source", "target"):
                    require(item.get(end) in actual_by_id, f"Missing edge endpoint: {identity}")
            if role == "message":
                anchor = actual_by_id[item.get("source")]
                target = actual_by_id[item.get("target")]
                for endpoint in (anchor, target):
                    participant = actual_by_id[endpoint.get("parent")]
                    require(endpoint.get("lisaParticipant") == participant.get("lisaId"), "Wrong sequence anchor participant")
                    require(float(endpoint[0].get("x")) + 1 == float(participant[0].get("width")) / 2,
                            "Sequence anchor detached from participant lifeline")
                source_y = float(anchor[0].get("y")) + float(actual_by_id[anchor.get("parent")][0].get("y"))
                target_y = float(target[0].get("y")) + float(actual_by_id[target.get("parent")][0].get("y"))
                expected_offset = 24 if anchor.get("parent") == target.get("parent") else 0
                require(target_y == source_y + expected_offset, "Sequence message anchors have inconsistent time")
                message_rows.append(source_y)
            if role in extracted:
                extracted[role].append(json.loads(item.get("lisaRecord")))
        require(message_rows == sorted(set(message_rows)), "Draw.io sequence time/order differs")
    recovered_model = json.loads(actual.get("lisaContext"))
    recovered_model.update(components=extracted["component"], relationships=extracted["relationship"], sequence=extracted["message"])
    require(recovered_model == design.model, "Draw.io canonical semantic roundtrip differs")
    return Design(recovered_model)


def mermaid_escape(text: str) -> str:
    # Numeric Mermaid entities prevent grammar injection before labels are rendered.
    # Escape '#' too, so literal source entities are not decoded a second time.
    unsafe = set('#"&<>|;[]{}()`\\%')
    result = "".join("<br/>" if character == "\n" else
                     f"#{ord(character)};" if character in unsafe or character in "\r\t\u0085\u2028\u2029" else character
                     for character in text)
    return re.sub(r"\bend\b", lambda match: f"#{ord(match[0][0])};" + match[0][1:], result, flags=re.IGNORECASE)


def mermaid_unescape(text: str) -> str:
    decoded = re.sub(r"#([0-9]+);", lambda match: chr(int(match[1])), text.replace("<br/>", "\n"))
    require(mermaid_escape(decoded) == text, "Unsafe or noncanonical Mermaid label escaping")
    return decoded


def mermaid_header(kind: str, design: Design, model_hash: str, drawio_hash: str) -> list[str]:
    return [kind, f"%% model-sha256: {model_hash}", f"%% drawio-sha256: {drawio_hash}",
            "%% context: " + canonical_json(design.context)]


def architecture_mermaid(design: Design, model_hash: str, drawio_hash: str) -> str:
    lines = mermaid_header("flowchart LR", design, model_hash, drawio_hash)
    aliases = {record["id"]: f"n{index:04d}" for index, record in enumerate(design.components, 1)}
    for record in design.components:
        lines.append(f'    {aliases[record["id"]]}["{mermaid_escape(component_label(record))}"]')
    for item in design.relationships:
        record = item["record"]
        arrow = "<-->" if record.get("direction") == "bidirectional" else "-->"
        lines.append(f'    {aliases[record["from"]]} {arrow}|"{mermaid_escape(interaction_label(item))}"| {aliases[record["to"]]}')
    for index, item in enumerate(design.relationships):
        record = item["record"]
        dashed = record["implementationMode"] != "real" or record["style"] in {"response", "optional", "tbd"}
        style = f"stroke:{MODES[record['implementationMode']]},stroke-width:2px"
        if dashed:
            style += ",stroke-dasharray:5 4"
        lines.append(f"    linkStyle {index} {style}")
    return "\n".join(lines) + "\n"


def fragment_header(fragment: str) -> tuple[str, str]:
    match = re.fullmatch(r"(alt|opt|loop|par|critical|break|else|and|option)\s+(.+)", fragment, re.DOTALL)
    return (match[1], match[2]) if match else ("rect", fragment)


def sequence_mermaid(design: Design, model_hash: str, drawio_hash: str) -> str:
    lines = mermaid_header("sequenceDiagram", design, model_hash, drawio_hash)
    lines.append("    autonumber")
    aliases = {identity: f"p{index:04d}" for index, identity in enumerate(design.participant_ids, 1)}
    for record in design.participants:
        lines.append(f"    participant {aliases[record['id']]} as {mermaid_escape(record['name'])}")
    for record in design.participants:
        lines.append(f"    Note over {aliases[record['id']]}: {mermaid_escape(component_label(record))}")
    span = aliases[design.participant_ids[0]]
    if len(design.participant_ids) > 1:
        span += "," + aliases[design.participant_ids[-1]]
    lines.append(f"    Note over {span}: {mermaid_escape(context_label(design))}")
    previous_phase = previous_fragment = None
    block = None
    for item in design.sequence:
        record = item["record"]
        fragment = record.get("fragment")
        if fragment != previous_fragment:
            kind, condition = fragment_header(fragment) if fragment else (None, "")
            branch = (kind, block) in {("else", "alt"), ("and", "par"), ("option", "critical")}
            if block and not branch:
                lines.append("    end")
                block = None
            if fragment:
                if branch:
                    lines.append(f"    {kind} {mermaid_escape(condition)}")
                elif kind in {"alt", "opt", "loop", "par", "critical", "break"}:
                    lines.append(f"    {kind} {mermaid_escape(condition)}")
                    block = kind
                else:
                    # An untyped fragment is a neutral group, never an invented opt/alt.
                    lines.append("    rect rgb(245, 248, 252)")
                    block = "rect"
                lines.append(f"    Note over {span}: {mermaid_escape('Fragment: ' + fragment)}")
        phase = record.get("phase")
        if phase and phase != previous_phase:
            lines.append(f"    Note over {span}: {mermaid_escape('Phase: ' + phase)}")
        arrow = "-->>" if record["type"] == "response" or record["implementationMode"] != "real" else "->>"
        lines.append(f"    {aliases[record['from']]}{arrow}{aliases[record['to']]}: {mermaid_escape(interaction_label(item))}")
        previous_phase, previous_fragment = phase, fragment
    if block:
        lines.append("    end")
    return "\n".join(lines) + "\n"


def parse_mermaid(source: str, kind: str) -> list[tuple]:
    """Parse the emitted grammar, including real labels/endpoints and block balance."""
    lines = source.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    require(bool(lines) and lines[0] == kind, "Unexpected Mermaid diagram kind")
    events: list[tuple] = [(kind,)]
    declarations = set()
    stack = []
    edges = 0
    for raw in lines[1:]:
        line = raw.lstrip(" ")
        match = re.fullmatch(r"%% (model-sha256|drawio-sha256): ([a-f0-9]{64})", line)
        if match:
            events.append(("hash", match[1], match[2]))
            continue
        if line.startswith("%% context: "):
            events.append(("context", json.loads(line[len("%% context: "):])))
            continue
        if kind == "flowchart LR":
            match = re.fullmatch(r'(n[0-9]{4,})\["(.*)"\]', line)
            if match:
                require(match[1] not in declarations, "Duplicate Mermaid node")
                declarations.add(match[1])
                events.append(("node", match[1], mermaid_unescape(match[2])))
                continue
            match = re.fullmatch(r'(n[0-9]{4,}) (-->|<-->)\|"(.*)"\| (n[0-9]{4,})', line)
            if match:
                require(match[1] in declarations and match[4] in declarations, "Unknown Mermaid edge endpoint")
                events.append(("edge", match[1], match[4], match[2], mermaid_unescape(match[3])))
                edges += 1
                continue
            match = re.fullmatch(r"linkStyle ([0-9]+) stroke:(#[0-9a-f]{6}),stroke-width:2px(,stroke-dasharray:5 4)?", line)
            if match:
                require(int(match[1]) < edges, "Mermaid style has no edge")
                events.append(("style", int(match[1]), match[2], bool(match[3])))
                continue
        else:
            if line == "autonumber":
                events.append(("autonumber",))
                continue
            match = re.fullmatch(r"participant (p[0-9]{4,}) as (.*)", line)
            if match:
                require(match[1] not in declarations, "Duplicate Mermaid participant")
                declarations.add(match[1])
                events.append(("participant", match[1], mermaid_unescape(match[2])))
                continue
            match = re.fullmatch(r"Note over (p[0-9]{4,})(?:,(p[0-9]{4,}))?: (.*)", line)
            if match:
                require(match[1] in declarations and (not match[2] or match[2] in declarations), "Unknown note participant")
                events.append(("note", match[1], match[2], mermaid_unescape(match[3])))
                continue
            match = re.fullmatch(r"(p[0-9]{4,})(->>|-->>)(p[0-9]{4,}): (.*)", line)
            if match:
                require(match[1] in declarations and match[3] in declarations, "Unknown Mermaid message participant")
                events.append(("message", match[1], match[3], match[2], mermaid_unescape(match[4])))
                continue
            match = re.fullmatch(r"(alt|opt|loop|par|critical|break|else|and|option) (.*)", line)
            if match:
                if match[1] in {"else", "and", "option"}:
                    require(bool(stack) and (match[1], stack[-1]) in {("else", "alt"), ("and", "par"), ("option", "critical")},
                            "Unmatched Mermaid fragment branch")
                else:
                    stack.append(match[1])
                events.append(("fragment", match[1], mermaid_unescape(match[2])))
                continue
            if line == "rect rgb(245, 248, 252)":
                stack.append("rect")
                events.append(("group",))
                continue
            if line == "end":
                require(bool(stack), "Unmatched Mermaid fragment end")
                stack.pop()
                events.append(("end",))
                continue
        raise SourceValidationError(f"Unsupported or unsafe Mermaid syntax: {line[:100]}")
    require(not stack, "Unclosed Mermaid fragment")
    return events


def validate_mermaid(path: Path, expected: str, kind: str) -> None:
    actual_events = parse_mermaid(path.read_text(encoding="utf-8"), kind)
    expected_events = parse_mermaid(expected, kind)
    require(actual_events == expected_events, f"Mermaid visible labels, directed multiedges, modes, or sequence differ: {path.name}")


def source_report(design: Design, model_path: Path, output: Path) -> dict:
    files = {key: {"path": name, "sha256": sha256(output / name), "bytes": (output / name).stat().st_size}
             for key, name in design.filenames.items()}
    coverage = {
        "componentIds": design.component_ids, "participantIds": design.participant_ids,
        "relationships": [{**{key: item[key] for key in ("id", "order")},
                           **{key: item["record"][key] for key in ("from", "to", "implementationMode")},
                           **({"direction": item["record"]["direction"]} if "direction" in item["record"] else {})}
                          for item in design.relationships],
        "sequence": [{**{key: item[key] for key in ("id", "order")},
                      **{key: item["record"][key] for key in ("from", "to", "implementationMode")}}
                     for item in design.sequence],
    }
    return {
        "schemaVersion": 1, "scenarioSlug": design.model["scenarioSlug"], "validation": "passed",
        "validationIssues": [], "stages": ["drawio", "mermaid"],
        "stageDetails": [
            {"name": "drawio", "order": 1, "validation": "passed", "inputSha256": sha256(model_path),
             "outputs": [files["drawio"]["path"]], "pages": list(PAGES)},
            {"name": "mermaid", "order": 2, "validation": "passed", "inputSha256": files["drawio"]["sha256"],
             "outputs": [files["architectureMermaid"]["path"], files["sequenceMermaid"]["path"]]},
        ],
        "model": {"path": model_path.name, "sha256": sha256(model_path)},
        "sources": files,
        "artifactOrder": [*design.filenames.values(), "source-report.json"],
        "coverage": coverage,
    }


def load_design(model_path: Path) -> Design:
    return Design(json.loads(model_path.read_text(encoding="utf-8-sig")))


def _mermaid_sources(design: Design, model_hash: str, drawio_hash: str) -> dict[str, tuple[str, str]]:
    return {
        "architectureMermaid": (architecture_mermaid(design, model_hash, drawio_hash), "flowchart LR"),
        "sequenceMermaid": (sequence_mermaid(design, model_hash, drawio_hash), "sequenceDiagram"),
    }


def generate(model_path: Path, output: Path) -> dict:
    design = load_design(model_path)
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "source-report.json"
    # A failed rerun cannot leave a prior success report beside partial sources.
    report_path.unlink(missing_ok=True)
    model_hash = sha256(model_path)
    drawio_path = output / design.filenames["drawio"]
    write_drawio(drawio_path, design, model_hash)
    recovered = validate_drawio(drawio_path, design, model_hash)
    # Mermaid is derived only from the on-disk Draw.io semantic roundtrip.
    mermaid_sources = _mermaid_sources(recovered, model_hash, sha256(drawio_path))
    for key, (source, kind) in mermaid_sources.items():
        path = output / recovered.filenames[key]
        path.write_text(source, encoding="utf-8", newline="\n")
        validate_mermaid(path, source, kind)
    report = source_report(recovered, model_path, output)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return validate(model_path, output)


def validate(model_path: Path, output: Path) -> dict:
    design = load_design(model_path)
    drawio_path = output / design.filenames["drawio"]
    recovered = validate_drawio(drawio_path, design, sha256(model_path))
    for key, (source, kind) in _mermaid_sources(recovered, sha256(model_path), sha256(drawio_path)).items():
        validate_mermaid(output / design.filenames[key], source, kind)
    expected = source_report(recovered, model_path, output)
    actual = json.loads((output / "source-report.json").read_text(encoding="utf-8"))
    require(actual == expected, "Source report stage order, source/model hashes, or canonical coverage differs")
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate", "validate"))
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = {"generate": generate, "validate": validate}[args.command](args.model, args.output)
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
        print(json.dumps({"validation": "failed", "validationIssues": [str(error)]}, ensure_ascii=True))
        return 1
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
