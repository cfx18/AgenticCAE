"""OCCT-based drawing evidence and fixed-frame BRep checks for task acceptance."""

from __future__ import annotations

import math
from pathlib import Path

import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepLib import BRepLib
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from PIL import Image, ImageDraw, ImageFont


VIEWS = {
    "front": ((0, -1, 0), (1, 0, 0), ("X", "Z")),
    "top": ((0, 0, 1), (1, 0, 0), ("X", "Y")),
    "right": ((1, 0, 0), (0, 1, 0), ("Y", "Z")),
}


def font(size: int):
    for path in ("C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def load_shape(path: Path):
    shape = cq.importers.importStep(str(path)).val()
    if not shape.isValid() or len(shape.Solids()) != 1 or shape.Volume() <= 0:
        raise ValueError("Pilot requires one valid, positive-volume solid")
    return shape


def normalized(shape):
    box = shape.BoundingBox()
    offset = (-box.xmin, -box.ymin, -box.zmin)
    return shape.translate(offset), offset


def extents(shape) -> list[float]:
    box = shape.BoundingBox()
    return [box.xlen, box.ylen, box.zlen]


def cylinders(shape) -> list[dict]:
    result = []
    for index, face in enumerate(shape.Faces()):
        if face.geomType() != "CYLINDER":
            continue
        surface = BRepAdaptor_Surface(face.wrapped)
        cylinder = surface.Cylinder()
        axis = cylinder.Axis()
        u = (surface.FirstUParameter() + surface.LastUParameter()) / 2
        v = (surface.FirstVParameter() + surface.LastVParameter()) / 2
        point = cq.Vector(surface.Value(u, v))
        direction = cq.Vector(axis.Direction())
        delta = point - cq.Vector(axis.Location())
        radial = delta - direction * delta.dot(direction)
        normal_dot_radial = face.normalAt(point).dot(radial)
        result.append({"face_index": index, "radius_mm": cylinder.Radius(),
                       "axis": list(axis.Direction().Coord()), "origin_mm": list(axis.Location().Coord()),
                       "v_min": surface.FirstVParameter(), "v_max": surface.LastVParameter(),
                       "angular_span": surface.LastUParameter() - surface.FirstUParameter(),
                       "radial_normal_dot": normal_dot_radial, "internal": normal_dot_radial < 0})
    return result


def projected_edges(shape, view: str) -> list[dict]:
    normal, horizontal, _ = VIEWS[view]
    algorithm = HLRBRep_Algo()
    algorithm.Add(shape.wrapped)
    algorithm.Projector(HLRAlgo_Projector(gp_Ax2(gp_Pnt(), gp_Dir(*normal), gp_Dir(*horizontal))))
    algorithm.Update()
    algorithm.Hide()
    result = HLRBRep_HLRToShape(algorithm)
    edges = []
    groups = [
        ("hidden_edge", result.HCompound()), ("hidden_edge", result.OutLineHCompound()),
        ("visible_edge", result.VCompound()), ("visible_edge", result.Rg1LineVCompound()),
        ("visible_edge", result.OutLineVCompound()),
    ]
    for role, compound in groups:
        if compound.IsNull():
            continue
        BRepLib.BuildCurves3d_s(compound, 1e-7)
        for edge in cq.Shape(compound).Edges():
            points = edge.sample(2 if edge.geomType() == "LINE" else 160)[0]
            coordinates = [[point.x, point.y] for point in points]
            if coordinates:
                edges.append({"role": role, "points": coordinates,
                              "length_mm": edge.Length(), "lineage": "OCCT-HLR-projection; not original BRep edge identity"})
    if not edges:
        raise ValueError("Empty HLR projection")
    return edges


def dashed(draw, points, *, fill="#434343", width=2, pattern=(9, 6)):
    remaining, phase = pattern[0], 0
    for first, last in zip(points, points[1:]):
        dx, dy = last[0] - first[0], last[1] - first[1]
        length = math.hypot(dx, dy)
        if length < 1e-8:
            continue
        distance = 0.0
        while distance < length:
            end = min(length, distance + remaining)
            if phase % 2 == 0:
                draw.line([(first[0] + dx * distance / length, first[1] + dy * distance / length),
                           (first[0] + dx * end / length, first[1] + dy * end / length)], fill=fill, width=width)
            remaining -= end - distance
            distance = end
            if remaining < 1e-7:
                phase = (phase + 1) % len(pattern)
                remaining = pattern[phase]


def draw_view(shape, output: Path, *, view="front", dimensions=True, hidden=True,
              hidden_as_solid=False, marker_role: str | None = None, title: str | None = None) -> dict:
    edges = projected_edges(shape, view)
    points = [point for edge in edges for point in edge["points"]]
    xmin, xmax = min(p[0] for p in points), max(p[0] for p in points)
    ymin, ymax = min(p[1] for p in points), max(p[1] for p in points)
    scale = min(390 / max(xmax - xmin, 1e-7), 330 / max(ymax - ymin, 1e-7))
    left = (600 - (xmax - xmin) * scale) / 2
    bottom = 425
    transform = lambda p: (left + (p[0] - xmin) * scale, bottom - (p[1] - ymin) * scale)
    image = Image.new("RGB", (600, 590), "white")
    draw = ImageDraw.Draw(image)
    draw.text((24, 16), title or (view.title() + " view"), fill="#18212b", font=font(24))
    horizontal, vertical = VIEWS[view][2]
    draw.text((24, 50), f"Horizontal: {horizontal}   Vertical: {vertical}   Units: mm", fill="#484848", font=font(16))
    primitives = []
    for index, edge in enumerate(edges):
        if edge["role"] == "hidden_edge" and not hidden:
            continue
        pixels = [transform(point) for point in edge["points"]]
        if edge["role"] == "hidden_edge" and not hidden_as_solid:
            dashed(draw, pixels)
        else:
            draw.line(pixels, fill="#151515", width=3)
        primitives.append({**edge, "id": f"p{index:03d}", "pixels": pixels})
    x0, y0 = transform((xmin, ymin))
    x1, y1 = transform((xmax, ymax))
    if dimensions:
        # These are explicit bounding dimensions, not inferred feature dimensions.
        dimension_y = 474
        for x in (x0, x1):
            pixels = [(x, y0 + 8), (x, dimension_y + 12)]
            draw.line(pixels, fill="#353535", width=1)
            primitives.append({"role": "extension_line", "pixels": pixels, "anchors": [horizontal + "_min", horizontal + "_max"]})
        draw.line([(x0, dimension_y), (x1, dimension_y)], fill="#353535", width=1)
        for x, direction in ((x0, 1), (x1, -1)):
            draw.polygon([(x, dimension_y), (x + direction * 11, dimension_y - 4), (x + direction * 11, dimension_y + 4)], fill="#353535")
        draw.text(((x0+x1)/2, dimension_y - 9), f"{xmax-xmin:.3f}", anchor="ms", font=font(20), fill="#111111", stroke_width=3, stroke_fill="white")
        primitives.append({"role": "dimension_line", "pixels": [(x0, dimension_y), (x1, dimension_y)],
                           "value_mm": xmax-xmin, "axis": horizontal, "anchors": [horizontal + "_min", horizontal + "_max"]})
        draw.text((30, 530), f"Vertical extent: {ymax-ymin:.3f} mm", fill="#111111", font=font(20))
    marked = None
    if marker_role:
        eligible = [p for p in primitives if p["role"] == marker_role]
        if not eligible:
            raise ValueError(f"No {marker_role} in {view}")
        if marker_role == "hidden_edge":
            # Reject hidden strokes coincident with visible strokes at the probe location.
            def clearance(primitive):
                point = primitive["pixels"][len(primitive["pixels"]) // 2] if len(primitive["pixels"]) > 2 else tuple(sum(v)/2 for v in zip(*primitive["pixels"]))
                distances = []
                for visible in primitives:
                    if visible["role"] != "visible_edge":
                        continue
                    for a, b in zip(visible["pixels"], visible["pixels"][1:]):
                        vx, vy = b[0]-a[0], b[1]-a[1]
                        t = max(0, min(1, ((point[0]-a[0])*vx+(point[1]-a[1])*vy)/max(vx*vx+vy*vy, 1e-12)))
                        distances.append(math.hypot(point[0]-a[0]-t*vx, point[1]-a[1]-t*vy))
                return min(distances, default=999)
            eligible = [p for p in eligible if clearance(p) > 10]
            if not eligible:
                raise ValueError("Hidden stroke overlaps visible geometry at probe")
        marked = max(eligible, key=lambda p: p.get("length_mm", math.dist(p["pixels"][0], p["pixels"][-1])))
        pixels = marked["pixels"]
        point = pixels[len(pixels)//2] if len(pixels) > 2 else tuple(sum(v)/2 for v in zip(*pixels))
        if marker_role == "dimension_line":
            point = (pixels[0][0]*.75 + pixels[-1][0]*.25, pixels[0][1])
        x, y = point
        draw.ellipse((x-13, y-13, x+13, y+13), outline="#b22626", width=2)
        label_x = x-36 if marker_role in {"extension_line", "dimension_line"} else x+18
        draw.text((label_x, y-22), "A", font=font(24), fill="#b22626")
        marked = {**marked, "marker_center_px": [x, y]}
    image.save(output)
    return {"view": view, "projection_normal": VIEWS[view][0], "horizontal_axis": VIEWS[view][1],
            "units": "mm", "pixel_scale": scale, "primitives": primitives, "marked": marked}


def shape_verdict(candidate, target, *, volume_tolerance: float = 1e-3, length_tolerance: float = 1e-4) -> dict:
    if not candidate.isValid() or len(candidate.Solids()) != 1:
        return {"passed": False, "checks": {"valid_single_solid": False}, "score": 0.0}
    missing = target.cut(candidate).Volume()
    extra = candidate.cut(target).Volume()
    a, b = candidate.BoundingBox(), target.BoundingBox()
    if missing > target.Volume()*.99 and extra > candidate.Volume()*.99:
        # Imported periodic-face representations can produce contradictory booleans.
        # A shared strictly-interior point disproves an alleged empty intersection.
        for ix in range(1, 6):
            for iy in range(1, 6):
                for iz in range(1, 6):
                    point = (b.xmin+b.xlen*ix/6, b.ymin+b.ylen*iy/6, b.zmin+b.zlen*iz/6)
                    if target.isInside(point, tolerance=1e-6) and candidate.isInside(point, tolerance=1e-6):
                        raise RuntimeError("Boolean kernel contradicts point-classification overlap; verdict is inconclusive")
    bound_error = max(abs(getattr(a, name)-getattr(b, name)) for name in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"))
    checks = {"valid_single_solid": True, "missing_volume": abs(missing) <= volume_tolerance,
              "extra_volume": abs(extra) <= volume_tolerance, "fixed_frame_bounds": bound_error <= length_tolerance}
    return {"passed": all(checks.values()), "checks": checks,
            "metrics": {"missing_mm3": missing, "extra_mm3": extra, "max_bound_error_mm": bound_error},
            "score": float(all(checks.values())), "alignment": "none; fixed millimetre frame",
            "tolerances": {"volume_mm3": volume_tolerance, "length_mm": length_tolerance}}
