using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Msagl.Core.Geometry;
using Microsoft.Msagl.Core.Geometry.Curves;
using Microsoft.Msagl.Core.Layout;
using Microsoft.Msagl.Core.Routing;
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
    foreach (var item in input.Nodes)
    {
        if (!nodes.TryAdd(item.Id, CreateNode(item)))
        {
            throw new InvalidOperationException($"Duplicate node ID: {item.Id}");
        }
        graph.Nodes.Add(nodes[item.Id]);
    }

    AddBoundaryObstacles(graph, input.CanvasWidth, input.CanvasHeight);

    var edges = new List<Edge>();
    var edgeInputs = new Dictionary<Edge, EdgeInput>();
    foreach (var item in input.Edges)
    {
        if (!nodes.TryGetValue(item.SourceId, out var source)
            || !nodes.TryGetValue(item.TargetId, out var target))
        {
            throw new InvalidOperationException(
                $"Edge '{item.Id}' references an unknown node."
            );
        }
        var edge = new Edge(source, target) { UserData = item.Id };
        graph.Edges.Add(edge);
        edges.Add(edge);
        edgeInputs.Add(edge, item);
    }

    RectilinearInteractiveEditor.CreatePortsAndRouteEdges(
        0,
        Math.Max(6, input.RoutePadding),
        graph.Nodes,
        edges,
        EdgeRoutingMode.Rectilinear,
        true,
        false
    );

    var routed = new List<RouteOutput>();
    foreach (var edge in edges)
    {
        var item = edgeInputs[edge];
        var points = Simplify(ExtractPoints(edge.Curve).Select(ToSvgPoint).ToList());
        if (points.Count < 2)
        {
            throw new InvalidOperationException($"MSAGL did not route edge '{item.Id}'.");
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
    return new LayoutOutput
    {
        Engine = "MSAGL 1.1.6 rectilinear",
        Routes = routed,
        Issues = issues,
    };
}

static Node CreateNode(NodeInput item)
{
    if (item.Width <= 0 || item.Height <= 0)
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
    nodeBoxes.AddRange(input.LabelExclusions);

    foreach (var route in routes.OrderBy(item => item.Id, StringComparer.Ordinal))
    {
        var candidates = BuildLabelCandidates(route);
        Box? selected = null;
        foreach (var candidate in candidates)
        {
            if (!WithinCanvas(candidate, input.CanvasWidth, input.CanvasHeight, 8)
                || nodeBoxes.Any(box => box.Intersects(candidate))
                || occupied.Any(box => box.Intersects(candidate)))
            {
                continue;
            }
            selected = candidate;
            break;
        }
        if (selected is null)
        {
            issues.Add($"MSAGL could not place label for edge '{route.Id}' without collision.");
            var midpoint = Midpoint(route.Points);
            selected = new Box(
                midpoint.X - (route.LabelWidth / 2),
                midpoint.Y - (route.LabelHeight / 2),
                route.LabelWidth,
                route.LabelHeight
            );
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
        foreach (var fraction in new[] { 0.5, 0.35, 0.65, 0.2, 0.25, 0.75, 0.8 })
        {
            var x = segment.A.X + ((segment.B.X - segment.A.X) * fraction);
            foreach (var offset in new[]
                     {
                         -20d, 20d, -44d, 44d, -72d, 72d,
                         -104d, 104d, -140d, 140d, 0d,
                     })
            {
                yield return new Box(
                    x - (route.LabelWidth / 2),
                    segment.A.Y + offset - (route.LabelHeight / 2),
                    route.LabelWidth,
                    route.LabelHeight
                );
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
        foreach (var fraction in new[] { 0.5, 0.35, 0.65, 0.2, 0.25, 0.75, 0.8 })
        {
            var y = a.Y + ((b.Y - a.Y) * fraction);
            foreach (var distance in new[] { 18d, 50d, 86d, 122d, 164d })
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

static SvgPoint Midpoint(IReadOnlyList<SvgPoint> points)
{
    var index = Math.Max(0, (points.Count - 2) / 2);
    return new SvgPoint
    {
        X = (points[index].X + points[index + 1].X) / 2,
        Y = (points[index].Y + points[index + 1].Y) / 2,
    };
}

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
    public double LabelX { get; set; }
    public double LabelY { get; set; }
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
}
