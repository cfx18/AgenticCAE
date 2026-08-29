"""Render an extracted AutoCAD scene to a neutral PNG for visual evaluation."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


DIMENSION_TOKEN = "Dimension"


def entity_points(entity: dict[str, Any]) -> list[tuple[float, float]]:
    kind = entity.get("type", "")
    if kind == "AcDbLine":
        return [tuple(entity["StartPoint"][:2]), tuple(entity["EndPoint"][:2])]
    if kind in {"AcDbPolyline", "AcDb2dPolyline"}:
        coordinates = entity.get("Coordinates", [])
        return [(float(coordinates[index]), float(coordinates[index + 1])) for index in range(0, len(coordinates), 2)]
    if kind == "AcDbArc":
        center = entity.get("Center", [0, 0])
        radius = float(entity.get("Radius", 0))
        start = float(entity.get("StartAngle", 0))
        end = float(entity.get("EndAngle", 0))
        if end < start:
            end += 2 * math.pi
        steps = max(8, int(abs(end - start) * 32))
        return [
            (
                float(center[0]) + radius * math.cos(start + (end - start) * index / steps),
                float(center[1]) + radius * math.sin(start + (end - start) * index / steps),
            )
            for index in range(steps + 1)
        ]
    return []


def render_scene(scene: dict[str, Any], output: Path, width: int = 1600, height: int = 1200) -> None:
    entities = [
        entity for entity in scene.get("entities", [])
        if entity.get("owner") == "Model" and entity.get("Visible", True)
    ]
    geometry_points = [
        point
        for entity in entities
        if DIMENSION_TOKEN not in entity.get("type", "") and entity.get("type") != "AcDbText"
        for point in entity_points(entity)
    ]
    if not geometry_points:
        raise ValueError("Scene contains no renderable model-space geometry")
    min_x = min(point[0] for point in geometry_points)
    max_x = max(point[0] for point in geometry_points)
    min_y = min(point[1] for point in geometry_points)
    max_y = max(point[1] for point in geometry_points)
    margin = 80
    scale = min((width - 2 * margin) / max(max_x - min_x, 1), (height - 2 * margin) / max(max_y - min_y, 1))

    def transform(point: tuple[float, float]) -> tuple[int, int]:
        x = margin + (point[0] - min_x) * scale
        y = height - margin - (point[1] - min_y) * scale
        return round(x), round(y)

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=18)
    small_font = ImageFont.load_default(size=15)
    for entity in entities:
        kind = entity.get("type", "")
        points = entity_points(entity)
        if points:
            pixels = [transform(point) for point in points]
            if kind in {"AcDbPolyline", "AcDb2dPolyline"} and entity.get("Closed") and len(pixels) > 2:
                pixels.append(pixels[0])
            cad_width = float(entity.get("ConstantWidth", 0) or 0)
            line_width = max(3, round(cad_width * scale)) if cad_width else 3
            draw.line(pixels, fill=(15, 23, 42), width=line_width, joint="curve")
        elif kind == "AcDbText" and entity.get("InsertionPoint"):
            position = transform(tuple(entity["InsertionPoint"][:2]))
            draw.text(position, str(entity.get("TextString", "")), fill=(55, 65, 81), font=font, anchor="ls")
        elif DIMENSION_TOKEN in kind and entity.get("TextPosition"):
            position = transform(tuple(entity["TextPosition"][:2]))
            measurement = entity.get("Measurement")
            label = f"{measurement:.3g}" if isinstance(measurement, (int, float)) else "DIM"
            draw.text(position, label, fill=(90, 100, 115), font=small_font, anchor="mm")
    image.save(output, format="PNG")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=1200)
    args = parser.parse_args()
    scene = json.loads(Path(args.scene).read_text(encoding="utf-8"))
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    render_scene(scene, output, args.width, args.height)
    print(output)


if __name__ == "__main__":
    main()
