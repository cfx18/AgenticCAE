"""Extract a normalized, JSON-serializable scene from an AutoCAD DWG."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable


RETRY_HRESULTS = {-2147418111, -2147417846}


def _com_modules() -> tuple[Any, Any, Any]:
    import pythoncom
    import pywintypes
    import win32com.client

    return pythoncom, pywintypes, win32com.client


def com_call(fn: Callable[[], Any], attempts: int = 30, delay: float = 0.25) -> Any:
    _, pywintypes, _ = _com_modules()
    for attempt in range(attempts):
        try:
            return fn()
        except pywintypes.com_error as exc:
            if exc.hresult in RETRY_HRESULTS and attempt < attempts - 1:
                time.sleep(delay)
                continue
            raise


def json_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    try:
        return float(value)
    except (TypeError, ValueError):
        return str(value)


def read_property(entity: Any, name: str) -> Any:
    try:
        return json_value(com_call(lambda: getattr(entity, name)))
    except Exception:
        return None


def bounding_box(entity: Any) -> dict[str, list[float]] | None:
    pythoncom, _, win32com_client = _com_modules()
    minimum = win32com_client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None)
    maximum = win32com_client.VARIANT(pythoncom.VT_BYREF | pythoncom.VT_VARIANT, None)
    try:
        com_call(lambda: entity.GetBoundingBox(minimum, maximum))
        return {
            "min": [float(value) for value in minimum.value],
            "max": [float(value) for value in maximum.value],
        }
    except Exception:
        return None


COMMON_PROPERTIES = ("Handle", "Layer", "Color", "Linetype", "Visible")
TYPE_PROPERTIES: dict[str, tuple[str, ...]] = {
    "AcDbLine": ("StartPoint", "EndPoint", "Length", "Angle"),
    "AcDbCircle": ("Center", "Radius", "Circumference", "Area"),
    "AcDbArc": ("Center", "Radius", "StartAngle", "EndAngle", "ArcLength", "Area"),
    "AcDbPolyline": ("Coordinates", "Length", "Area", "Closed", "ConstantWidth"),
    "AcDb2dPolyline": ("Coordinates", "Length", "Area", "Closed", "ConstantWidth"),
    "AcDb3dPolyline": ("Coordinates", "Length", "Closed"),
    "AcDbText": ("TextString", "InsertionPoint", "Height", "Rotation"),
    "AcDbMText": ("TextString", "InsertionPoint", "Height", "Rotation", "Width"),
    "AcDbHatch": ("PatternName", "PatternScale", "PatternAngle", "Area"),
    "AcDbBlockReference": (
        "Name", "EffectiveName", "InsertionPoint", "Rotation",
        "XScaleFactor", "YScaleFactor", "ZScaleFactor",
    ),
    "AcDb3dSolid": ("Volume", "Centroid", "PrincipalDirections"),
    "AcDbRegion": ("Area", "Centroid", "Perimeter"),
}


def is_dimension(object_name: str) -> bool:
    return "Dimension" in object_name or object_name.startswith("AcDbDim")


def extract_entity(entity: Any, owner: str) -> dict[str, Any]:
    object_name = str(com_call(lambda: entity.ObjectName))
    record: dict[str, Any] = {"type": object_name, "owner": owner}
    for name in COMMON_PROPERTIES + TYPE_PROPERTIES.get(object_name, ()):
        value = read_property(entity, name)
        if value is not None:
            record[name] = value
    if is_dimension(object_name):
        for name in ("Measurement", "TextOverride", "StyleName", "TextPosition"):
            value = read_property(entity, name)
            if value is not None:
                record[name] = value
    box = bounding_box(entity)
    if box:
        record["bbox"] = box
    return record


def collection_records(collection: Any, owner: str) -> list[dict[str, Any]]:
    _, _, win32com_client = _com_modules()
    records = []
    count = int(com_call(lambda: collection.Count))
    for index in range(count):
        try:
            entity = com_call(lambda index=index: collection.Item(index))
            entity = win32com_client.dynamic.DumbDispatch(entity._oleobj_)
            records.append(extract_entity(entity, owner))
        except Exception as exc:
            records.append({"type": "ExtractionError", "owner": owner, "index": index, "error": str(exc)})
    return records


def named_collection(collection: Any, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    result = []
    count = int(com_call(lambda: collection.Count))
    for index in range(count):
        item = com_call(lambda index=index: collection.Item(index))
        record = {}
        for field in fields:
            value = read_property(item, field)
            if value is not None:
                record[field] = value
        result.append(record)
    return result


def scene_bounds(entities: list[dict[str, Any]]) -> dict[str, list[float]] | None:
    boxes = [entity["bbox"] for entity in entities if "bbox" in entity]
    if not boxes:
        return None
    return {
        "min": [min(box["min"][axis] for box in boxes) for axis in range(3)],
        "max": [max(box["max"][axis] for box in boxes) for axis in range(3)],
    }


def extract_document(doc: Any) -> dict[str, Any]:
    model_space = com_call(lambda: doc.ModelSpace)
    entities = collection_records(model_space, "Model")
    layouts = []
    layout_collection = com_call(lambda: doc.Layouts)
    for index in range(int(com_call(lambda: layout_collection.Count))):
        layout = com_call(lambda index=index: layout_collection.Item(index))
        name = str(read_property(layout, "Name") or f"Layout{index}")
        model_type = bool(read_property(layout, "ModelType"))
        block = com_call(lambda: layout.Block)
        if not model_type:
            entities.extend(collection_records(block, name))
        layouts.append({
            "name": name,
            "model_type": model_type,
            "tab_order": read_property(layout, "TabOrder"),
            "entity_count": int(com_call(lambda: block.Count)),
        })

    type_counts = Counter(entity["type"] for entity in entities)
    extraction_errors = [entity for entity in entities if entity["type"] == "ExtractionError"]
    return {
        "document": str(com_call(lambda: doc.Name)),
        "full_name": str(read_property(doc, "FullName") or ""),
        "insunits": json_value(com_call(lambda: doc.GetVariable("INSUNITS"))),
        "active_command": str(com_call(lambda: doc.GetVariable("CMDNAMES"))),
        "layers": named_collection(com_call(lambda: doc.Layers), ("Name", "LayerOn", "Freeze", "Lock", "Color", "Linetype")),
        "dimstyles": named_collection(com_call(lambda: doc.DimStyles), ("Name",)),
        "layouts": layouts,
        "entities": entities,
        "summary": {
            "entity_count": len(entities) - len(extraction_errors),
            "type_counts": dict(sorted(type_counts.items())),
            "extraction_errors": len(extraction_errors),
            "bounds": scene_bounds(entities),
        },
    }


def extract_dwg(path: str | Path, start_autocad: bool = False) -> dict[str, Any]:
    pythoncom, _, win32com_client = _com_modules()
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(resolved)

    pythoncom.CoInitialize()
    opened = None
    try:
        try:
            app = com_call(lambda: win32com_client.GetActiveObject("AutoCAD.Application"))
        except Exception:
            if not start_autocad:
                raise RuntimeError("AutoCAD is not running; start it or pass --start-autocad")
            app = win32com_client.Dispatch("AutoCAD.Application")
            app.Visible = True
        opened = com_call(lambda: app.Documents.Open(str(resolved), True))
        return extract_document(opened)
    finally:
        if opened is not None:
            try:
                com_call(lambda: opened.Close(False))
            except Exception:
                pass
        pythoncom.CoUninitialize()
