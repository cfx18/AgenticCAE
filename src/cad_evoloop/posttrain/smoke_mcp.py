"""Capability-limited, public-input-only MCP for the perception smoke test."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import sys

from cad_evoloop.ledger.ledger import write_json_atomic
from .environment import Episode


TOOLS = [
    {"name": "observe", "description": "Inspect a public task image, optionally cropping a pixel rectangle. State what you want to inspect. Returns the actual image and an observation ID.",
     "inputSchema": {"type": "object", "properties": {
         "image": {"type": "string"}, "intent": {"type": "string"},
         "crop": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4}},
         "required": ["image", "intent"], "additionalProperties": False}},
    {"name": "conclude", "description": "Record a short evidence-based finding about an image you actually inspected, not private reasoning.",
     "inputSchema": {"type": "object", "properties": {
         "observation_id": {"type": "string"}, "finding": {"type": "string"}},
         "required": ["observation_id", "finding"], "additionalProperties": False}},
    {"name": "submit", "description": "Submit your final JSON answer once. No correctness feedback is available during this test.",
     "inputSchema": {"type": "object", "properties": {"answer": {"type": "object"}},
         "required": ["answer"], "additionalProperties": False}},
]


def text_result(value: object) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}


class PublicTools:
    def __init__(self, root: Path):
        self.episode = Episode(root)
        task = json.loads((root / "input/task.json").read_text(encoding="utf-8"))
        self.images = set(task.get("input_images", []))
        self.calls = 0

    def call(self, name: str, args: dict) -> dict:
        self.calls += 1
        if self.calls > 40:
            raise ValueError("Smoke tool budget exceeded")
        if name == "observe":
            if args["image"] not in self.images:
                raise ValueError("Only listed public task images are accessible")
            crop = args.get("crop")
            if crop is not None and (not isinstance(crop, list) or len(crop) != 4 or
                                     any(type(v) is not int for v in crop)):
                raise ValueError("Crop requires four integer pixel coordinates")
            receipt = self.episode.observe(args["image"], intent=args["intent"],
                                           crop=tuple(crop) if crop is not None else None)
            result = text_result(receipt)
            result["content"].append({"type": "image", "mimeType": "image/png", "data":
                                      base64.b64encode((self.episode.root / receipt["image"]).read_bytes()).decode()})
            return result
        if name == "conclude":
            self.episode.conclude_observation(args["observation_id"], args["finding"])
            return text_result({"recorded": True})
        if name == "submit":
            self.episode._active()
            if not isinstance(args.get("answer"), dict):
                raise ValueError("Answer must be a JSON object")
            write_json_atomic(self.episode.root / "work/answer.json", args["answer"])
            return text_result(self.episode.submit(["answer.json"]))
        raise ValueError("Unknown tool")


def serve(root: Path) -> None:
    api = PublicTools(root)
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request:
            continue
        method = request.get("method")
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "evocad-perception-smoke", "version": "1.0.0"}}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            try:
                result = api.call(request["params"]["name"], request["params"].get("arguments", {}))
            except (ValueError, KeyError, TypeError, OSError) as error:
                result = text_result({"error": str(error)})
                result["isError"] = True
        elif method == "ping":
            result = {}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": {
                "code": -32601, "message": "Method not found"}}), flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)


if __name__ == "__main__":
    serve(Path(sys.argv[1]).resolve())
