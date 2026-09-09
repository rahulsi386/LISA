"""Deterministic rectilinear routing over a NetworkX visibility grid."""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import networkx as nx


ENGINE = "Python NetworkX rectilinear"
SIDES = {"east": "east", "right": "east", "west": "west", "left": "west",
         "north": "north", "top": "north", "south": "south", "bottom": "south"}
Point = tuple[float, float]


def number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Geometry values must be finite numbers.")
    return float(value)


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @classmethod
    def read(cls, value: dict) -> Box:
        box = cls(*(number(value[key]) for key in ("x", "y", "width", "height")))
        if box.width <= 0 or box.height <= 0:
            raise ValueError("Box dimensions must be positive.")
        return box

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def inflate(self, padding: float) -> Box:
        return Box(self.x - padding, self.y - padding,
                   self.width + padding * 2, self.height + padding * 2)

    def contains(self, other: Box) -> bool:
        return (self.x <= other.x and self.y <= other.y
                and self.right >= other.right and self.bottom >= other.bottom)

    def intersects(self, other: Box) -> bool:
        return (self.x < other.right and self.right > other.x
                and self.y < other.bottom and self.bottom > other.y)

    def crosses(self, start: Point, end: Point, interior: bool = False) -> bool:
        padding = 1e-7 if interior else 0
        if start[0] == end[0]:
            return (self.x + padding <= start[0] <= self.right - padding
                    and max(start[1], end[1]) >= self.y + padding
                    and min(start[1], end[1]) <= self.bottom - padding)
        return (self.y + padding <= start[1] <= self.bottom - padding
                and max(start[0], end[0]) >= self.x + padding
                and min(start[0], end[0]) <= self.right - padding)


def simplify(points: list[Point]) -> list[Point]:
    result: list[Point] = []
    for point in points:
        if result and point == result[-1]:
            continue
        if len(result) >= 2:
            first, second = result[-2:]
            if ((first[0] == second[0] == point[0] and
                 min(first[1], point[1]) <= second[1] <= max(first[1], point[1])) or
                (first[1] == second[1] == point[1] and
                 min(first[0], point[0]) <= second[0] <= max(first[0], point[0]))):
                result[-1] = point
                continue
        result.append(point)
    return result


def length(points: list[Point]) -> float:
    return sum(abs(start[0] - end[0]) + abs(start[1] - end[1])
               for start, end in zip(points, points[1:]))


def preference(edge: dict, endpoint: str) -> str | None:
    hint = edge.get(endpoint + "Side")
    if hint is None:
        hint = edge.get(endpoint + "Port")
    hint = hint.strip().lower() if isinstance(hint, str) else hint
    if hint in (None, "", "auto"):
        side = None
    elif hint in SIDES:
        side = SIDES[hint]
    else:
        raise ValueError(f"Unknown port preference '{hint}'.")
    offset = edge.get(endpoint + "Offset")
    if offset is not None and (not 0 <= number(offset) <= 1 or side is None):
        raise ValueError("Port offsets require an explicit side and a fraction between 0 and 1.")
    return side


