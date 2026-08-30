"""Create deterministic, stratified geometry benchmark splits."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from cad_evoloop.ledger.ledger import sha256_file

from .geometry_campaign import PROTOCOL_ID, load_geometry_manifest


DEFAULT_SEED = "evocad-geometry-split-v1-20260830"
DEFAULT_RATIOS = {"dev": 0.4, "validation": 0.2, "hidden_test": 0.4}


def _stable_order(samples: list[dict[str, Any]], seed: str) -> list[dict[str, Any]]:
    return sorted(
        samples,
        key=lambda sample: hashlib.sha256(
            f"{seed}\0{sample['sample_id']}".encode("utf-8")
        ).hexdigest(),
    )


def _allocate(total: int, weights: dict[str, float]) -> dict[str, int]:
    if total < 0 or not weights or any(weight < 0 for weight in weights.values()):
        raise ValueError("Allocation totals and weights must be non-negative")
    weight_sum = sum(weights.values())
    if weight_sum <= 0:
        raise ValueError("Allocation weights must have a positive sum")
    exact = {name: total * weight / weight_sum for name, weight in weights.items()}
    counts = {name: math.floor(value) for name, value in exact.items()}
    remainder = total - sum(counts.values())
    priority = sorted(weights, key=lambda name: (-(exact[name] - counts[name]), name))
    for name in priority[:remainder]:
        counts[name] += 1
    return counts


def _sample_set_sha256(sample_ids: list[str]) -> str:
    payload = "\n".join(sorted(sample_ids)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _payload_sha256(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_geometry_split(
    manifest: str | Path,
    *,
    seed: str = DEFAULT_SEED,
    ratios: dict[str, float] | None = None,
    pilot_count: int = 10,
) -> dict[str, Any]:
    manifest_path, value = load_geometry_manifest(manifest)
    ratios = dict(ratios or DEFAULT_RATIOS)
    if set(ratios) != set(DEFAULT_RATIOS):
        raise ValueError(f"Split names must be {sorted(DEFAULT_RATIOS)}")
    if pilot_count < 1:
        raise ValueError("pilot_count must be at least 1")
    scorable = [sample for sample in value["samples"] if sample.get("ground_truth_step")]
    if pilot_count > len(scorable):
        raise ValueError("pilot_count exceeds the number of scorable samples")
    by_dataset: dict[str, list[dict[str, Any]]] = {}
    for sample in scorable:
        by_dataset.setdefault(sample["dataset"], []).append(sample)

    splits = {name: [] for name in ratios}
    strata: dict[str, dict[str, int]] = {}
    for dataset in sorted(by_dataset):
        ordered = _stable_order(by_dataset[dataset], f"{seed}:split:{dataset}")
        allocation = _allocate(len(ordered), ratios)
        strata[dataset] = allocation
        offset = 0
        for name in ratios:
            count = allocation[name]
            splits[name].extend(sample["sample_id"] for sample in ordered[offset:offset + count])
            offset += count

    dev_by_dataset = {
        dataset: [sample for sample in by_dataset[dataset] if sample["sample_id"] in splits["dev"]]
        for dataset in by_dataset
    }
    pilot_allocation = _allocate(
        pilot_count,
        {dataset: len(samples) for dataset, samples in dev_by_dataset.items()},
    )
    pilot = []
    for dataset in sorted(dev_by_dataset):
        ordered = _stable_order(dev_by_dataset[dataset], f"{seed}:pilot:{dataset}")
        pilot.extend(sample["sample_id"] for sample in ordered[:pilot_allocation[dataset]])

    sample_ids = [sample["sample_id"] for sample in scorable]
    payload = {
        "schema_version": "1.0",
        "protocol": PROTOCOL_ID,
        "kind": "stratified-geometry-split",
        "seed": seed,
        "source_manifest_sha256": sha256_file(manifest_path),
        "source_sample_ids_sha256": _sample_set_sha256(sample_ids),
        "ratios": ratios,
        "sample_count": len(sample_ids),
        "strata": strata,
        "splits": splits,
        "cost_pilot": {
            "source_split": "dev",
            "sample_count": len(pilot),
            "strata": pilot_allocation,
            "sample_ids": pilot,
        },
    }
    payload["split_sha256"] = _payload_sha256(payload)
    validate_geometry_split(payload, sample_ids=sample_ids)
    return payload


def validate_geometry_split(payload: dict[str, Any], *, sample_ids: list[str] | None = None) -> None:
    if payload.get("schema_version") != "1.0" or payload.get("protocol") != PROTOCOL_ID:
        raise ValueError("Unsupported geometry split")
    recorded_sha = payload.get("split_sha256")
    unsigned = {key: value for key, value in payload.items() if key != "split_sha256"}
    if recorded_sha != _payload_sha256(unsigned):
        raise ValueError("Geometry split digest does not match its contents")
    splits = payload.get("splits")
    if not isinstance(splits, dict) or set(splits) != set(DEFAULT_RATIOS):
        raise ValueError("Geometry split must contain dev, validation, and hidden_test")
    flattened = [sample_id for name in DEFAULT_RATIOS for sample_id in splits[name]]
    if len(flattened) != len(set(flattened)):
        raise ValueError("Geometry splits overlap or contain duplicate samples")
    if len(flattened) != payload.get("sample_count"):
        raise ValueError("Geometry split sample count is inconsistent")
    if sample_ids is not None:
        if set(flattened) != set(sample_ids):
            raise ValueError("Geometry split does not cover the provided sample set")
        if payload.get("source_sample_ids_sha256") != _sample_set_sha256(sample_ids):
            raise ValueError("Geometry split sample-set digest does not match")
    pilot = payload.get("cost_pilot", {}).get("sample_ids", [])
    if len(pilot) != len(set(pilot)) or not set(pilot).issubset(splits["dev"]):
        raise ValueError("Cost pilot must be a unique subset of dev")


def write_geometry_split(
    manifest: str | Path,
    output: str | Path,
    *,
    seed: str = DEFAULT_SEED,
    pilot_count: int = 10,
) -> dict[str, Any]:
    payload = build_geometry_split(manifest, seed=seed, pilot_count=pilot_count)
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload
