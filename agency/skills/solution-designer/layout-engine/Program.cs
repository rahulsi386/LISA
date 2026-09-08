using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Msagl.Core.Geometry;
using Microsoft.Msagl.Core.Geometry.Curves;
using Microsoft.Msagl.Core.Layout;
using Microsoft.Msagl.Routing;
using Microsoft.Msagl.Routing.Rectilinear;

if (args.Length != 2)
{
    Console.Error.WriteLine("Usage: SolutionDesigner.LayoutEngine <input.json> <output.json>");
    return 2;
}

var jsonOptions = new JsonSerializerOptions
{
    PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    WriteIndented = true,
    DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
};

try
{
    var input = JsonSerializer.Deserialize<LayoutInput>(
        await File.ReadAllTextAsync(args[0]),
        jsonOptions
    ) ?? throw new InvalidOperationException("Layout input is empty.");
    var output = Route(input);
    await File.WriteAllTextAsync(
        args[1],
        JsonSerializer.Serialize(output, jsonOptions) + Environment.NewLine
    );
    return output.Issues.Count == 0 ? 0 : 3;
}
catch (Exception exception)
{
    var failure = new LayoutOutput
    {
        Engine = "MSAGL 1.1.6",
        Routes = [],
        Issues = [exception.Message],
    };
    await File.WriteAllTextAsync(
        args[1],
        JsonSerializer.Serialize(failure, jsonOptions) + Environment.NewLine
    );
    Console.Error.WriteLine(exception);
    return 2;
}

