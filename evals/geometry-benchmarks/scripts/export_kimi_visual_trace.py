"""Export exact ReadMediaFile returns, without exposing private reasoning blocks."""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re

from PIL import Image


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_blocks(content):
    if isinstance(content, str):
        try:
            value = json.loads(content)
            if isinstance(value, list):
                return value
        except json.JSONDecodeError:
            pass
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def observation_claims(messages):
    claims = []
    for message in messages:
        for sentence in re.split(r"(?<=[.!?])\s+", message["text"]):
            # Next-action announcements are not discoveries.
            if re.match(r"^(?:(?:Now|First|Next|Then)[,:]?\s+)?(?:Let me|I['\u2019]ll|I will|We will|I'm going to)\b", sentence, re.IGNORECASE):
                continue
            if sentence.strip():
                claims.append({"line": message["line"], "text": sentence.strip(),
                               "status": "public_statement_not_independently_verified"})
    return claims


def image_record(url: str, assets: dict) -> dict | None:
    match = re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,(.*)", url, re.DOTALL)
    if not match:
        return None
    data = base64.b64decode(match[2], validate=True)
    sha = digest(data)
    with Image.open(BytesIO(data)) as image:
        width, height = image.size
        pixel_sha = digest(f"{width},{height}:".encode() + image.convert("RGBA").tobytes())
    assets.setdefault(sha, {"data_url": url, "sha256": sha, "bytes": len(data),
                           "width": width, "height": height, "pixel_sha256": pixel_sha})
    return {key: value for key, value in assets[sha].items() if key != "data_url"}