class Router:
    def __init__(self, model: dict):
        self.width = number(model["canvasWidth"])
        self.height = number(model["canvasHeight"])
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Canvas dimensions must be positive.")
        self.padding = max(6.0, number(model.get("routePadding", 8)))
        self.nodes: dict[str, Box] = {}
        for node in sorted(model.get("nodes", []), key=lambda item: item["id"]):
            identity = node["id"]
            if not isinstance(identity, str) or not identity.strip() or identity in self.nodes:
                raise ValueError("Duplicate or empty node ID.")
            box = Box.read(node)
            if not Box(0, 0, self.width, self.height).contains(box):
                raise ValueError(f"Node '{identity}' is outside the canvas.")
            self.nodes[identity] = box
        self.edges = sorted(model.get("edges", []), key=lambda item: item["id"])
        identities = set()
        for edge in self.edges:
            identity = edge["id"]
            if not isinstance(identity, str) or not identity.strip() or identity in identities:
                raise ValueError("Duplicate or empty edge ID.")
            identities.add(identity)
            if edge["sourceId"] not in self.nodes or edge["targetId"] not in self.nodes:
                raise ValueError(f"Edge '{identity}' references an unknown node.")
            if number(edge.get("labelWidth", 100)) <= 0 or number(edge.get("labelHeight", 24)) <= 0:
                raise ValueError("Label dimensions must be positive.")
            for endpoint in ("source", "target"):
                preference(edge, endpoint)
        self.exclusions = [Box.read(box) for box in model.get("routingExclusions", [])]
        self.label_obstacles = ([box.inflate(3) for box in self.nodes.values()]
                                + self.exclusions
                                + [Box.read(box) for box in model.get("labelExclusions", [])])
        self.obstacles = [box.inflate(self.padding) for box in self.nodes.values()]
        self.obstacles += [box.inflate(self.padding) for box in self.exclusions
                           if not any(node.contains(box) for node in self.nodes.values())]
        self.graph = self.visibility_graph()

    def port(self, edge: dict, endpoint: str, side: str) -> tuple[Point, Point, int]:
        box = self.nodes[edge[endpoint + "Id"]]
        default = (0.35 if endpoint == "source" else 0.65) if edge["sourceId"] == edge["targetId"] else 0.5
        offset = edge.get(endpoint + "Offset")
        fraction = default if offset is None else number(offset)
        if side in ("east", "west"):
            coordinate = box.right if side == "east" else box.x
            point = (coordinate, box.y + box.height * fraction)
            stub = (coordinate + (self.padding if side == "east" else -self.padding), point[1])
            return point, stub, 0
        coordinate = box.bottom if side == "south" else box.y
        point = (box.x + box.width * fraction, coordinate)
        stub = (point[0], coordinate + (self.padding if side == "south" else -self.padding))
        return point, stub, 1

    def visibility_graph(self) -> nx.Graph:
        coordinates_x = {8.0, self.width - 8}
        coordinates_y = {8.0, self.height - 8}
        for box in self.obstacles:
            coordinates_x.update((box.x, box.right))
            coordinates_y.update((box.y, box.bottom))
        for edge in self.edges:
            for endpoint in ("source", "target"):
                for side in ("east", "west", "north", "south"):
                    _, stub, _ = self.port(edge, endpoint, side)
                    coordinates_x.add(stub[0])
                    coordinates_y.add(stub[1])
        horizontal = sorted(value for value in coordinates_x if 0 <= value <= self.width)
        vertical = sorted(value for value in coordinates_y if 0 <= value <= self.height)
        if len(horizontal) * len(vertical) > 250_000:
            raise ValueError("Routing grid exceeds the 250000-intersection safety limit.")
        graph = nx.Graph()
        for coordinate_y in vertical:
            for coordinate_x in horizontal:
                point = (coordinate_x, coordinate_y)
                if not any(box.crosses(point, point, interior=True) for box in self.obstacles):
                    graph.add_edge((point, 0), (point, 1), weight=24.0)
        for axis, primary, secondary in ((0, vertical, horizontal), (1, horizontal, vertical)):
            for fixed in primary:
                previous = None
                for moving in secondary:
                    point = (moving, fixed) if axis == 0 else (fixed, moving)
                    if (point, axis) not in graph:
                        previous = None
                        continue
                    if previous is not None and not any(
                        box.crosses(previous, point, interior=True) for box in self.obstacles
                    ):
                        graph.add_edge((previous, axis), (point, axis), weight=length([previous, point]))
                    previous = point
        return graph

    def route(self, edge: dict, source_side: str, target_side: str) -> list[Point]:
        source, start, source_axis = self.port(edge, "source", source_side)
        target, end, target_axis = self.port(edge, "target", target_side)
        path = nx.astar_path(
            self.graph, (start, source_axis), (end, target_axis),
            heuristic=lambda first, last: length([first[0], last[0]]), weight="weight",
        )
        points = simplify([source] + [state[0] for state in path] + [target])
        if len(points) < 2:
            raise ValueError(f"Edge '{edge['id']}' has no route.")
        for first, last in zip(points, points[1:]):
            for identity, box in self.nodes.items():
                own = identity in (edge["sourceId"], edge["targetId"])
                if box.inflate(-0.05 if own else 1).crosses(first, last):
                    raise ValueError(f"Edge '{edge['id']}' crosses node '{identity}'.")
            if any(box.crosses(first, last) for box in self.exclusions):
                raise ValueError(f"Edge '{edge['id']}' crosses a routing exclusion.")
        return points

    def sides(self, edge: dict) -> list[tuple[str, str]]:
        source = self.nodes[edge["sourceId"]]
        target = self.nodes[edge["targetId"]]
        delta_x = target.x + target.width / 2 - source.x - source.width / 2
        delta_y = target.y + target.height / 2 - source.y - source.height / 2
        if edge["sourceId"] == edge["targetId"]:
            preferred = ("east", "east")
        elif abs(delta_x) >= abs(delta_y):
            preferred = ("east", "west") if delta_x >= 0 else ("west", "east")
        else:
            preferred = ("south", "north") if delta_y >= 0 else ("north", "south")
        source_fixed, target_fixed = preference(edge, "source"), preference(edge, "target")
        choices = [preferred] + [(side, side) for side in ("south", "north", "east", "west")]
        choices += [(first, last) for first in ("east", "west", "north", "south")
                    for last in ("east", "west", "north", "south")]
        return list(dict.fromkeys((source_fixed or first, target_fixed or last) for first, last in choices))

    def solve(self) -> dict:
        routes = []
        for edge in self.edges:
            for source_side, target_side in self.sides(edge):
                try:
                    points = self.route(edge, source_side, target_side)
                    break
                except (nx.NetworkXNoPath, nx.NodeNotFound, ValueError):
                    continue
            else:
                raise ValueError(f"No collision-free route for edge '{edge['id']}'.")
            routes.append({"id": edge["id"], "sourceId": edge["sourceId"], "targetId": edge["targetId"],
                           "points": [{"x": point[0], "y": point[1]} for point in points],
                           "labelWidth": edge.get("labelWidth", 100), "labelHeight": edge.get("labelHeight", 24)})
        issues = self.place_labels(routes)
        attempts = 0
        for route, edge in zip(routes, self.edges):
            if "labelX" in route:
                continue
            original = route["points"]
            original_length = length([(point["x"], point["y"]) for point in original])
            allowance = 2 * sum(self.nodes[edge[key]].width + self.nodes[edge[key]].height
                                for key in ("sourceId", "targetId"))
            for source_side, target_side in self.sides(edge)[1:]:
                attempts += 1
                if attempts > 24:
                    break
                try:
                    points = self.route(edge, source_side, target_side)
                    if length(points) > original_length + allowance:
                        continue
                    route["points"] = [{"x": point[0], "y": point[1]} for point in points]
                    candidate = self.place_labels(routes)
                    if len(candidate) < len(issues):
                        issues = candidate
                        break
                except (nx.NetworkXNoPath, nx.NodeNotFound, ValueError):
                    pass
                route["points"] = original
                self.place_labels(routes)
        return {"engine": ENGINE, "routes": routes, "issues": self.place_labels(routes)}

    def place_labels(self, routes: list[dict]) -> list[str]:
        occupied: list[Box] = []
        issues = []
        segments = []
        for route in routes:
            points = [(point["x"], point["y"]) for point in route["points"]]
            segments.extend(zip(points, points[1:]))
        for route in routes:
            route.pop("labelX", None)
            route.pop("labelY", None)
            for box in label_candidates(route):
                if (not Box(8, 8, self.width - 16, self.height - 16).contains(box)
                    or any(obstacle.intersects(box) for obstacle in self.label_obstacles)
                    or any(other.inflate(4).intersects(box) for other in occupied)
                    or any(box.inflate(4).crosses(first, last) for first, last in segments)):
                    continue
                route["labelX"] = box.x + box.width / 2
                route["labelY"] = box.y + box.height / 2
                occupied.append(box)
                break
            else:
                issues.append(f"Could not place label for edge '{route['id']}' without collision.")
        return issues


