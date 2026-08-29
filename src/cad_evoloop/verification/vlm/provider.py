"""Codex CLI provider for structured, image-only CAD visual evaluation."""

from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Iterable
import uuid


PROHIBITED_ITEM_TYPES = {
    "command_execution",
    "computer_tool_call",
    "file_search_call",
    "mcp_tool_call",
    "web_search_call",
}


def validate_visual_result(value: dict[str, Any], expected_ids: Iterable[str]) -> None:
    expected = list(expected_ids)
    if value.get("image_quality") not in {"sufficient", "insufficient"}:
        raise ValueError("Invalid image_quality")
    rubrics = value.get("rubrics")
    if not isinstance(rubrics, list):
        raise ValueError("rubrics must be an array")
    actual_ids = [item.get("id") for item in rubrics if isinstance(item, dict)]
    if sorted(actual_ids) != sorted(expected) or len(actual_ids) != len(set(actual_ids)):
        raise ValueError(f"Expected exactly these rubric IDs: {expected}")
    for item in rubrics:
        if item.get("verdict") not in {"pass", "fail", "uncertain"}:
            raise ValueError(f"Invalid verdict for {item.get('id')}")
        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError(f"Invalid confidence for {item.get('id')}")
        if not isinstance(item.get("explanation"), str) or not item["explanation"].strip():
            raise ValueError(f"Missing explanation for {item.get('id')}")
        if not isinstance(item.get("evidence"), list):
            raise ValueError(f"Invalid evidence for {item.get('id')}")
        for evidence in item["evidence"]:
            region = evidence.get("region")
            if region is None:
                continue
            if not isinstance(region, dict) or set(region) != {"x", "y", "width", "height"}:
                raise ValueError(f"Invalid evidence region for {item.get('id')}")
            if any(not isinstance(region[key], (int, float)) or not 0 <= region[key] <= 1 for key in region):
                raise ValueError(f"Out-of-range evidence region for {item.get('id')}")
            if region["x"] + region["width"] > 1 or region["y"] + region["height"] > 1:
                raise ValueError(f"Evidence region exceeds image bounds for {item.get('id')}")


class CodexCliProvider:
    def __init__(self, model: str = "gpt-5.5", executable: str = "codex", timeout: int = 300) -> None:
        self.model = model
        self.executable = executable
        self.timeout = timeout

    def evaluate(
        self,
        prompt: str,
        images: list[Path],
        schema_path: Path,
        work_dir: Path,
        expected_ids: Iterable[str],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        executable = shutil.which(self.executable)
        if not executable:
            raise FileNotFoundError(f"Codex CLI not found: {self.executable}")
        work_dir.mkdir(parents=True, exist_ok=True)
        invocation_id = uuid.uuid4().hex
        result_path = work_dir / f"vlm-last-message-{invocation_id}.json"
        events_path = work_dir / f"vlm-events-{invocation_id}.jsonl"
        stderr_path = work_dir / f"vlm-stderr-{invocation_id}.log"
        command = [
            executable,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-rules",
            "--ignore-user-config",
            "--sandbox",
            "read-only",
            "--model",
            self.model,
        ]
        for image in images:
            command.extend(["--image", str(image.resolve())])
        command.extend([
            "--output-schema",
            str(schema_path.resolve()),
            "--json",
            "--output-last-message",
            str(result_path.resolve()),
            "--cd",
            str(work_dir.resolve()),
            "-c",
            "mcp_servers={}",
        ])
        command.append(prompt)
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=work_dir,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            check=False,
        )
        elapsed = round(time.perf_counter() - started, 3)
        events_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(
                f"Codex VLM exited with {completed.returncode}; see {stderr_path}"
            )
        prohibited = []
        usage: dict[str, Any] = {}
        for line in completed.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = event.get("item") or {}
            item_type = item.get("type")
            if item_type in PROHIBITED_ITEM_TYPES:
                prohibited.append(item_type)
            if event.get("type") == "turn.completed":
                usage = event.get("usage") or usage
        if prohibited:
            raise RuntimeError(f"VLM evaluator used prohibited tools: {sorted(set(prohibited))}")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        validate_visual_result(result, expected_ids)
        return result, {
            "provider": "codex-cli",
            "model": self.model,
            "invocation_id": invocation_id,
            "events_path": str(events_path),
            "stderr_path": str(stderr_path),
            "result_path": str(result_path),
            "return_code": completed.returncode,
            "elapsed_seconds": elapsed,
            "usage": usage,
        }
