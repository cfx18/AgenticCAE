"""Publish a frozen, unscored native trial into the existing review catalog."""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import zipfile

from cad_evoloop.evaluation.geometry_review import _public_events, _mcp_events
from cad_evoloop.evaluation.human_review import _canonical_sha256
from cad_evoloop.ledger.ledger import sha256_file


class Node:
    def __init__(self, tag="", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return "".join(c.text() if isinstance(c, Node) else c for c in self.children)

    def find(self, cls):
        matches = [self] if cls in self.attrs.get("class", "").split() else []
        return matches + [n for c in self.children if isinstance(c, Node) for n in c.find(cls)]


class ReportParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = Node()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {"img", "br", "hr", "input", "meta", "link", "source", "wbr"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse_report(path, sample="111"):
    parser = ReportParser()
    parser.feed(path.read_text(encoding="utf-8"))
    cards = [c for c in parser.root.find("fixture-card")
             if c.find("card-title") and c.find("card-title")[0].text().split()[0] == sample]
    if len(cards) != 1:
        raise ValueError(f"Expected one report card for {sample}")
    card = cards[0]
    values = {}
    for css, name in (("cad", "cad_score"), ("shape", "shape_similarity"),
                      ("iface", "interface_match"), ("topo", "topology_match")):
        section = card.find("headline-" + css)[0]
        values[name] = float(section.find("headline-value")[0].text())
    shape_text = card.find("headline-shape")[0].text()
    for label, name in (("Surface Distance F1", "surface_f1"), ("Volume IoU", "volume_iou")):
        values[name] = float(re.search(re.escape(label) + r":\s*([0-9.]+)", shape_text)[1])
    values["betti"] = card.find("headline-topo")[0].find("headline-sub")[0].text().strip()
    values["valid"] = bool(card.find("status-valid"))
    return values


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export(root, run, out, archive, submission):
    root, run, out, archive, submission = [p.resolve() for p in (root, run, out, archive, submission)]
    for path in (run, out, archive, submission):
        if path == root or not path.is_relative_to(root):
            raise ValueError("Paths must stay inside workspace")
    if out.exists() or archive.exists() or archive.with_suffix(".zip").exists():
        raise FileExistsError("Refusing to overwrite a frozen review")
    result = read(run / "result.json")
    if result["status"] != "generation_ready_for_review":
        raise ValueError("Run is not complete")
    manifest = read(run / "recorded-execution/manifest.json")
    for item in manifest["files"]:
        source = (run / item["path"]).resolve()
        if not source.is_relative_to(run) or sha256_file(source) != item["sha256"]:
            raise ValueError("Frozen run changed: " + item["path"])
    archive.mkdir(parents=True)
    # The adapter copies only hash-verified source records, not arbitrary workspace files.
    for item in manifest["files"]:
        target = archive / "raw" / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(run / item["path"], target)
    shutil.copy2(run / "recorded-execution/manifest.json", archive / "source-manifest.json")
    verification = read(run / "outputs/verification.json")
    references = []
    for filename, label, report_id in [
        ("reference-astra-high.html", "Astra High + build123d MCP (pzfreo)",
         "pzfreo_build123d-mcp-0-3-85-dev0-with-gpt-6-ast_20260905-073202"),
        ("reference-astra-codex-low.html", "Codex + Astra Low + CadQuery (modelcorp)",
         "modelcorp_baseline-astra-codex-low-v1_20260905-013922"),
    ]:
        path = submission / filename
        references.append({"label": label, "sample_id": "111", "metrics": parse_report(path),
                           "status": "official_report_unvalidated_submission", "source_sha256": sha256_file(path),
                           "source_url": f"https://huggingai4engineering-cadgenbench.hf.space/reports/{report_id}.html#sample=111"})
        shutil.copy2(path, archive / filename)
    comparison = {
        "benchmark": "CADGenBench", "task_type": "generation", "sample_id": "111",
        "score_scale": "0 to 1", "formula": "CADScore = 0.4 shape + 0.4 interface + 0.2 topology; shape = (Surface F1 + Volume IoU) / 2",
        "status": "awaiting_authenticated_submission", "official_metrics": None,
        "notes": "Same fixture, different harnesses and reasoning budgets. Reference values are rounded to 3 decimals by public official reports; submissions are unvalidated. No controlled ranking claim. Local validity is not GT accuracy. Chamfer and volume error are not published in these reference cards.",
        "metric_docs": "https://github.com/huggingface/cadgenbench/blob/main/docs/metrics.md",
        "candidate": {"label": "Codex + Astra Ultra + AutoCAD (this run)", "metrics": {}},
        "references": references,
        "conversion": read(submission / "conversion-verification.json") if (submission / "conversion-verification.json").is_file() else None,
    }
    for name in ("candidate.step", "submission.zip", "conversion-verification.json", "conversion.log", "convert-sat.py"):
        if (submission / name).is_file():
            shutil.copy2(submission / name, archive / name)
    write(archive / "comparison.json", comparison)
    events_path = run / "attempts/a001/codex-events.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    timeline = [{"sequence": 1, "phase": "a001/action", "kind": "model_input_prompt", "source": "raw/attempts/a001/action-prompt.txt",
                 "payload": {"text": (run / "attempts/a001/action-prompt.txt").read_text(encoding="utf-8")}}]
    timeline += [{"sequence": i + 2, "phase": "a001/action", "kind": "cli_event", "source": "raw/attempts/a001/codex-events.jsonl",
                  "source_line": i + 1, "payload": event} for i, event in enumerate(events)]
    (archive / "timeline.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in timeline), encoding="utf-8")
    jobs = []
    for job in read(run / "recorded-execution/native-jobs.json"):
        directory = "raw/recorded-execution/autocad/" + job["job_id"]
        jobs.append({"directory": directory, "job_id": job["job_id"], "phase": "a001/action", "actor": "agent",
                     "files": [p.name for p in sorted((archive / directory).iterdir()) if p.is_file()]})
    write(archive / "autocad/index.json", jobs)
    summary = {"campaign": run.name, "sample_id": "cadgenbench:111", "model": "gpt-6-astra", "reasoning_effort": "ultra",
               "score": None, "passed": None, "condition": "native-codex", "elapsed_seconds": result["elapsed_seconds"],
               "counts": {"cli_events": len(events), "mcp_audit_calls": manifest["mcp_calls"], "native_jobs": len(jobs)},
               "limitations": ["GT is private; official accuracy has not been evaluated.",
                               "Local artifact checks and inferred dimensions do not prove GT agreement.",
                               "SAT to STEP conversion is postrun format translation, not agent remodeling.",
                               "Recorded prompts, public messages, calls and returns are available; hidden model reasoning is not.",
                               result["record_recovery"]]}
    write(archive / "summary.json", summary)
    files = [{"path": p.relative_to(archive).as_posix(), "sha256": sha256_file(p), "bytes": p.stat().st_size}
             for p in sorted(archive.rglob("*")) if p.is_file()]
    write(archive / "manifest.json", {"schema_version": "1.0", "files": files})
    with zipfile.ZipFile(archive.with_suffix(".zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(archive.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(archive).as_posix())
    assets = out / "assets"
    assets.mkdir(parents=True)
    def asset(source, name):
        target = assets / name
        shutil.copy2(source, target)
        return {"path": "assets/" + name, "sha256": sha256_file(target), "bytes": target.stat().st_size}
    original = asset(run / "input/input.png", "input.png")
    candidate = asset(run / "outputs/candidate.dwg", "candidate.dwg")
    image = asset(run / "outputs/renders/isometric.png", "candidate.png")
    mesh = asset(run / "outputs/renders/candidate.stl", "candidate.stl")
    asset(run / "outputs/renders/front.png", "front.png")
    asset(run / "outputs/renders/opposite-isometric.png", "opposite-isometric.png")
    evidence = {"candidate": candidate, "render_images": {"candidate": image}, "geometry_assets": {"candidate": mesh}}
    verdict = {"protocol": "cadgenbench-generation-pending-official", "score": None, "passed": None,
               "metrics": {}, "rubrics": [], "candidate_geometry": {"extents": verification["native_envelope_mm"],
               "volume": verification["native_volume_mm3"]}, "local_verification": verification}
    attempt = {"attempt_id": "a001", "attempt_number": 1, "selected": True, "score": None, "passed": None,
               **{k: result[k] for k in ("elapsed_seconds", "return_code", "timed_out", "usage", "thread_id")},
               "decision_reason": "Native Codex completed after local validation; no GT metric feedback was available.",
               "evidence": evidence, "evidence_sha256": _canonical_sha256(evidence), "verdict": verdict,
               "images": {"candidate": image["path"]}, "geometry": {"candidate": mesh["path"]},
               "public_events": _public_events(events_path, "action"), "mcp_events": _mcp_events(run / "attempts/a001/mcp-audit.jsonl"),
               "benchmark_comparison": comparison}
    trial = {"target_id": "cadgenbench-111-astra-ultra", "run_id": run.name, "sample_id": "cadgenbench:111",
             "sample_key": "cadgenbench / 111", "dataset": "cadgenbench", "category": "generation",
             "task": "CADGenBench / 111", "model": "gpt-6-astra", "reasoning_effort": "ultra", "score": None,
             "passed": None, "status": "unscored", "selected_attempt_id": "a001", "stop_reason": "generation_ready_for_review",
             "selected_evidence_sha256": attempt["evidence_sha256"], "candidate_sha256": candidate["sha256"],
             "ground_truth_sha256": None, "integrity": {"ok": True, "checked_files": len(manifest["files"]), "errors": []},
             "input_images": [original["path"]], "input_evidence": [original], "attempts": [attempt]}
    bundle = {"schema_version": "1.0", "review_ui_version": "1.0", "campaign": {
        "campaign_id": run.name, "campaign_manifest_sha256": sha256_file(run / "run.json"),
        "source_manifest_sha256": sha256_file(run / "recorded-execution/manifest.json"),
        "protocol": verdict["protocol"], "agent_loop_protocol": "native-codex-single-conversation-v1"},
        "models": ["gpt-6-astra"], "runs": [trial]}
    bundle["bundle_sha256"] = _canonical_sha256(bundle)
    write(out / "review-data.json", bundle)
    config = {"id": "cadgenbench-astra-111", "harness": "Codex", "label": "CADGenBench 111 - Astra Ultra",
              "bundle": out.relative_to(root).as_posix(), "reviews": "evals/cadgenbench/human-reviews/111-astra-ultra.jsonl",
              "recorded_io": {"directory": archive.relative_to(root).as_posix(), "manifest_sha256": sha256_file(archive / "manifest.json"),
                              "zip_path": archive.with_suffix(".zip").relative_to(root).as_posix(), "zip_sha256": sha256_file(archive.with_suffix(".zip")),
                              "note": "Official GT accuracy pending. One native Codex conversation, AutoCAD construction, no GT feedback. Self-checks are not an accuracy score."}}
    write(out / "catalog-entry.json", config)
    print(json.dumps(config, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--submission", type=Path, required=True)
    args = p.parse_args()
    export(Path(__file__).resolve().parents[3], args.run, args.output, args.archive, args.submission)