static LayoutOutput Route(LayoutInput input)
{
    if (input.CanvasWidth <= 0 || input.CanvasHeight <= 0)
    {
        throw new InvalidOperationException("Canvas dimensions must be positive.");
    }

    var graph = new GeometryGraph();
    var nodes = new Dictionary<string, Node>(StringComparer.Ordinal);
    foreach (var item in input.Nodes.OrderBy(item => item.Id, StringComparer.Ordinal))
    {
        if (string.IsNullOrWhiteSpace(item.Id)
            || !WithinCanvas(new Box(item.X, item.Y, item.Width, item.Height),
                input.CanvasWidth, input.CanvasHeight, 0))
        {
            throw new InvalidOperationException($"Node '{item.Id}' is outside the canvas.");
        }
        if (!nodes.TryAdd(item.Id, CreateNode(item)))
        {
            throw new InvalidOperationException($"Duplicate node ID: {item.Id}");
        }
        graph.Nodes.Add(nodes[item.Id]);
    }

    AddBoundaryObstacles(graph, input.CanvasWidth, input.CanvasHeight);
    foreach (var box in input.RoutingExclusions)
    {
        if (!ValidBox(box))
        {
            throw new InvalidOperationException("Invalid routing exclusion geometry.");
        }
        // Card text is already protected by its card. Adding overlapping obstacles
        // would unnecessarily merge their ports into MSAGL obstacle groups.
        if (input.Nodes.Any(node => new Box(node.X, node.Y, node.Width, node.Height).Contains(box)))
        {
            continue;
        }
        graph.Nodes.Add(CreateNode(new NodeInput
        {
            Id = "__text", X = box.X, Y = box.Y, Width = box.Width, Height = box.Height,
        }));
    }
    var shapes = graph.Nodes.ToDictionary(node => node,
        node => new Shape(node.BoundaryCurve));

    var edges = new List<Edge>();
    var edgeInputs = new Dictionary<Edge, EdgeInput>();
    var edgeIds = new HashSet<string>(StringComparer.Ordinal);
    foreach (var item in input.Edges.OrderBy(item => item.Id, StringComparer.Ordinal))
    {
        if (string.IsNullOrWhiteSpace(item.Id) || !edgeIds.Add(item.Id))
        {
            throw new InvalidOperationException($"Duplicate or empty edge ID: '{item.Id}'.");
        }
        if (!double.IsFinite(item.LabelWidth) || !double.IsFinite(item.LabelHeight)
            || item.LabelWidth <= 0 || item.LabelHeight <= 0)
        {
            throw new InvalidOperationException($"Edge '{item.Id}' has invalid label dimensions.");
        }
        if (!nodes.TryGetValue(item.SourceId, out var source)
            || !nodes.TryGetValue(item.TargetId, out var target))
        {
            throw new InvalidOperationException(
                $"Edge '{item.Id}' references an unknown node."
            );
        }
        var edge = new Edge(source, target) { UserData = item.Id };
        var sourceSide = item.SourceSide ?? item.SourcePort;
        var targetSide = item.TargetSide ?? item.TargetPort;
        ValidateOffset(sourceSide, item.SourceOffset);
        ValidateOffset(targetSide, item.TargetOffset);
        edge.SourcePort = CreatePort(source, sourceSide, item.SourceOffset ?? (source == target ? 0.35 : 0.5));
        edge.TargetPort = CreatePort(target, targetSide, item.TargetOffset ?? (source == target ? 0.65 : 0.5));
        edge.EdgeGeometry.SourceArrowhead = null;
        edge.EdgeGeometry.TargetArrowhead = null;
        shapes[source].Ports.Insert(edge.SourcePort);
        shapes[target].Ports.Insert(edge.TargetPort);
        graph.Edges.Add(edge);
        edges.Add(edge);
        edgeInputs.Add(edge, item);
    }

    var router = new RectilinearEdgeRouter(shapes.Values, Math.Max(6, input.RoutePadding), 0, true)
    {
        RouteToCenterOfObstacles = false,
    };
    foreach (var edge in edges) { router.AddEdgeGeometryToRoute(edge.EdgeGeometry); }
    if (edges.Count > 0) { router.Run(); }

    var routed = new List<RouteOutput>();
    foreach (var edge in edges)
    {
        var item = edgeInputs[edge];
        var points = Simplify(ExtractPoints(edge.Curve).Select(ToSvgPoint).ToList());
        if (points.Count < 2)
        {
            throw new InvalidOperationException($"MSAGL did not route edge '{item.Id}'.");
        }
        ValidateRoute(input, item, points);
        foreach (var (side, port, point) in new[]
        {
            (item.SourceSide ?? item.SourcePort, edge.SourcePort, points[0]),
            (item.TargetSide ?? item.TargetPort, edge.TargetPort, points[^1]),
        })
        {
            if (!string.IsNullOrWhiteSpace(side) && !side.Trim().Equals("auto", StringComparison.OrdinalIgnoreCase)
                && (Math.Abs(point.X - port.Location.X) > 1 || Math.Abs(point.Y + port.Location.Y) > 1))
            {
                throw new InvalidOperationException($"Edge '{item.Id}' did not preserve its requested port.");
            }
        }
        routed.Add(new RouteOutput
        {
            Id = item.Id,
            SourceId = item.SourceId,
            TargetId = item.TargetId,
            Points = points,
            LabelWidth = item.LabelWidth,
            LabelHeight = item.LabelHeight,
        });
    }

    var issues = PlaceLabels(input, routed);
    if (issues.Count > 0)
    {
        issues = RetryLabelRoutes(input, graph.Nodes, nodes, routed, issues);
    }
    return new LayoutOutput
    {
        Engine = "MSAGL 1.1.6 rectilinear",
        Routes = routed,
        Issues = issues,
    };
}