def fractions(distance: float):
    yield 0.5
    offset = 8
    while offset <= distance / 2:
        yield 0.5 - offset / distance
        yield 0.5 + offset / distance
        offset += 8
    yield 0
    yield 1


def label_candidates(route: dict):
    points = [(point["x"], point["y"]) for point in route["points"]]
    segments = list(zip(points, points[1:]))
    segments.sort(key=lambda pair: (pair[0][1] != pair[1][1], -length(list(pair))))
    width, height = route["labelWidth"], route["labelHeight"]
    for first, last in segments:
        horizontal = first[1] == last[1]
        for fraction in fractions(length([first, last])):
            coordinate_x = first[0] + (last[0] - first[0]) * fraction
            coordinate_y = first[1] + (last[1] - first[1]) * fraction
            for gap in (8, 16, 24):
                for side in (-1, 1):
                    yield Box(coordinate_x - width / 2 + (0 if horizontal else side * (gap + width / 2)),
                              coordinate_y - height / 2 + (side * (gap + height / 2) if horizontal else 0),
                              width, height)


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: layout_engine.py <input.json> <output.json>", file=sys.stderr)
        return 2
    try:
        result = Router(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))).solve()
        status = 3 if result["issues"] else 0
    except (ValueError, KeyError, TypeError, OSError, nx.NetworkXException) as error:
        result = {"engine": ENGINE, "routes": [], "issues": [str(error)]}
        print(error, file=sys.stderr)
        status = 2
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())