"""Prepare a domain-balanced 50-workflow subset of CAD 1000 Hours."""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import requests


REPO = "markov-ai/cad-1000-hours"
REVISION = "main"
DEFAULT_COUNT = 50
ROOT = Path(__file__).resolve().parents[1]


def request_bytes(url: str, timeout: int) -> bytes:
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "AgenticCAE-eval-preparer/1.0"},
                timeout=timeout,
            )
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            last_error = exc
            if attempt < 4:
                time.sleep(2 ** attempt)
    assert last_error is not None
    raise last_error


def get_json(url: str) -> Any:
    return json.loads(request_bytes(url, 120))


def get_bytes(url: str) -> bytes:
    return request_bytes(url, 300)


def resolve_url(path: str) -> str:
    quoted = urllib.parse.quote(path, safe="/")
    return f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/{quoted}"


def dataset_metadata() -> dict[str, Any]:
    return get_json(f"https://huggingface.co/api/datasets/{REPO}")


def workflow_files(metadata: dict[str, Any]) -> dict[str, list[str]]:
    workflows: dict[str, list[str]] = defaultdict(list)
    for sibling in metadata.get("siblings", []):
        path = sibling["rfilename"]
        parts = path.split("/")
        if len(parts) >= 3 and parts[0] == "autocad":
            workflows[parts[1]].append(path)
    return dict(workflows)


def fetch_task(item: tuple[str, list[str]]) -> dict[str, Any]:
    workflow_id, files = item
    path = f"autocad/{workflow_id}/task_desc.json"
    task = get_json(resolve_url(path))
    return {"id": workflow_id, "files": sorted(files), "task": task}


def balanced_select(workflows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    groups: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    for workflow in sorted(workflows, key=lambda item: item["id"]):
        domain = workflow["task"].get("domain") or "Unspecified"
        groups[str(domain)].append(workflow)

    selected: list[dict[str, Any]] = []
    domains = deque(sorted(groups))
    while domains and len(selected) < count:
        domain = domains.popleft()
        selected.append(groups[domain].popleft())
        if groups[domain]:
            domains.append(domain)
    return selected


def artifact_paths(workflow: dict[str, Any], mode: str) -> list[str]:
    base_names = {"task_desc.json", "rubrics.json", "metadata.json"}
    if mode == "full":
        return workflow["files"]
    paths = []
    for path in workflow["files"]:
        name = path.rsplit("/", 1)[-1]
        if name in base_names:
            paths.append(path)
        elif mode == "core" and ("/input_files/" in path or "/output_files/" in path):
            paths.append(path)
    return paths


def download(path: str) -> None:
    destination = ROOT / "samples" / Path(path).relative_to("autocad")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(get_bytes(resolve_url(path)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--artifacts", choices=("metadata", "core", "full"), default="metadata")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.count <= 0:
        parser.error("--count must be positive")

    metadata = dataset_metadata()
    files_by_workflow = workflow_files(metadata)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        workflows = list(pool.map(fetch_task, sorted(files_by_workflow.items())))
    selected = balanced_select(workflows, min(args.count, len(workflows)))

    manifest = {
        "source": f"https://huggingface.co/datasets/{REPO}",
        "revision": REVISION,
        "license": metadata.get("cardData", {}).get("license"),
        "selection": "deterministic round-robin by task_desc.domain, then workflow id",
        "requested_count": args.count,
        "sample_count": len(selected),
        "samples": [
            {
                "id": item["id"],
                "domain": item["task"].get("domain"),
                "task": item["task"].get("task"),
                "dimensions": len(item["task"].get("dimensions", [])),
                "files": item["files"],
            }
            for item in selected
        ],
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    paths = [path for item in selected for path in artifact_paths(item, args.artifacts)]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(download, paths))

    domains = sorted({item["task"].get("domain") or "Unspecified" for item in selected})
    print(f"Prepared {len(selected)} workflows across {len(domains)} domains")
    print(f"Downloaded {len(paths)} files using artifact mode: {args.artifacts}")
    print(f"Manifest: {ROOT / 'manifest.json'}")


if __name__ == "__main__":
    main()