static List<string> RetryLabelRoutes(
    LayoutInput input, IEnumerable<Node> obstacles, Dictionary<string, Node> nodes,
    List<RouteOutput> routes, List<string> issues)
{
    var attempts = 0;
    foreach (var route in routes.Where(item => item.LabelX is null).ToList())
    {
        var item = input.Edges.Single(edge => edge.Id == route.Id);
        var sourceHint = item.SourceSide ?? item.SourcePort;
        var targetHint = item.TargetSide ?? item.TargetPort;
        var sourceFixed = !string.IsNullOrWhiteSpace(sourceHint) && !sourceHint.Trim().Equals("auto", StringComparison.OrdinalIgnoreCase);
        var targetFixed = !string.IsNullOrWhiteSpace(targetHint) && !targetHint.Trim().Equals("auto", StringComparison.OrdinalIgnoreCase);
        if (sourceFixed && targetFixed) { continue; }
        var original = route.Points;
        var source = nodes[item.SourceId];
        var target = nodes[item.TargetId];
        var horizontal = Math.Abs(source.Center.X - target.Center.X) >= Math.Abs(source.Center.Y - target.Center.Y);
        var sides = horizontal ? new[] { "south", "north", "east", "west" } : new[] { "east", "west", "south", "north" };
        foreach (var side in sides)
        {
            if (++attempts > 24) { return PlaceLabels(input, routes); }
            try
            {
                // Move the connector to a nearby free lane rather than floating
                // its label away. Explicit caller port constraints remain fixed.
                var edge = new Edge(source, target)
                {
                    SourcePort = CreatePort(source, sourceFixed ? sourceHint : side, item.SourceOffset ?? (source == target ? 0.35 : 0.5)),
                    TargetPort = CreatePort(target, targetFixed ? targetHint : side, item.TargetOffset ?? (source == target ? 0.65 : 0.5)),
                };
                edge.EdgeGeometry.SourceArrowhead = null;
                edge.EdgeGeometry.TargetArrowhead = null;
                var shapes = obstacles.ToDictionary(node => node, node => new Shape(node.BoundaryCurve));
                shapes[source].Ports.Insert(edge.SourcePort);
                shapes[target].Ports.Insert(edge.TargetPort);
                var router = new RectilinearEdgeRouter(shapes.Values, Math.Max(6, input.RoutePadding), 0, true)
                {
                    RouteToCenterOfObstacles = false,
                };
                router.AddEdgeGeometryToRoute(edge.EdgeGeometry);
                router.Run();
                var points = Simplify(ExtractPoints(edge.Curve).Select(ToSvgPoint).ToList());
                if (points.Count < 2 || RouteLength(points) > RouteLength(original) + 2 * (
                    source.BoundingBox.Width + source.BoundingBox.Height + target.BoundingBox.Width + target.BoundingBox.Height))
                {
                    continue;
                }
                ValidateRoute(input, item, points);
                if ((sourceFixed && (Math.Abs(points[0].X - edge.SourcePort.Location.X) > 1 || Math.Abs(points[0].Y + edge.SourcePort.Location.Y) > 1))
                    || (targetFixed && (Math.Abs(points[^1].X - edge.TargetPort.Location.X) > 1 || Math.Abs(points[^1].Y + edge.TargetPort.Location.Y) > 1)))
                {
                    continue;
                }
                route.Points = points;
                var candidateIssues = PlaceLabels(input, routes);
                if (candidateIssues.Count < issues.Count)
                {
                    issues = candidateIssues;
                    break;
                }
            }
            catch (InvalidOperationException)
            {
                // An infeasible alternative is not a successful placement.
            }
            route.Points = original;
            PlaceLabels(input, routes);
        }
    }
    return PlaceLabels(input, routes);
}

static double RouteLength(IReadOnlyList<SvgPoint> points) =>
    points.Zip(points.Skip(1)).Sum(segment =>
        Math.Abs(segment.First.X - segment.Second.X) + Math.Abs(segment.First.Y - segment.Second.Y));

static void ValidateOffset(string? side, double? offset)
{
    if (offset is null) { return; }
    if (!double.IsFinite(offset.Value) || offset < 0 || offset > 1)
    {
        throw new InvalidOperationException("Port offsets must be fractions between 0 and 1.");
    }
    if (string.IsNullOrWhiteSpace(side) || side.Trim().Equals("auto", StringComparison.OrdinalIgnoreCase))
    {
        throw new InvalidOperationException("A port offset requires an explicit side preference.");
    }
}

static Port CreatePort(Node node, string? hint, double fraction)
{
    var side = hint?.Trim().ToLowerInvariant();
    var bounds = node.BoundingBox;
    var location = side switch
    {
        null or "" or "auto" when CloseScalar(fraction, 0.5) => node.Center,
        null or "" or "auto" or "east" or "right" => new Point(bounds.Right, bounds.Top - bounds.Height * fraction),
        "west" or "left" => new Point(bounds.Left, bounds.Top - bounds.Height * fraction),
        "north" or "top" => new Point(bounds.Left + bounds.Width * fraction, bounds.Top),
        "south" or "bottom" => new Point(bounds.Left + bounds.Width * fraction, bounds.Bottom),
        _ => throw new InvalidOperationException($"Unknown port preference '{hint}'."),
    };
    return new FloatingPort(node.BoundaryCurve, location);
}

