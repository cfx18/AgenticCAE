using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.BoundaryRepresentation;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;

namespace EvoCad.AutoCAD
{
    public sealed class TopologyCommands
    {
        [CommandMethod("EVOCAD_EXPORT_TOPOLOGY", CommandFlags.Session)]
        public static void ExportTopology()
        {
            string output = Environment.GetEnvironmentVariable("EVOCAD_TOPOLOGY_OUTPUT");
            if (String.IsNullOrWhiteSpace(output))
                throw new InvalidOperationException("EVOCAD_TOPOLOGY_OUTPUT is not set");

            Document document = Application.DocumentManager.MdiActiveDocument;
            Database database = document.Database;
            List<string> entities = new List<string>();
            List<string> errors = new List<string>();

            using (Transaction transaction = database.TransactionManager.StartTransaction())
            {
                BlockTable table = (BlockTable)transaction.GetObject(database.BlockTableId, OpenMode.ForRead);
                BlockTableRecord model = (BlockTableRecord)transaction.GetObject(table[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                foreach (ObjectId id in model)
                {
                    Entity entity = transaction.GetObject(id, OpenMode.ForRead) as Entity;
                    if (!(entity is Solid3d) && !(entity is Autodesk.AutoCAD.DatabaseServices.Surface) && !(entity is Region))
                        continue;
                    try
                    {
                        entities.Add(ExportEntity(entity));
                    }
                    catch (System.Exception exception)
                    {
                        Autodesk.AutoCAD.BoundaryRepresentation.Exception brepException = exception as Autodesk.AutoCAD.BoundaryRepresentation.Exception;
                        errors.Add(JsonObject(new Dictionary<string, string> {
                            { "handle", Quote(entity.Handle.ToString()) },
                            { "type", Quote(entity.GetType().Name) },
                            { "message", Quote(exception.GetType().Name + ": " + exception.Message) },
                            { "error_status", Quote(brepException == null ? "" : brepException.ErrorStatus.ToString()) },
                            { "stack_trace", Quote(exception.StackTrace ?? "") }
                        }));
                    }
                }
                transaction.Commit();
            }

            string json = JsonObject(new Dictionary<string, string> {
                { "schema_version", Quote("1.0") },
                { "source_dwg", Quote(database.Filename ?? "") },
                { "generated_at", Quote(DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture)) },
                { "coordinate_system", Quote("WCS") },
                { "entities", JsonArray(entities) },
                { "errors", JsonArray(errors) }
            });
            string fullPath = Path.GetFullPath(output);
            Directory.CreateDirectory(Path.GetDirectoryName(fullPath));
            File.WriteAllText(fullPath, json + Environment.NewLine, new UTF8Encoding(false));
            document.Editor.WriteMessage("\nEVOCAD_TOPOLOGY_OK " + fullPath);
        }

        [CommandMethod("EVOCAD_LOCATE_POINTS", CommandFlags.Session)]
        public static void LocatePoints()
        {
            string input = Environment.GetEnvironmentVariable("EVOCAD_FACE_QUERY_INPUT");
            string output = Environment.GetEnvironmentVariable("EVOCAD_FACE_QUERY_OUTPUT");
            if (String.IsNullOrWhiteSpace(input) || String.IsNullOrWhiteSpace(output))
                throw new InvalidOperationException("EVOCAD face-query paths are not set");
            Document document = Application.DocumentManager.MdiActiveDocument;
            Database database = document.Database;
            List<QueryFace> faces = new List<QueryFace>();
            List<string> results = new List<string>();
            Vector3d queryTranslation = new Vector3d(0, 0, 0);
            try
            {
                using (Transaction transaction = database.TransactionManager.StartTransaction())
                {
                    BlockTable table = (BlockTable)transaction.GetObject(database.BlockTableId, OpenMode.ForRead);
                    BlockTableRecord model = (BlockTableRecord)transaction.GetObject(table[BlockTableRecord.ModelSpace], OpenMode.ForRead);
                    foreach (ObjectId id in model)
                    {
                        Entity entity = transaction.GetObject(id, OpenMode.ForRead) as Entity;
                        if (!(entity is Solid3d) && !(entity is Autodesk.AutoCAD.DatabaseServices.Surface) && !(entity is Region)) continue;
                        FullSubentityPath path = new FullSubentityPath(new ObjectId[] { entity.ObjectId }, SubentityId.Null);
                        Brep brep = new Brep(path);
                        foreach (Autodesk.AutoCAD.BoundaryRepresentation.Face face in brep.Faces)
                        {
                            faces.Add(new QueryFace {
                                Brep = brep, Face = face, EntityHandle = entity.Handle.ToString(),
                                FaceId = face.SubentityPath.SubentId.IndexPtr.ToInt64(),
                                Minimum = face.BoundBlock.GetMinimumPoint(), Maximum = face.BoundBlock.GetMaximumPoint()
                            });
                        }
                    }
                    string sourceCenterValue = Environment.GetEnvironmentVariable("EVOCAD_FACE_QUERY_SOURCE_CENTER");
                    if (!String.IsNullOrWhiteSpace(sourceCenterValue) && faces.Count > 0)
                    {
                        string[] centerFields = sourceCenterValue.Split(',');
                        if (centerFields.Length != 3) throw new InvalidDataException("Query source center must contain x,y,z");
                        Point3d sourceCenter = new Point3d(
                            Double.Parse(centerFields[0], CultureInfo.InvariantCulture),
                            Double.Parse(centerFields[1], CultureInfo.InvariantCulture),
                            Double.Parse(centerFields[2], CultureInfo.InvariantCulture));
                        Point3d minimum = faces[0].Minimum, maximum = faces[0].Maximum;
                        foreach (QueryFace face in faces)
                        {
                            minimum = new Point3d(Math.Min(minimum.X, face.Minimum.X), Math.Min(minimum.Y, face.Minimum.Y), Math.Min(minimum.Z, face.Minimum.Z));
                            maximum = new Point3d(Math.Max(maximum.X, face.Maximum.X), Math.Max(maximum.Y, face.Maximum.Y), Math.Max(maximum.Z, face.Maximum.Z));
                        }
                        Point3d nativeCenter = new Point3d((minimum.X + maximum.X) / 2, (minimum.Y + maximum.Y) / 2, (minimum.Z + maximum.Z) / 2);
                        queryTranslation = nativeCenter - sourceCenter;
                    }
                    foreach (string line in File.ReadAllLines(input, Encoding.UTF8))
                    {
                        if (String.IsNullOrWhiteSpace(line)) continue;
                        string[] fields = line.Split('\t');
                        if (fields.Length != 4) throw new InvalidDataException("Face query rows must contain id, x, y, z");
                        Point3d sourcePoint = new Point3d(
                            Double.Parse(fields[1], CultureInfo.InvariantCulture),
                            Double.Parse(fields[2], CultureInfo.InvariantCulture),
                            Double.Parse(fields[3], CultureInfo.InvariantCulture));
                        Point3d point = sourcePoint + queryTranslation;
                        QueryHit hit = ClosestFace(point, faces);
                        results.Add(JsonObject(new Dictionary<string, string> {
                            { "query_id", Quote(fields[0]) }, { "source_point", Point(sourcePoint) },
                            { "point", Point(point) },
                            { "entity_handle", Quote(hit == null ? "" : hit.Face.EntityHandle) },
                            { "face_id", Quote(hit == null ? "" : "f" + hit.Face.FaceId.ToString(CultureInfo.InvariantCulture)) },
                            { "distance", hit == null ? "null" : Number(hit.Distance) },
                            { "method", Quote(hit == null ? "unavailable" : hit.Method) }
                        }));
                    }
                    transaction.Commit();
                }
            }
            finally
            {
                foreach (QueryFace face in faces) face.Face.Dispose();
                HashSet<Brep> breps = new HashSet<Brep>();
                foreach (QueryFace face in faces) breps.Add(face.Brep);
                foreach (Brep brep in breps) brep.Dispose();
            }
            string json = JsonObject(new Dictionary<string, string> {
                { "schema_version", Quote("1.0") }, { "source_dwg", Quote(database.Filename ?? "") },
                { "source_to_native_translation", Vector(queryTranslation) },
                { "queries", JsonArray(results) }
            });
            string fullPath = Path.GetFullPath(output);
            Directory.CreateDirectory(Path.GetDirectoryName(fullPath));
            File.WriteAllText(fullPath, json + Environment.NewLine, new UTF8Encoding(false));
            document.Editor.WriteMessage("\nEVOCAD_FACE_QUERY_OK " + fullPath);
        }

        private static QueryHit ClosestFace(Point3d point, List<QueryFace> faces)
        {
            List<QueryFace> ordered = new List<QueryFace>(faces);
            ordered.Sort(delegate(QueryFace first, QueryFace second) {
                return BoxDistance(point, first.Minimum, first.Maximum).CompareTo(BoxDistance(point, second.Minimum, second.Maximum));
            });
            QueryHit best = null;
            foreach (QueryFace record in ordered)
            {
                if (best != null && BoxDistance(point, record.Minimum, record.Maximum) > best.Distance) break;
                double distance = Double.PositiveInfinity;
                string method = "";
                try
                {
                    using (Autodesk.AutoCAD.Geometry.Surface surface = record.Face.Surface)
                    {
                        Point3d closest = surface.ClosestPointTo(point);
                        PointContainment containment;
                        using (BrepEntity contained = record.Face.GetPointContainment(closest, out containment)) { }
                        if (containment != PointContainment.Outside)
                        {
                            distance = closest.DistanceTo(point);
                            method = containment == PointContainment.Inside ? "trimmed_surface" : "surface_boundary";
                        }
                    }
                    foreach (BoundaryLoop loop in record.Face.Loops)
                    {
                        using (loop)
                        foreach (Edge edge in loop.Edges)
                        {
                            using (edge)
                            using (Curve3d curve = edge.Curve)
                            {
                                double edgeDistance = curve.GetClosestPointTo(point).Point.DistanceTo(point);
                                if (edgeDistance < distance) { distance = edgeDistance; method = "trim_boundary"; }
                            }
                        }
                    }
                }
                catch (System.Exception) { continue; }
                if (!Double.IsInfinity(distance) && (best == null || distance < best.Distance))
                    best = new QueryHit { Face = record, Distance = distance, Method = method };
            }
            return best;
        }

        private static double BoxDistance(Point3d point, Point3d minimum, Point3d maximum)
        {
            double dx = Math.Max(Math.Max(minimum.X - point.X, point.X - maximum.X), 0.0);
            double dy = Math.Max(Math.Max(minimum.Y - point.Y, point.Y - maximum.Y), 0.0);
            double dz = Math.Max(Math.Max(minimum.Z - point.Z, point.Z - maximum.Z), 0.0);
            return Math.Sqrt(dx * dx + dy * dy + dz * dz);
        }

        private static string ExportEntity(Entity entity)
        {
            FullSubentityPath entityPath = new FullSubentityPath(
                new ObjectId[] { entity.ObjectId }, SubentityId.Null);
            using (Brep brep = new Brep(entityPath))
            {
                Dictionary<long, string> vertices = new Dictionary<long, string>();
                foreach (Autodesk.AutoCAD.BoundaryRepresentation.Vertex vertex in brep.Vertices)
                {
                    using (vertex)
                    {
                        long id = vertex.SubentityPath.SubentId.IndexPtr.ToInt64();
                        vertices[id] = JsonObject(new Dictionary<string, string> {
                            { "id", Quote("v" + id.ToString(CultureInfo.InvariantCulture)) },
                            { "point", Point(vertex.Point) }
                        });
                    }
                }

                Dictionary<long, EdgeRecord> edges = new Dictionary<long, EdgeRecord>();
                foreach (Edge edge in brep.Edges)
                {
                    using (edge)
                    using (Curve3d curve = edge.Curve)
                    {
                        long id = edge.SubentityPath.SubentId.IndexPtr.ToInt64();
                        edges[id] = new EdgeRecord {
                            Id = id,
                            Vertex1 = edge.Vertex1.SubentityPath.SubentId.IndexPtr.ToInt64(),
                            Vertex2 = edge.Vertex2.SubentityPath.SubentId.IndexPtr.ToInt64(),
                            Curve = Curve(curve),
                            Faces = new SortedSet<long>()
                        };
                    }
                }

                List<string> faces = new List<string>();
                List<string> faceFingerprints = new List<string>();
                foreach (Autodesk.AutoCAD.BoundaryRepresentation.Face face in brep.Faces)
                {
                    using (face)
                    {
                        long faceId = face.SubentityPath.SubentId.IndexPtr.ToInt64();
                        List<string> loops = new List<string>();
                        List<string> loopSignatures = new List<string>();
                        SortedSet<long> faceEdges = new SortedSet<long>();
                        foreach (BoundaryLoop loop in face.Loops)
                        {
                            using (loop)
                            {
                                List<string> loopEdges = new List<string>();
                                foreach (Edge edge in loop.Edges)
                                {
                                    using (edge)
                                    {
                                        long edgeId = edge.SubentityPath.SubentId.IndexPtr.ToInt64();
                                        faceEdges.Add(edgeId);
                                        if (edges.ContainsKey(edgeId)) edges[edgeId].Faces.Add(faceId);
                                        loopEdges.Add(Quote("e" + edgeId.ToString(CultureInfo.InvariantCulture)));
                                    }
                                }
                                loops.Add(JsonObject(new Dictionary<string, string> {
                                    { "type", Quote(loop.LoopType.ToString()) },
                                    { "edges", JsonArray(loopEdges) }
                                }));
                                loopSignatures.Add(loop.LoopType.ToString() + ":" + loopEdges.Count.ToString(CultureInfo.InvariantCulture));
                            }
                        }

                        string surface;
                        using (Autodesk.AutoCAD.Geometry.Surface geometry = face.Surface)
                            surface = Surface(geometry);
                        Point3d min = face.BoundBlock.GetMinimumPoint();
                        Point3d max = face.BoundBlock.GetMaximumPoint();
                        double area = face.GetArea();
                        loopSignatures.Sort(StringComparer.Ordinal);
                        string fingerprint = Sha256(surface + "|" + Number(area) + "|" + Point(min) + "|" + Point(max) + "|" + String.Join(",", loopSignatures.ToArray()));
                        faceFingerprints.Add(fingerprint);
                        faces.Add(JsonObject(new Dictionary<string, string> {
                            { "id", Quote("f" + faceId.ToString(CultureInfo.InvariantCulture)) },
                            { "fingerprint", Quote(fingerprint) },
                            { "area", Number(area) },
                            { "bounds", JsonObject(new Dictionary<string, string> {{ "min", Point(min) }, { "max", Point(max) }}) },
                            { "surface", surface },
                            { "orientation_to_surface", Bool(face.IsOrientToSurface) },
                            { "edge_ids", JsonArray(QuotedIds(faceEdges, "e")) },
                            { "loops", JsonArray(loops) }
                        }));
                    }
                }

                List<string> edgeJson = new List<string>();
                foreach (EdgeRecord edge in edges.Values)
                {
                    string descriptor = edge.Curve + "|face-degree=" + edge.Faces.Count.ToString(CultureInfo.InvariantCulture);
                    edgeJson.Add(JsonObject(new Dictionary<string, string> {
                        { "id", Quote("e" + edge.Id.ToString(CultureInfo.InvariantCulture)) },
                        { "fingerprint", Quote(Sha256(descriptor)) },
                        { "vertex_ids", JsonArray(new List<string> { Quote("v" + edge.Vertex1), Quote("v" + edge.Vertex2) }) },
                        { "face_ids", JsonArray(QuotedIds(edge.Faces, "f")) },
                        { "curve", edge.Curve }
                    }));
                }

                Point3d boundMin = brep.BoundBlock.GetMinimumPoint();
                Point3d boundMax = brep.BoundBlock.GetMaximumPoint();
                Dictionary<string, string> values = new Dictionary<string, string> {
                    { "handle", Quote(entity.Handle.ToString()) },
                    { "type", Quote(entity.GetType().Name) },
                    { "layer", Quote(entity.Layer) },
                    { "bounds", JsonObject(new Dictionary<string, string> {{ "min", Point(boundMin) }, { "max", Point(boundMax) }}) },
                    { "vertices", JsonArray(new List<string>(vertices.Values)) },
                    { "edges", JsonArray(edgeJson) },
                    { "faces", JsonArray(faces) }
                };
                try
                {
                    MassProperties mass = brep.GetMassProperties();
                    values["mass_properties"] = JsonObject(new Dictionary<string, string> {
                        { "volume", Number(mass.Volume) },
                        { "centroid", Point(mass.Centroid) },
                        { "surface_area", Number(brep.GetSurfaceArea()) }
                    });
                }
                catch (System.Exception) { }
                faceFingerprints.Sort(StringComparer.Ordinal);
                string massProperties = values.ContainsKey("mass_properties") ? values["mass_properties"] : "";
                values["fingerprint"] = Quote(Sha256(values["type"] + values["bounds"] + massProperties + String.Join(",", faceFingerprints.ToArray())));
                return JsonObject(values);
            }
        }

        private static string Surface(Autodesk.AutoCAD.Geometry.Surface surface)
        {
            return JsonObject(SurfaceValues(surface));
        }

        private static Dictionary<string, string> SurfaceValues(Autodesk.AutoCAD.Geometry.Surface surface)
        {
            ExternalBoundedSurface bounded = surface as ExternalBoundedSurface;
            if (bounded != null && bounded.IsDefined && !bounded.IsExternalSurface)
            {
                using (Autodesk.AutoCAD.Geometry.Surface inner = bounded.BaseSurface)
                {
                    Dictionary<string, string> unwrapped = SurfaceValues(inner);
                    unwrapped["trimmed"] = "true";
                    unwrapped["contour_count"] = bounded.NumContours.ToString(CultureInfo.InvariantCulture);
                    return unwrapped;
                }
            }
            Dictionary<string, string> values = new Dictionary<string, string>();
            values["type"] = Quote(surface.GetType().Name.ToLowerInvariant());
            Plane plane = surface as Plane;
            Cylinder cylinder = surface as Cylinder;
            Cone cone = surface as Cone;
            Sphere sphere = surface as Sphere;
            Torus torus = surface as Torus;
            Autodesk.AutoCAD.Geometry.NurbSurface nurb = surface as Autodesk.AutoCAD.Geometry.NurbSurface;
            if (plane != null) {
                values["origin"] = Point(plane.PointOnPlane); values["normal"] = Vector(plane.Normal);
            } else if (cylinder != null) {
                values["origin"] = Point(cylinder.Origin); values["axis"] = Vector(cylinder.AxisOfSymmetry); values["radius"] = Number(cylinder.Radius); values["outer_normal"] = Bool(cylinder.IsOuterNormal);
            } else if (cone != null) {
                values["apex"] = Point(cone.Apex); values["axis"] = Vector(cone.AxisOfSymmetry); values["base_radius"] = Number(cone.BaseRadius); values["half_angle"] = Number(cone.HalfAngle); values["outer_normal"] = Bool(cone.IsOuterNormal);
            } else if (sphere != null) {
                values["center"] = Point(sphere.Center); values["radius"] = Number(sphere.Radius); values["outer_normal"] = Bool(sphere.IsOuterNormal);
            } else if (torus != null) {
                values["center"] = Point(torus.Center); values["axis"] = Vector(torus.AxisOfSymmetry); values["major_radius"] = Number(torus.MajorRadius); values["minor_radius"] = Number(torus.MinorRadius); values["outer_normal"] = Bool(torus.IsOuterNormal);
            } else if (nurb != null) {
                values["degree_u"] = nurb.DegreeInU.ToString(CultureInfo.InvariantCulture); values["degree_v"] = nurb.DegreeInV.ToString(CultureInfo.InvariantCulture); values["control_points_u"] = nurb.NumControlPointsInU.ToString(CultureInfo.InvariantCulture); values["control_points_v"] = nurb.NumControlPointsInV.ToString(CultureInfo.InvariantCulture);
            }
            values["normal_reversed"] = Bool(surface.IsNormalReversed);
            return values;
        }

        private static string Curve(Curve3d curve)
        {
            ExternalCurve3d external = curve as ExternalCurve3d;
            if (external != null && external.IsDefined && external.IsNativeCurve)
            {
                using (Curve3d inner = external.NativeCurve)
                    return Curve(inner);
            }
            Dictionary<string, string> values = new Dictionary<string, string>();
            values["type"] = Quote(curve.GetType().Name.ToLowerInvariant());
            values["bounds"] = JsonObject(new Dictionary<string, string> {
                { "min", Point(curve.BoundBlock.GetMinimumPoint()) },
                { "max", Point(curve.BoundBlock.GetMaximumPoint()) }
            });
            LineSegment3d line = curve as LineSegment3d;
            CircularArc3d circle = curve as CircularArc3d;
            if (line != null) {
                values["start"] = Point(line.StartPoint); values["end"] = Point(line.EndPoint); values["length"] = Number(line.Length);
            } else if (circle != null) {
                values["center"] = Point(circle.Center); values["normal"] = Vector(circle.Normal); values["radius"] = Number(circle.Radius); values["start_angle"] = Number(circle.StartAngle); values["end_angle"] = Number(circle.EndAngle);
            }
            return JsonObject(values);
        }

        private static string Point(Point3d value) { return "[" + Number(value.X) + "," + Number(value.Y) + "," + Number(value.Z) + "]"; }
        private static string Vector(Vector3d value) { return "[" + Number(value.X) + "," + Number(value.Y) + "," + Number(value.Z) + "]"; }
        private static string Number(double value) { return value.ToString("R", CultureInfo.InvariantCulture); }
        private static string Bool(bool value) { return value ? "true" : "false"; }
        private static List<string> QuotedIds(IEnumerable<long> ids, string prefix) { List<string> result = new List<string>(); foreach (long id in ids) result.Add(Quote(prefix + id.ToString(CultureInfo.InvariantCulture))); return result; }
        private static string JoinIds(IEnumerable<long> ids, string prefix) { return String.Join(",", QuotedIds(ids, prefix).ToArray()); }
        private static string JsonArray(IEnumerable<string> values) { return "[" + String.Join(",", new List<string>(values).ToArray()) + "]"; }
        private static string JsonObject(IDictionary<string, string> values) { List<string> keys = new List<string>(values.Keys); keys.Sort(StringComparer.Ordinal); List<string> fields = new List<string>(); foreach (string key in keys) fields.Add(Quote(key) + ":" + values[key]); return "{" + String.Join(",", fields.ToArray()) + "}"; }
        private static string Quote(string value) { if (value == null) return "null"; StringBuilder result = new StringBuilder("\""); foreach (char character in value) { switch (character) { case '\\': result.Append("\\\\"); break; case '"': result.Append("\\\""); break; case '\b': result.Append("\\b"); break; case '\f': result.Append("\\f"); break; case '\n': result.Append("\\n"); break; case '\r': result.Append("\\r"); break; case '\t': result.Append("\\t"); break; default: if (character < 32) result.Append("\\u" + ((int)character).ToString("x4", CultureInfo.InvariantCulture)); else result.Append(character); break; } } result.Append('"'); return result.ToString(); }
        private static string Sha256(string value) { using (SHA256 hash = SHA256.Create()) { byte[] bytes = hash.ComputeHash(Encoding.UTF8.GetBytes(value)); StringBuilder result = new StringBuilder(); foreach (byte item in bytes) result.Append(item.ToString("x2", CultureInfo.InvariantCulture)); return result.ToString(); } }

        private sealed class EdgeRecord
        {
            public long Id; public long Vertex1; public long Vertex2; public string Curve; public SortedSet<long> Faces;
        }
        private sealed class QueryFace { public Brep Brep; public Autodesk.AutoCAD.BoundaryRepresentation.Face Face; public string EntityHandle; public long FaceId; public Point3d Minimum; public Point3d Maximum; }
        private sealed class QueryHit { public QueryFace Face; public double Distance; public string Method; }
    }
}