def extract(events: list[tuple[int, dict]], assets: dict) -> tuple[list, list, dict]:
    calls, operations, counts, by_id = [], [], Counter(), {}
    operations_by_id = {}
    public_messages = []
    for line, event in events:
        if event.get("role") == "assistant":
            for block in content_blocks(event.get("content")):
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").strip():
                    public_messages.append({"line": line, "text": block["text"]})
            for call in event.get("tool_calls") or []:
                function = call.get("function") or {}
                name = function.get("name", "unknown")
                args = function.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                counts[name] += 1
                if name == "ReadMediaFile":
                    row = {"number": len(calls) + 1, "line": line, "call_id": call.get("id"),
                           "arguments": args, "images": [], "response_text": [],
                           "status": "pending", "previous_operations": [op["number"] for op in operations[-2:]]}
                    calls.append(row)
                    by_id[call.get("id")] = row
                else:
                    # Public action arguments only. Never export assistant think/reasoning blocks.
                    operation = {"number": len(operations) + 1, "line": line,
                                 "call_id": call.get("id"), "tool": name,
                                 "arguments": args, "response_text": [], "status": "pending"}
                    operations.append(operation)
                    operations_by_id[call.get("id")] = operation
        elif event.get("role") == "tool" and event.get("tool_call_id") in by_id:
            row = by_id[event["tool_call_id"]]
            row["response_line"] = line
            for block in content_blocks(event.get("content")):
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    row["response_text"].append(block.get("text", ""))
                elif block.get("type") == "image_url":
                    url_value = block.get("imageUrl") or block.get("image_url") or {}
                    url = url_value if isinstance(url_value, str) else url_value.get("url", "")
                    try:
                        image = image_record(url, assets)
                        if image:
                            row["images"].append(image)
                    except (ValueError, OSError) as exc:
                        row.setdefault("decode_errors", []).append(str(exc))
            row["status"] = "image_returned" if row["images"] else "no_image_returned"
        elif event.get("role") == "tool" and event.get("tool_call_id") in operations_by_id:
            operation = operations_by_id[event["tool_call_id"]]
            operation.update(response_line=line, status="returned")
            operation["response_text"] = [block.get("text", "") for block in content_blocks(event.get("content"))
                                          if isinstance(block, dict) and block.get("type") == "text"]
    requests, pixels = {}, {}
    for row in calls:
        key = json.dumps(row["arguments"], sort_keys=True)
        row["same_request_as"] = list(requests.get(key, []))
        requests.setdefault(key, []).append(row["number"])
        key = tuple(image["pixel_sha256"] for image in row["images"])
        row["same_pixels_as"] = list(pixels.get(key, [])) if key else []
        if key:
            pixels.setdefault(key, []).append(row["number"])
        previous_image_line = max((r["line"] for r in calls if r["line"] < row["line"]), default=0)
        next_image_line = min((r["line"] for r in calls if r["line"] > row["line"]), default=float("inf"))
        before = [m for m in public_messages if previous_image_line < m["line"] <= row["line"]]
        after = [m for m in public_messages if row.get("response_line", float("inf")) < m["line"] <= next_image_line]
        direct_after = [m for m in after if not any(
            row.get("response_line", float("inf")) < op["line"] < m["line"]
            for op in operations
        )]
        region = row["arguments"].get("region")
        scope = (f"Inspect {row['arguments'].get('path', '')}; rectangle "
                 f"x={region['x']}, y={region['y']}, width={region['width']}, height={region['height']}"
                 if region else f"Inspect {row['arguments'].get('path', '')}")
        row["wanted"] = {
            "requested_scope": scope, "public_explanation": before,
            "semantic_intent_status": "adjacent_public_statement" if before else "not_recorded",
        }
        row["found"] = {
            "status": "public_observation_candidate" if observation_claims(direct_after) else "not_recorded",
            "observation_candidates": observation_claims(direct_after),
            "public_statements": after,
            "attribution_note": "Nearby public text is not proof of a conclusion about this exact crop; parallel image calls share the same context. Observation candidates exclude statements after intervening non-image tool calls.",
        }
    return calls, operations, dict(counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--events", default="attempts/a001/kimi-events.jsonl")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    job, output = args.job.resolve(), args.output.resolve()
    job.relative_to(root)
    output.relative_to(root)
    events_path = (job / args.events).resolve()
    events_path.relative_to(job)
    if output.exists():
        raise FileExistsError("Use a new export directory to preserve the earlier snapshot")
    # Bound a running log at its current length and ignore an incomplete final record.
    size = events_path.stat().st_size
    with events_path.open("rb") as stream:
        prefix = stream.read(size)
    complete = prefix[:prefix.rfind(b"\n") + 1]
    events, parse_errors = [], []
    for line, raw in enumerate(complete.splitlines(), 1):
        try:
            events.append((line, json.loads(raw)))
        except json.JSONDecodeError as exc:
            parse_errors.append({"line": line, "error": str(exc)})
    assets = {}
    calls, operations, counts = extract(events, assets)
    sources = {}
    for path in sorted((job / "input_files").glob("*")):
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}[path.suffix.lower()]
        data = path.read_bytes()
        record = image_record(f"data:{mime};base64," + base64.b64encode(data).decode(), assets)
        sources[path.relative_to(job).as_posix()] = record
    for row in calls:
        path = str(row["arguments"].get("path", "")).replace("\\", "/")
        row["path"] = path
        row["category"] = ("source crop" if row["arguments"].get("region") else "source whole") if path in sources else "derived image"
        row["source_image"] = sources.get(path)
    summary = {
        "image_calls": len(calls), "images_returned": sum(len(r["images"]) for r in calls),
        "distinct_returned_images": len({i["pixel_sha256"] for r in calls for i in r["images"]}),
        "repeated_pixel_calls": sum(bool(r["same_pixels_as"]) for r in calls),
        "repeated_request_calls": sum(bool(r["same_request_as"]) for r in calls),
        "no_image_returned": sum(r["status"] == "no_image_returned" for r in calls),
        "pending": sum(r["status"] == "pending" for r in calls),
        "calls_with_public_intent": sum(bool(r["wanted"]["public_explanation"]) for r in calls),
        "calls_with_public_followup": sum(bool(r["found"]["public_statements"]) for r in calls),
        "calls_with_observation_candidates": sum(bool(r["found"]["observation_candidates"]) for r in calls),
        "categories": dict(Counter(r["category"] for r in calls)), "tool_counts": counts,
        "autocad_tool_calls": sum(count for name, count in counts.items() if "autocad" in name.lower()),
    }
    data = {
        "schema_version": "1.0", "created_at": datetime.now(timezone.utc).isoformat(),
        "job": job.relative_to(root).as_posix(), "sample": job.parent.name,
        "source": {"path": events_path.relative_to(root).as_posix(),
                   "complete_prefix_bytes": len(complete), "prefix_sha256": digest(complete),
                   "complete_lines": len(complete.splitlines()), "parse_errors": parse_errors,
                   "is_point_in_time_snapshot": True},
        "evidence_scope": "Exact image bytes returned by ReadMediaFile; model attention and successful comprehension cannot be inferred. No private reasoning is exported.",
        "summary": summary, "calls": calls, "operations": operations, "source_images": sources,
    }
    result_path = job / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
    trial_path = job.parent.parent / "trial-config.json"
    trial = json.loads(trial_path.read_text(encoding="utf-8")) if trial_path.is_file() else {}
    native = result.get("agent_loop_protocol", "").startswith("native-kimi-code") or trial.get("harness", "").startswith("native-kimi-code")
    data["run_context"] = {
        "harness": "Kimi Code" if native else "EvoCAD",
        "condition": "Native Kimi Code + Kimi K3" if native else "EvoCAD + Kimi K3 feedback loop",
        "score": result.get("score"), "passed": result.get("passed"), "stop_reason": result.get("stop_reason"),
        "review_url": f"http://127.0.0.1:8770/?view={'direct' if native else 'evocad'}-kimi-{job.parent.name.removeprefix('omnimech-')}",
    }
    prompt_path = events_path.parent / "action-prompt.txt"
    data["action_prompt"] = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else None
    data["public_messages"] = [
        {"line": line, "text": block["text"]}
        for line, event in events if event.get("role") == "assistant"
        for block in content_blocks(event.get("content"))
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").strip()
    ]
    output.mkdir(parents=True)
    (output / "trace.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assets_dir = output / "images"
    assets_dir.mkdir()
    for key, image in assets.items():
        mime = image["data_url"].split(";", 1)[0]
        suffix = ".png" if mime.endswith("png") else ".webp" if mime.endswith("webp") else ".jpg"
        (assets_dir / (key + suffix)).write_bytes(base64.b64decode(image["data_url"].split(",", 1)[1]))
    template = root / "apps/geometry-review/kimi-vision.template.html"
    embedded = json.dumps({**data, "assets": assets}, ensure_ascii=False).replace("<", "\\u003c")
    html = template.read_text(encoding="utf-8").replace("__TRACE_DATA__", embedded)
    (output / "index.html").write_text(html, encoding="utf-8")
    manifest = {"source": data["source"], "exporter_sha256": digest(Path(__file__).read_bytes()),
                "template_sha256": digest(template.read_bytes()),
                "files": [{"path": p.relative_to(output).as_posix(), "sha256": digest(p.read_bytes())}
                          for p in sorted(output.rglob("*")) if p.is_file()]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