static void ValidateRoute(LayoutInput input, EdgeInput edge, List<SvgPoint> points)
{
    foreach (var (id, point) in new[] { (edge.SourceId, points[0]), (edge.TargetId, points[^1]) })
    {
        var node = input.Nodes.Single(item => item.Id == id);
        var box = new Box(node.X, node.Y, node.Width, node.Height);
        var onHorizontal = point.X >= box.X - 1 && point.X <= box.Right + 1
            && Math.Min(Math.Abs(point.Y - box.Y), Math.Abs(point.Y - box.Bottom)) <= 1;
        var onVertical = point.Y >= box.Y - 1 && point.Y <= box.Bottom + 1
            && Math.Min(Math.Abs(point.X - box.X), Math.Abs(point.X - box.Right)) <= 1;
        if (!onHorizontal && !onVertical)
        {
            throw new InvalidOperationException($"Edge '{edge.Id}' is not anchored to node '{id}'.");
        }
    }
    for (var i = 1; i < points.Count; i++)
    {
        var a = points[i - 1];
        var b = points[i];
        if (!double.IsFinite(a.X) || !double.IsFinite(a.Y)
            || !double.IsFinite(b.X) || !double.IsFinite(b.Y)
            || (!CloseScalar(a.X, b.X) && !CloseScalar(a.Y, b.Y))
            || a.X < 0 || a.Y < 0 || b.X < 0 || b.Y < 0
            || a.X > input.CanvasWidth || b.X > input.CanvasWidth
            || a.Y > input.CanvasHeight || b.Y > input.CanvasHeight)
        {
            throw new InvalidOperationException($"Edge '{edge.Id}' has invalid orthogonal geometry.");
        }
        foreach (var node in input.Nodes)
        {
            var own = node.Id == edge.SourceId || node.Id == edge.TargetId;
            var box = new Box(node.X, node.Y, node.Width, node.Height).Inflate(own ? -0.05 : 1);
            if (box.Crosses(a, b))
            {
                throw new InvalidOperationException($"Edge '{edge.Id}' crosses node '{node.Id}'.");
            }
        }
        if (input.RoutingExclusions.Any(box => box.Crosses(a, b)))
        {
            throw new InvalidOperationException($"Edge '{edge.Id}' crosses a routing exclusion.");
        }
    }
}

static Node CreateNode(NodeInput item)
{
    if (!ValidBox(new Box(item.X, item.Y, item.Width, item.Height)))
    {
        throw new InvalidOperationException($"Node '{item.Id}' has invalid dimensions.");
    }
    var center = new Point(
        item.X + (item.Width / 2),
        -1 * (item.Y + (item.Height / 2))
    );
    return new Node(CurveFactory.CreateRectangle(item.Width, item.Height, center))
    {
        UserData = item.Id,
    };
}

static void AddBoundaryObstacles(GeometryGraph graph, double width, double height)
{
    const double thickness = 80;
    var boundaries = new[]
    {
        new NodeInput { Id = "__left", X = -thickness, Y = -thickness, Width = thickness, Height = height + (2 * thickness) },
        new NodeInput { Id = "__right", X = width, Y = -thickness, Width = thickness, Height = height + (2 * thickness) },
        new NodeInput { Id = "__top", X = 0, Y = -thickness, Width = width, Height = thickness },
        new NodeInput { Id = "__bottom", X = 0, Y = height, Width = width, Height = thickness },
    };
    foreach (var boundary in boundaries)
    {
        graph.Nodes.Add(CreateNode(boundary));
    }
}

static IEnumerable<Point> ExtractPoints(ICurve? curve)
{
    if (curve is null)
    {
        return [];
    }
    if (curve is Curve composite)
    {
        var points = new List<Point>();
        foreach (var segment in composite.Segments)
        {
            var segmentPoints = ExtractPoints(segment).ToList();
            if (points.Count > 0 && segmentPoints.Count > 0
                && ClosePoint(points[^1], segmentPoints[0]))
            {
                segmentPoints.RemoveAt(0);
            }
            points.AddRange(segmentPoints);
        }
        return points;
    }
    if (curve is Polyline polyline)
    {
        var points = new List<Point>();
        for (var point = polyline.StartPoint; point is not null; point = point.Next)
        {
            points.Add(point.Point);
        }
        return points;
    }
    return [curve.Start, curve.End];
}

static SvgPoint ToSvgPoint(Point point) => new()
{
    X = Math.Round(point.X, 2),
    Y = Math.Round(-point.Y, 2),
};

