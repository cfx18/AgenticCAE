"""Export task evidence to the existing immutable human-review service."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from cad_evoloop.agent.events import canonical_json
from cad_evoloop.evaluation.human_review import HumanReviewStore, serve_geometry_review
from cad_evoloop.ledger.ledger import sha256_file, write_json_atomic
from .bundle import validate_bundle


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def export_review(pilot: Path, output: Path, learner_runs: Path | None = None) -> dict:
    workspace = Path(__file__).resolve().parents[3]
    pilot, output = pilot.resolve(), output.resolve()
    if not output.is_relative_to(workspace) or output == workspace:
        raise ValueError("Review output must stay in this project")
    if output.exists():
        raise FileExistsError("Review exports are immutable; use a new output directory")
    summary = json.loads((pilot / "pilot-summary.json").read_text(encoding="utf-8"))
    if summary.get("kind") == "real-drawing-qa-v1":
        return export_drawing_review(pilot, output, summary, learner_runs)
    from .geometry import load_shape
    import cadquery as cq
    if summary["mechanical_passed"] != summary["selected"] or summary["quarantined"]:
        raise ValueError("Do not present incomplete pilot builds as review-ready")
    output.mkdir(parents=True)
    app = output / "app"
    shutil.copytree(workspace / "apps/posttrain-review", app)
    shutil.copyfile(workspace / "apps/geometry-review/geometry-viewer.js", app / "geometry-viewer.js")
    shutil.copytree(workspace / "apps/geometry-review/vendor", app / "vendor")
    runs = []
    for result in summary["results"]:
        task = pilot / "tasks" / result["task_id"]
        manifest = validate_bundle(task)
        assets = output / "assets" / task.name
        shutil.copytree(task, assets / "task")
        shutil.copytree(pilot / result["reference_episode"], assets / "episode")
        write_json_atomic(assets / "acceptance.json", result)
        base = assets.relative_to(output).as_posix()
        public = json.loads((task / "public/task.json").read_text(encoding="utf-8"))
        images = [f"{base}/task/public/{name}" for name in public["input_images"]]
        geometry = {}
        candidates = []
        candidates.append(("Private source GT", task / "private/target.step", "ground_truth"))
        for name in ("initial", "current"):
            path = task / f"public/{name}.step"
            if path.exists():
                candidates.append((name.title() + " model", path, name))
        if (task / "private/alternative.step").exists():
            candidates.append(("Alternative consistent model", task / "private/alternative.step", "alternative"))
        if (assets / "episode/work/model.step").exists():
            candidates.append(("Reference solution", assets / "episode/work/model.step", "reference"))
        for path in sorted((task / "tests").glob("*.step")):
            candidates.append(("Negative: " + path.stem.replace("_", " "), path, path.stem))
        for label, path, key in candidates:
            target = assets / f"{key}.stl"
            cq.exporters.export(load_shape(path), str(target), tolerance=.03, angularTolerance=.1)
            geometry[key] = {"label": label, "path": f"{base}/{key}.stl"}
        asset_evidence = [{"path": str(path.relative_to(output)).replace("\\", "/"), "sha256": sha256_file(path), "bytes": path.stat().st_size}
                          for path in sorted(assets.rglob("*")) if path.is_file()]
        evidence_hash = digest(asset_evidence)
        runs.append({
            "target_id": digest({"task_manifest": sha256_file(task / "manifest.json")})[:24],
            "sample_id": task.name, "model": "trusted-reference-not-an-agent", "dataset": "posttrain-pilot",
            "run_id": task.name, "selected_attempt_id": "reference-01", "input_evidence": asset_evidence,
            "attempts": [{"attempt_id": "reference-01", "evidence_sha256": evidence_hash}],
            "task_manifest": manifest, "task": public, "input_images": images, "geometry_options": geometry,
            "reference_answer": json.loads((task / "reference/answer.json").read_text(encoding="utf-8")),
            "verifier": json.loads((task / "private/verifier.json").read_text(encoding="utf-8")),
            "source": json.loads((task / "provenance/source.json").read_text(encoding="utf-8")),
            "acceptance": result, "events": [json.loads(line) for line in (assets / "episode/events.jsonl").read_text(encoding="utf-8").splitlines()],
            "asset_base": base,
        })
    app_evidence = [{"path": path.relative_to(output).as_posix(), "sha256": sha256_file(path), "bytes": path.stat().st_size}
                    for path in sorted(app.rglob("*")) if path.is_file()]
    bundle = {"schema_version": "1.0", "kind": "posttrain_task_review", "campaign": {
        "campaign_id": summary["pilot_id"], "campaign_manifest_sha256": sha256_file(pilot / "pilot-summary.json"),
        "source_manifest_sha256": summary["source_manifest_sha256"], "protocol": "reference-and-counterexample-acceptance-v1"},
        "summary": summary, "runs": runs, "review_system": {"served_app": app_evidence}}
    bundle["bundle_sha256"] = digest(bundle)
    write_json_atomic(output / "review-data.json", bundle)
    HumanReviewStore(output / "review-data.json", output / "human-reviews.jsonl")
    return {"tasks": len(runs), "bundle_sha256": bundle["bundle_sha256"]}


def export_drawing_review(pilot: Path, output: Path, summary: dict, learner_runs: Path | None) -> dict:
    """Use the same review app/ledger without fabricating CAD GT or reference runs."""
    from .bundle import contained_file

    workspace = Path(__file__).resolve().parents[3]
    output.mkdir(parents=True)
    app = output / "app"
    shutil.copytree(workspace / "apps/posttrain-review", app)
    shutil.copyfile(workspace / "apps/geometry-review/geometry-viewer.js", app / "geometry-viewer.js")
    shutil.copytree(workspace / "apps/geometry-review/vendor", app / "vendor")
    runs = []
    for result in summary["results"]:
        task = pilot / "tasks" / result["task_id"]
        manifest = validate_bundle(task)
        assets = output / "assets" / task.name
        shutil.copytree(task, assets / "task")
        base = assets.relative_to(output).as_posix()
        public = json.loads((task / "public/task.json").read_text(encoding="utf-8"))
        annotation = json.loads((task / "private/annotation.json").read_text(encoding="utf-8"))
        events, answer, learner = [], None, None
        if learner_runs and (learner_runs / task.name / "run.json").is_file():
            run_root = learner_runs / task.name
            learner = json.loads((run_root / "run.json").read_text(encoding="utf-8"))
            state = json.loads((run_root / "episode/episode.json").read_text(encoding="utf-8"))
            if state["task_manifest_sha256"] != sha256_file(task / "manifest.json"):
                raise ValueError("Learner used a different task version")
            if state.get("status") == "submitted":
                for item in state["submission"]["files"]:
                    path = contained_file(run_root / "episode", item["snapshot"])
                    if sha256_file(path) != item["sha256"]:
                        raise ValueError("Learner answer snapshot changed")
                    if item["source"] == "answer.json":
                        answer = json.loads(path.read_text(encoding="utf-8"))
            shutil.copytree(run_root / "episode", assets / "episode")
            for name in ("run.json", "kimi-events.jsonl", "prompt.txt"):
                if (run_root / name).exists():
                    shutil.copyfile(run_root / name, assets / name)
            events = [json.loads(line) for line in (assets / "episode/events.jsonl").read_text(encoding="utf-8").splitlines()]
        evidence = [{"path": p.relative_to(output).as_posix(), "sha256": sha256_file(p), "bytes": p.stat().st_size}
                    for p in sorted(assets.rglob("*")) if p.is_file()]
        attempt = "kimi-01" if learner else "annotation-01"
        downloads = [{"label": "Task manifest", "path": f"{base}/task/manifest.json"},
                     {"label": "题目与框选记录" if manifest.get("label_status") == "unlabeled_probe" else "Astra annotation and blind audit", "path": f"{base}/task/private/annotation.json"}]
        if learner:
            downloads.extend([{"label": "Kimi raw input/output", "path": f"{base}/kimi-events.jsonl"},
                              {"label": "Exact Kimi prompt", "path": f"{base}/prompt.txt"}])
        runs.append({"target_id": digest({"task_manifest": sha256_file(task / "manifest.json")})[:24],
            "sample_id": task.name, "run_id": task.name, "dataset": "real-drawing-qa",
            "model": learner["model"] if learner else "not-run", "selected_attempt_id": attempt,
            "input_evidence": evidence, "attempts": [{"attempt_id": attempt, "evidence_sha256": digest(evidence)}],
            "task_manifest": manifest, "task": public,
            "input_images": [f"{base}/task/public/{name}" for name in public["input_images"]],
            "geometry_options": {}, "reference_answer": json.loads((task / "reference/answer.json").read_text(encoding="utf-8")),
            "annotation": annotation, "learner": learner, "learner_answer": answer,
            "verifier": json.loads((task / "private/verifier.json").read_text(encoding="utf-8")),
            "source": json.loads((task / "provenance/source.json").read_text(encoding="utf-8")),
            "acceptance": {**result, "negative_checks": []}, "events": events, "asset_base": base,
            "download_links": downloads,
            "source_notice": "Real published drawing. Astra-proposed labels; no verified CAD ground truth. Private research, not approved for redistribution.",
            "trajectory_notice": "Kimi public observations, exact image receipts, findings and submission. No hidden reasoning is inferred."})
    app_evidence = [{"path": path.relative_to(output).as_posix(), "sha256": sha256_file(path), "bytes": path.stat().st_size}
                    for path in sorted(app.rglob("*")) if path.is_file()]
    bundle = {"schema_version": "1.0", "kind": "posttrain_task_review", "campaign": {
        "campaign_id": summary["pilot_id"], "campaign_manifest_sha256": sha256_file(pilot / "pilot-summary.json"),
        "source_manifest_sha256": summary["source_manifest_sha256"],
        "protocol": summary.get("protocol", "model-proposed-label-blind-audit-v1")},
        "summary": summary, "runs": runs, "review_system": {"served_app": app_evidence}}
    bundle["bundle_sha256"] = digest(bundle)
    write_json_atomic(output / "review-data.json", bundle)
    HumanReviewStore(output / "review-data.json", output / "human-reviews.jsonl")
    return {"tasks": len(runs), "bundle_sha256": bundle["bundle_sha256"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export_parser = sub.add_parser("export")
    export_parser.add_argument("pilot", type=Path)
    export_parser.add_argument("output", type=Path)
    export_parser.add_argument("--learner-runs", type=Path)
    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("bundle", type=Path)
    serve_parser.add_argument("--port", type=int, default=8772)
    serve_parser.add_argument("--catalog", type=Path)
    args = parser.parse_args()
    if args.command == "export":
        print(json.dumps(export_review(args.pilot, args.output, args.learner_runs)))
    else:
        serve_geometry_review(args.bundle, args.bundle / "human-reviews.jsonl", app_dir=args.bundle / "app",
                              port=args.port, catalog_path=args.catalog)
