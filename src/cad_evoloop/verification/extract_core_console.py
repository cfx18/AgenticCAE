"""Extract verifier scene data through AutoCAD Core Console, without desktop COM."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import subprocess
import tempfile
from typing import Any


CORE_CONSOLE = Path(r"E:\AutoCAD\AutoCAD 2024\accoreconsole.exe")
TYPE_NAMES = {
    "LINE": "AcDbLine",
    "CIRCLE": "AcDbCircle",
    "ARC": "AcDbArc",
    "LWPOLYLINE": "AcDbPolyline",
    "POLYLINE": "AcDb2dPolyline",
    "TEXT": "AcDbText",
    "MTEXT": "AcDbMText",
    "DIMENSION": "AcDbDimension",
    "HATCH": "AcDbHatch",
    "SOLID": "AcDbSolid",
    "3DSOLID": "AcDb3dSolid",
    "REGION": "AcDbRegion",
    "INSERT": "AcDbBlockReference",
    "ELLIPSE": "AcDbEllipse",
    "SPLINE": "AcDbSpline",
    "VIEWPORT": "AcDbViewport",
    "LEADER": "AcDbLeader",
    "MULTILEADER": "AcDbMLeader",
    "ACAD_TABLE": "AcDbTable",
}


def decode_console_output(value: bytes) -> str:
    if not value:
        return ""
    if value.count(b"\x00") > len(value) // 4:
        return value.decode("utf-16-le", errors="replace")
    return value.decode("utf-8", errors="replace")


def lisp_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace('"', '\\"')


def extractor_lisp(output: Path) -> str:
    return f'''(vl-load-com)
(setq mcp-f (open "{lisp_path(output)}" "w"))
(defun mcp-n (x) (rtos x 2 8))
(defun mcp-p (p) (strcat (mcp-n (car p)) "," (mcp-n (cadr p)) "," (mcp-n (if (caddr p) (caddr p) 0.0))))
(defun mcp-bbox-inner (e / obj minp maxp)
  (setq obj (vlax-ename->vla-object e))
  (vla-getboundingbox obj 'minp 'maxp)
  (strcat (mcp-p (vlax-safearray->list minp)) "\t" (mcp-p (vlax-safearray->list maxp))))
(defun mcp-bbox (e / result)
  (setq result (vl-catch-all-apply 'mcp-bbox-inner (list e)))
  (if (vl-catch-all-error-p result)
    "\t"
    result))
(write-line (strcat "INSUNITS\t" (itoa (getvar "INSUNITS"))) mcp-f)
(write-line "LAYOUT\tModel\t1" mcp-f)
(setq mcp-r (tblnext "LAYER" T))
(while mcp-r
  (write-line (strcat "LAYER\t" (cdr (assoc 2 mcp-r)) "\t" (cdr (assoc 6 mcp-r))) mcp-f)
  (setq mcp-r (tblnext "LAYER")))
(setq mcp-r (tblnext "DIMSTYLE" T))
(while mcp-r
  (write-line (strcat "DIMSTYLE\t" (cdr (assoc 2 mcp-r))) mcp-f)
  (setq mcp-r (tblnext "DIMSTYLE")))
(setq mcp-ss (ssget "_X"))
(if mcp-ss
  (progn
    (setq mcp-i 0)
    (repeat (sslength mcp-ss)
      (setq mcp-e (ssname mcp-ss mcp-i) mcp-d (entget mcp-e)
            mcp-t (cdr (assoc 0 mcp-d)) mcp-extra ""
            mcp-owner (cdr (assoc 410 mcp-d)))
      (if (not mcp-owner) (setq mcp-owner "Model"))
      (cond
        ((= mcp-t "LINE") (setq mcp-extra (strcat (mcp-p (cdr (assoc 10 mcp-d))) "\t" (mcp-p (cdr (assoc 11 mcp-d))))))
        ((= mcp-t "CIRCLE") (setq mcp-extra (strcat (mcp-p (cdr (assoc 10 mcp-d))) "\t" (mcp-n (cdr (assoc 40 mcp-d))))))
        ((= mcp-t "ARC") (setq mcp-extra (strcat (mcp-p (cdr (assoc 10 mcp-d))) "\t" (mcp-n (cdr (assoc 40 mcp-d))) "\t" (mcp-n (cdr (assoc 50 mcp-d))) "\t" (mcp-n (cdr (assoc 51 mcp-d))))))
        ((= mcp-t "TEXT") (setq mcp-extra (strcat (mcp-p (cdr (assoc 10 mcp-d))) "\t" (mcp-n (cdr (assoc 40 mcp-d))) "\t" (cdr (assoc 1 mcp-d)))))
        ((= mcp-t "MTEXT") (setq mcp-extra (strcat (mcp-p (cdr (assoc 10 mcp-d))) "\t0\t" (cdr (assoc 1 mcp-d)))))
        ((= mcp-t "DIMENSION")
          ;; DXF group 42 is the actual measurement and works without desktop ActiveX.
          (setq mcp-v (cdr (assoc 42 mcp-d)))
          (if (numberp mcp-v)
            (setq mcp-extra (strcat (mcp-n mcp-v) "\t" (cdr (assoc 3 mcp-d)) "\t" (itoa (cdr (assoc 70 mcp-d))))))))
      (write-line (strcat "ENT2\t" mcp-t "\t" (cdr (assoc 8 mcp-d)) "\t" (cdr (assoc 5 mcp-d)) "\t" mcp-owner "\t" (mcp-bbox mcp-e) "\t" mcp-extra) mcp-f)
      (setq mcp-i (1+ mcp-i)))))
(write-line "DONE" mcp-f)
(close mcp-f)
(princ)
'''


def point(value: str) -> list[float]:
    return [float(item) for item in value.split(",")]


def parse_scene(lines: list[str], candidate: Path) -> dict[str, Any]:
    insunits = 0
    layers = []
    dimstyles = []
    layout_definitions: dict[str, bool] = {}
    entities = []
    for raw in lines:
        fields = raw.rstrip("\r\n").split("\t")
        if fields[0] == "INSUNITS":
            insunits = int(fields[1])
        elif fields[0] == "LAYER":
            layer = {"Name": fields[1]}
            if len(fields) >= 3 and fields[2]:
                layer["Linetype"] = fields[2]
            layers.append(layer)
        elif fields[0] == "DIMSTYLE":
            dimstyles.append({"Name": fields[1]})
        elif fields[0] == "LAYOUT" and len(fields) >= 3:
            layout_definitions[fields[1]] = fields[2] == "1"
        elif fields[0] in {"ENT", "ENT2"} and len(fields) >= 4:
            dxf_type, layer, handle = fields[1:4]
            if fields[0] == "ENT2" and len(fields) >= 7:
                owner = fields[4] or "Model"
                bbox_min, bbox_max = fields[5:7]
                extra = fields[7:]
            else:
                owner = "Model"
                bbox_min = bbox_max = ""
                extra = fields[4:]
            entity: dict[str, Any] = {
                "type": TYPE_NAMES.get(dxf_type, f"AcDb{dxf_type.title()}"),
                "owner": owner,
                "Layer": layer,
                "Handle": handle,
            }
            if bbox_min and bbox_max:
                entity["bbox"] = {"min": point(bbox_min), "max": point(bbox_max)}
            if dxf_type == "LINE" and len(extra) >= 2:
                start, end = point(extra[0]), point(extra[1])
                entity.update(StartPoint=start, EndPoint=end, bbox={
                    "min": [min(a, b) for a, b in zip(start, end)],
                    "max": [max(a, b) for a, b in zip(start, end)],
                })
            elif dxf_type in {"CIRCLE", "ARC"} and len(extra) >= 2:
                center, radius = point(extra[0]), float(extra[1])
                entity.update(Center=center, Radius=radius, bbox={
                    "min": [center[0] - radius, center[1] - radius, center[2]],
                    "max": [center[0] + radius, center[1] + radius, center[2]],
                })
                if dxf_type == "ARC" and len(extra) >= 4:
                    entity.update(StartAngle=float(extra[2]), EndAngle=float(extra[3]))
            elif dxf_type in {"TEXT", "MTEXT"} and len(extra) >= 3:
                entity.update(InsertionPoint=point(extra[0]), Height=float(extra[1]), TextString="\t".join(extra[2:]))
            elif dxf_type == "DIMENSION" and extra and extra[0]:
                entity["Measurement"] = float(extra[0])
                if len(extra) >= 2 and extra[1]:
                    entity["DimStyle"] = extra[1]
                if len(extra) >= 3 and extra[2]:
                    entity["DimensionType"] = int(extra[2])
            entities.append(entity)

    boxes = [entity["bbox"] for entity in entities if "bbox" in entity]
    bounds = None if not boxes else {
        "min": [min(box["min"][axis] for box in boxes) for axis in range(3)],
        "max": [max(box["max"][axis] for box in boxes) for axis in range(3)],
    }
    counts = Counter(entity["type"] for entity in entities)
    layout_counts = Counter(entity["owner"] for entity in entities)
    for owner in layout_counts:
        layout_definitions.setdefault(owner, owner.casefold() == "model")
    if not layout_definitions:
        layout_definitions["Model"] = True
    return {
        "document": candidate.name,
        "full_name": str(candidate),
        "insunits": insunits,
        "active_command": "",
        "layers": layers,
        "dimstyles": dimstyles,
        "layouts": [
            {"name": name, "model_type": model_type, "entity_count": layout_counts.get(name, 0)}
            for name, model_type in layout_definitions.items()
        ],
        "entities": entities,
        "summary": {
            "entity_count": len(entities),
            "type_counts": dict(sorted(counts.items())),
            "extraction_errors": 0,
            "bounds": bounds,
        },
        "extraction_backend": "core_console",
    }


def extract_dwg_core(path: str | Path, timeout: int = 120) -> dict[str, Any]:
    candidate = Path(path).resolve()
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    with tempfile.TemporaryDirectory(prefix="cad-core-extract-", dir=candidate.parent) as temp:
        job_dir = Path(temp)
        output = job_dir / "scene.tsv"
        payload = job_dir / "extract.lsp"
        script = job_dir / "extract.scr"
        payload.write_text(extractor_lisp(output), encoding="utf-8", newline="\n")
        script.write_text(
            f'(setvar "SECURELOAD" 0)\n(load "{lisp_path(payload)}")\n_.QUIT\n_N\n',
            encoding="utf-8",
            newline="\n",
        )
        completed = subprocess.run(
            [str(CORE_CONSOLE), "/i", str(candidate), "/s", str(script)],
            # AutoCAD may briefly leave a helper process inheriting its cwd on Windows.
            # Keep that cwd outside the disposable directory so cleanup cannot recurse
            # on a directory that is still held open.
            cwd=candidate.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0 or not output.is_file():
            diagnostic = "\n".join(filter(None, (
                decode_console_output(completed.stdout),
                decode_console_output(completed.stderr),
            )))[-4000:]
            raise RuntimeError(
                f"Core Console extraction failed with code {completed.returncode}: {diagnostic}"
            )
        lines = output.read_text(encoding="utf-8", errors="replace").splitlines()
        if "DONE" not in lines:
            diagnostic = decode_console_output(completed.stdout)[-4000:]
            raise RuntimeError(f"Core Console extraction stopped before sentinel: {diagnostic}")
        return parse_scene(lines, candidate)