static List<SvgPoint> Simplify(List<SvgPoint> points)
{
    var result = new List<SvgPoint>();
    foreach (var point in points)
    {
        if (result.Count > 0 && CloseSvg(result[^1], point))
        {
            continue;
        }
        if (result.Count >= 2)
        {
            var a = result[^2];
            var b = result[^1];
            if ((CloseScalar(a.X, b.X) && CloseScalar(b.X, point.X))
                || (CloseScalar(a.Y, b.Y) && CloseScalar(b.Y, point.Y)))
            {
                result[^1] = point;
                continue;
            }
        }
        result.Add(point);
    }
    return result;
}

static List<string> PlaceLabels(LayoutInput input, List<RouteOutput> routes)
{
    var issues = new List<string>();
    var occupied = new List<Box>();
    var nodeBoxes = input.Nodes.Select(item => new Box(
        item.X - 3,
        item.Y - 3,
        item.Width + 6,
        item.Height + 6
    )).ToList();
    foreach (var box in input.LabelExclusions.Concat(input.RoutingExclusions))
    {
        if (!ValidBox(box)) { throw new InvalidOperationException("Invalid label exclusion geometry."); }
        nodeBoxes.Add(box);
    }
    var segments = routes.SelectMany(route => route.Points.Zip(route.Points.Skip(1))).ToList();

    foreach (var route in routes.OrderBy(item => item.Id, StringComparer.Ordinal))
    {
        route.LabelX = null;
        route.LabelY = null;
        var candidates = BuildLabelCandidates(route);
        Box? selected = null;
        foreach (var candidate in candidates)
        {
            if (!WithinCanvas(candidate, input.CanvasWidth, input.CanvasHeight, 8)
                || nodeBoxes.Any(box => box.Intersects(candidate))
                || occupied.Any(box => box.Inflate(4).Intersects(candidate))
                || segments.Any(segment => candidate.Inflate(4).Crosses(segment.First, segment.Second)))
            {
                continue;
            }
            selected = candidate;
            break;
        }
        if (selected is null)
        {
            issues.Add($"MSAGL could not place label for edge '{route.Id}' without collision.");
            continue;
        }
        occupied.Add(selected);
        route.LabelX = Math.Round(selected.X + (selected.Width / 2), 2);
        route.LabelY = Math.Round(selected.Y + (selected.Height / 2), 2);
    }
    return issues;
}

static IEnumerable<Box> BuildLabelCandidates(RouteOutput route)
{
    var horizontal = new List<(SvgPoint A, SvgPoint B, double Length)>();
    for (var index = 0; index < route.Points.Count - 1; index++)
    {
        var a = route.Points[index];
        var b = route.Points[index + 1];
        if (CloseScalar(a.Y, b.Y))
        {
            horizontal.Add((a, b, Math.Abs(a.X - b.X)));
        }
    }
    foreach (var segment in horizontal.OrderByDescending(item => item.Length))
    {
        foreach (var fraction in LabelFractions(segment.Length))
        {
            var x = segment.A.X + ((segment.B.X - segment.A.X) * fraction);
            foreach (var gap in new[] { 8d, 16d, 24d })
            {
                foreach (var side in new[] { -1d, 1d })
                {
                    yield return new Box(
                        x - (route.LabelWidth / 2),
                        segment.A.Y + side * (gap + route.LabelHeight / 2) - route.LabelHeight / 2,
                        route.LabelWidth,
                        route.LabelHeight
                    );
                }
            }
        }
    }
    for (var index = 0; index < route.Points.Count - 1; index++)
    {
        var a = route.Points[index];
        var b = route.Points[index + 1];
        if (!CloseScalar(a.X, b.X))
        {
            continue;
        }
        foreach (var fraction in LabelFractions(Math.Abs(a.Y - b.Y)))
        {
            var y = a.Y + ((b.Y - a.Y) * fraction);
            foreach (var distance in new[] { 8d, 16d, 24d })
            {
                foreach (var side in new[] { -1d, 1d })
                {
                    var x = a.X + side * ((route.LabelWidth / 2) + distance);
                    yield return new Box(
                        x - (route.LabelWidth / 2),
                        y - (route.LabelHeight / 2),
                        route.LabelWidth,
                        route.LabelHeight
                    );
                }
            }
        }
    }
}

static IEnumerable<double> LabelFractions(double length)
{
    yield return 0.5;
    // A small free interval between card and section headers can fall entirely
    // between coarse percentage samples. Search along the line, never away from it.
    for (var offset = 8d; offset <= length / 2; offset += 8)
    {
        yield return 0.5 - offset / length;
        yield return 0.5 + offset / length;
    }
    yield return 0;
    yield return 1;
}

static bool ValidBox(Box box) =>
    double.IsFinite(box.X) && double.IsFinite(box.Y)
    && double.IsFinite(box.Width) && double.IsFinite(box.Height)
    && box.Width > 0 && box.Height > 0;

static bool WithinCanvas(Box box, double width, double height, double margin) =>
    box.X >= margin && box.Y >= margin
    && box.Right <= width - margin && box.Bottom <= height - margin;

static bool ClosePoint(Point a, Point b) =>
    CloseScalar(a.X, b.X) && CloseScalar(a.Y, b.Y);
static bool CloseSvg(SvgPoint a, SvgPoint b) =>
    CloseScalar(a.X, b.X) && CloseScalar(a.Y, b.Y);
static bool CloseScalar(double a, double b) => Math.Abs(a - b) < 0.1;

sealed class LayoutInput
{
    public double CanvasWidth { get; set; }
    public double CanvasHeight { get; set; }
    public double RoutePadding { get; set; } = 8;
    public List<NodeInput> Nodes { get; set; } = [];
    public List<EdgeInput> Edges { get; set; } = [];
    public List<Box> LabelExclusions { get; set; } = [];
    public List<Box> RoutingExclusions { get; set; } = [];
}

sealed class NodeInput
{
    public string Id { get; set; } = "";
    public double X { get; set; }
    public double Y { get; set; }
    public double Width { get; set; }
    public double Height { get; set; }
}

sealed class EdgeInput
{
    public string Id { get; set; } = "";
    public string SourceId { get; set; } = "";
    public string TargetId { get; set; } = "";
    public string Label { get; set; } = "";
    public string? SourcePort { get; set; }
    public string? TargetPort { get; set; }
    public string? SourceSide { get; set; }
    public string? TargetSide { get; set; }
    public double? SourceOffset { get; set; }
    public double? TargetOffset { get; set; }
    public double LabelWidth { get; set; } = 100;
    public double LabelHeight { get; set; } = 24;
}

sealed class LayoutOutput
{
    public string Engine { get; set; } = "";
    public List<RouteOutput> Routes { get; set; } = [];
    public List<string> Issues { get; set; } = [];
}

sealed class RouteOutput
{
    public string Id { get; set; } = "";
    public string SourceId { get; set; } = "";
    public string TargetId { get; set; } = "";
    public List<SvgPoint> Points { get; set; } = [];
    public double LabelWidth { get; set; }
    public double LabelHeight { get; set; }
    public double? LabelX { get; set; }
    public double? LabelY { get; set; }
}

sealed class SvgPoint
{
    public double X { get; set; }
    public double Y { get; set; }
}

sealed class Box
{
    public Box() { }
    public Box(double x, double y, double width, double height)
    {
        X = x;
        Y = y;
        Width = width;
        Height = height;
    }

    public double X { get; set; }
    public double Y { get; set; }
    public double Width { get; set; }
    public double Height { get; set; }
    [JsonIgnore]
    public double Right => X + Width;
    [JsonIgnore]
    public double Bottom => Y + Height;

    public bool Intersects(Box other) =>
        X < other.Right && Right > other.X && Y < other.Bottom && Bottom > other.Y;

    public bool Contains(Box other) =>
        other.X >= X && other.Y >= Y && other.Right <= Right && other.Bottom <= Bottom;

    public Box Inflate(double padding) =>
        new(X - padding, Y - padding, Width + padding * 2, Height + padding * 2);

    public bool Crosses(SvgPoint a, SvgPoint b) =>
        Math.Abs(a.X - b.X) < 0.1
            ? a.X >= X && a.X <= Right && Math.Max(a.Y, b.Y) >= Y && Math.Min(a.Y, b.Y) <= Bottom
            : a.Y >= Y && a.Y <= Bottom && Math.Max(a.X, b.X) >= X && Math.Min(a.X, b.X) <= Right;
}
