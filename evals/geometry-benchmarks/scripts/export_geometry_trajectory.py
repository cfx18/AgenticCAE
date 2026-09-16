"""Export a completed geometry trial's recorded I/O without rerunning CAD or a model."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export_trial(workspace, campaign, output):
    workspace, campaign, output = map(lambda p: Path(p).resolve(), (workspace, campaign, output))
    archive = output.with_suffix(".zip")
    for path in (campaign, output, archive):
        if not path.is_relative_to(workspace) or path == workspace:
            raise ValueError(f"Path must be inside the workspace: {path}")
    if output.is_relative_to(campaign) or campaign.is_relative_to(output):
        raise ValueError("Export and source campaign must not contain one another")
    if output.exists() or archive.exists():
        raise FileExistsError("Refusing to overwrite an existing export or archive")
    all_rows = read_json(campaign / "results.json")
    rows = [row for row in all_rows if Path(row["job_dir"]).resolve().is_relative_to(campaign)]
    if len(rows) != 1:
        raise ValueError("This exporter requires exactly one campaign-owned run")
    result = rows[0]
    diagnostic = result.get("stop_reason") == "human-requested-diagnostic-complete"
    job, ledger = Path(result["job_dir"]).resolve(), Path(result["ledger_run"]).resolve()
    if (not job.is_relative_to(campaign) or job == campaign
            or not ledger.is_relative_to(workspace) or ledger == workspace):
        raise ValueError("Run paths escape their expected source directories")
    if output.is_relative_to(ledger) or ledger.is_relative_to(output):
        raise ValueError("Export and ledger must not contain one another")
    if not result.get("stop_reason"):
        raise ValueError("Run has not completed")

    output.mkdir(parents=True)
    provenance = {}
    warnings = []

    def copy_file(source, destination):
        resolved = source.resolve()
        if source.is_symlink() or not resolved.is_relative_to(workspace):
            raise ValueError(f"Archive source escapes workspace or is a symlink: {source}")
        before = digest(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if digest(destination) != before or digest(source) != before:
            raise ValueError(f"Source changed during export: {source}")
        provenance[destination.relative_to(output).as_posix()] = source.relative_to(workspace).as_posix()

    def copy_tree(source, destination):
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"Symlinks are not exported: {path}")
            if path.is_file() and not path.name.endswith(".lock"):
                copy_file(path, destination / path.relative_to(source))

    copy_tree(campaign, output / "raw/campaign")
    copy_tree(ledger, output / "raw/ledger")
    script = Path(__file__).resolve()
    if script.is_relative_to(workspace):
        copy_file(script, output / "exporter.py")

    def exported(path):
        if path.is_relative_to(campaign):
            return "raw/campaign/" + path.relative_to(campaign).as_posix()
        raise ValueError(f"Timeline source outside campaign: {path}")

    timeline, calls, messages, phases = [], [], [], []
    counts = Counter()

    def append(phase, kind, source, payload, line=None):
        record = {"sequence": len(timeline) + 1, "phase": phase, "kind": kind,
                  "source": exported(source), "source_line": line, "payload": payload}
        timeline.append(record)
        return record

    def json_lines(path):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                yield number, json.loads(line)
            except ValueError:
                warnings.append({"source": exported(path), "line": number,
                                 "error": "Malformed JSONL; original bytes retained in raw export"})

    def model_phase(name, directory, prompt_name, events_name):
        phases.append({"name": name, "directory": exported(directory)})
        prompt = directory / prompt_name
        if prompt.is_file():
            append(name, "model_input_prompt", prompt, {"text": prompt.read_text(encoding="utf-8")})
        else:
            warnings.append({"phase": name, "error": "No saved input prompt"})
        events = directory / events_name
        if events.is_file():
            for number, event in json_lines(events):
                append(name, "cli_event", events, event, number)
                counts["cli_events"] += 1
                if event.get("type") == "item.completed":
                    item = event.get("item", {})
                    counts[item.get("type", "unknown_item")] += 1
                    if item.get("type") == "agent_message":
                        messages.append((name, item.get("text", "")))
        else:
            warnings.append({"phase": name, "error": "No saved CLI event stream"})
        audit = directory / "mcp-audit.jsonl"
        if audit.is_file():
            for number, event in json_lines(audit):
                calls.append({"sequence": len(calls) + 1, "phase": name,
                              "source": exported(audit), "source_line": number, "event": event})

    for attempt in result["attempts"]:
        attempt_id = attempt["attempt_id"]
        directory = job / "attempts" / attempt_id
        for interruption in sorted((directory / "action-interruptions").glob("i*")):
            if interruption.is_dir():
                model_phase(f"{attempt_id}/interrupted/{interruption.name}", interruption,
                            "action-prompt.txt", "codex-events.jsonl")
        if diagnostic:
            for path in (campaign / "provenance.json", directory / "mirror-core-job.json"):
                if path.is_file():
                    append(f"{attempt_id}/human-diagnostic", "human_diagnostic_evidence", path, read_json(path))
        else:
            model_phase(f"{attempt_id}/action", directory, "action-prompt.txt", "codex-events.jsonl")
        verdict = directory / "geometry-verdict.json"
        if verdict.is_file():
            append(f"{attempt_id}/verifier", "evaluator_output", verdict, read_json(verdict))
        decisions = sorted((directory / "decision-turns").glob("t*"))
        for decision in decisions:
            if decision.is_dir():
                model_phase(f"{attempt_id}/decision/{decision.name}", decision, "prompt.txt", "events.jsonl")
        if not decisions and (directory / "reflection-events.jsonl").is_file():
            model_phase(f"{attempt_id}/reflection", directory, "reflection-prompt.txt", "reflection-events.jsonl")

    # Preserve per-stream ordering. CLI events lack wall-clock timestamps; do not invent interleaving.
    for name, records in (("timeline.jsonl", timeline), ("mcp-calls.jsonl", calls)):
        (output / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    ledger_manifest = read_json(ledger / "run.json")
    artifact_index = {}
    for attempt in ledger_manifest["attempts"]:
        for artifact in attempt["artifacts"]:
            if artifact.get("storage") == "copy":
                source = (ledger / artifact["stored_path"]).resolve()
                if not source.is_relative_to(ledger) or digest(source) != artifact["sha256"]:
                    raise ValueError("Ledger artifact path/hash mismatch")
                artifact_index[Path(artifact["source_path"]).resolve()] = source

    native_jobs = []
    for call in calls:
        event = call["event"]
        if event.get("tool") != "autocad_core_start" or event.get("status") != "pass":
            continue
        payload = None
        for block in event.get("response", {}).get("result", {}).get("content", []):
            if block.get("type") == "text":
                try:
                    value = json.loads(block["text"])
                except ValueError:
                    continue
                if isinstance(value, dict) and value.get("job_dir"):
                    payload = value
                    break
        if payload is None:
            warnings.append({"call": call["sequence"], "error": "Native job directory not captured"})
            continue
        original_job = Path(payload["job_dir"]).resolve()
        if not original_job.is_relative_to(workspace / "mcp/jobs"):
            raise ValueError("Native job path outside workspace/mcp/jobs")
        stage = re.sub(r"[^a-zA-Z0-9_-]", "-", Path(event["arguments"]["output_path"]).stem)
        name = f"{len(native_jobs) + 1:02d}-{stage}"
        directory = output / "autocad" / name
        directory.mkdir(parents=True)
        (directory / "agent-input.lsp").write_text(event["arguments"]["lisp"], encoding="utf-8")
        write_json(directory / "mcp-call.json", call)
        copied = []
        for original, saved in artifact_index.items():
            if original.is_relative_to(original_job):
                relative = original.relative_to(original_job)
                copy_file(saved, directory / relative)
                copied.append(relative.as_posix())
        # Older trials archived only selected artifacts. Preserve remaining native
        # files now, labeling them as postrun snapshots rather than model observations.
        postrun_files = []
        for original in sorted(original_job.rglob("*")):
            relative = original.relative_to(original_job)
            if original.is_file() and relative.as_posix() not in copied:
                copy_file(original, directory / relative)
                postrun_files.append(relative.as_posix())
                copied.append(relative.as_posix())
        if not copied:
            warnings.append({"call": call["sequence"], "error": "Native job files absent from immutable ledger"})
        native_jobs.append({"index": len(native_jobs) + 1, "job_id": payload["job_id"],
                            "directory": directory.relative_to(output).as_posix(), "phase": call["phase"],
                            "mcp_sequence": call["sequence"], "files": sorted(copied),
                            "postrun_snapshot_files": postrun_files, "actor": "agent"})
    if diagnostic:
        for attempt in result["attempts"]:
            path = job / "attempts" / attempt["attempt_id"] / "mirror-core-job.json"
            if not path.is_file():
                continue
            payload = read_json(path)
            original_job = Path(payload["job_dir"]).resolve()
            if not original_job.is_relative_to(workspace / "mcp/jobs"):
                raise ValueError("Native job path outside workspace/mcp/jobs")
            directory = output / "autocad/01-human-mirror"
            directory.mkdir(parents=True)
            copied = []
            for original in sorted(original_job.rglob("*")):
                if original.is_file():
                    relative = original.relative_to(original_job)
                    copy_file(artifact_index.get(original.resolve(), original), directory / relative)
                    copied.append(relative.as_posix())
            native_jobs.append({"index": 1, "job_id": payload["job_id"],
                                "directory": directory.relative_to(output).as_posix(),
                                "phase": "human-diagnostic", "files": copied, "actor": "human-supervisor"})
    write_json(output / "autocad/index.json", native_jobs)

    summary = {
        "campaign": result["campaign"], "sample_id": result["sample_id"], "model": result["model"],
        "reasoning_effort": result["reasoning_effort"], "score": result["score"],
        "passed": result["passed"], "selected_attempt_id": result["selected_attempt_id"],
        "phases": phases, "counts": {**dict(counts), "mcp_audit_calls": len(calls),
                                    "native_jobs": len(native_jobs), "timeline_records": len(timeline)},
        "mcp_tools": dict(Counter(c["event"]["tool"] for c in calls)), "warnings": warnings,
        "condition": "human-diagnostic" if diagnostic else (
            "evocad" if result.get("agent_loop_protocol", "").startswith("evocad-") else "native-codex"),
        "source_result_rows": len(all_rows), "selected_run_id": result.get("run_id"),
        "elapsed_seconds": sum(a.get("elapsed_seconds", 0) for a in result["attempts"]),
        "scope": "All locally captured trial I/O, not a model-service HTTP dump or private reasoning trace",
        "ordering": "Phase order and original stream line order; CLI events do not carry wall-clock timestamps",
        "deduplication": "Decision-turn streams are canonical; copied reflection events remain in raw files only",
        "limitations": ["No model-service hidden prompts, private reasoning, or exact serialized HTTP requests",
                        "Images are original input files, not the service's internal visual token representation",
                        "Any output truncation already present in source logs cannot be reconstructed",
                        "Interrupted calls may have a start event without a recorded result",
                        "Tool schemas are available in frozen source snapshots, not a captured tools/list transcript"],
    }
    write_json(output / "summary.json", summary)
    public_text = ["# Recorded Agent Messages", "", "Public messages only; not private chain-of-thought.", ""]
    for name, message in messages:
        public_text.extend(["## " + name, "", message, ""])
    (output / "agent-messages.md").write_text("\n".join(public_text), encoding="utf-8")
    transcript = ["# Recorded Model And Tool I/O", "",
                  "Prompts and CLI-emitted events in phase/line order. No content summaries or invented timestamps.", "",
                  "Input images and all original files: raw/campaign/. Native jobs: autocad/.", ""]
    for record in timeline:
        text = json.dumps(record["payload"], ensure_ascii=False, indent=2)
        fence = "`" * max(3, max((len(m.group()) + 1 for m in re.finditer(r"`+", text)), default=3))
        transcript.extend([f"## {record['sequence']:03d} {record['phase']} / {record['kind']}", "",
                           f"Source: `{record['source']}` line {record['source_line']}", "",
                           fence + "json", text, fence, ""])
    (output / "transcript.md").write_text("\n".join(transcript), encoding="utf-8")
    (output / "README.md").write_text(
        "# OmniMech Trial Recorded I/O\n\n"
        f"Recorded condition: {summary['condition']}. The human diagnostic makes no new model call.\n\n"
        "- `summary.json`: counts, phases, export warnings and completeness limits.\n"
        "- `transcript.md`: readable prompts and every CLI event, including interrupted events.\n"
        "- `agent-messages.md`: public Agent messages and its final decision.\n"
        "- `timeline.jsonl`: structured event stream; IDs are scoped to phase, not globally unique.\n"
        "- `mcp-calls.jsonl`: exact audit arguments/results, with original timestamps and line references.\n"
        "- `autocad/`: ordered native jobs; agent-input.lsp is the submitted code; payload.lsp adds "
        "backend saving/handle capture. run.scr is the executed wrapper; stdout/stderr are native output.\n"
        "- `raw/campaign/`: original prompts, input images, events, score/feedback, recovery, DWGs and kernel records.\n"
        "- `raw/ledger/`: archived immutable evidence and frozen source snapshots.\n"
        "- `manifest.json`: SHA-256 and size of every exported file except this manifest itself.\n\n"
        "This is a local evidence export, not a complete model-service request/response capture. "
        "No account credentials or unrelated conversations were read or exported. "
        "Private model reasoning and unrecorded data cannot be recovered. "
        "Raw source files are copied unchanged; normalized streams do not duplicate the reflection "
        "compatibility copies. Native logs are evaluator/backend evidence and were not necessarily "
        "all read by the Agent. The CLI command output shows what the Agent actually received.\n",
        encoding="utf-8",
    )
    manifest = {"schema_version": "1.0", "source_campaign": campaign.relative_to(workspace).as_posix(),
                "files": [{"path": p.relative_to(output).as_posix(), "sha256": digest(p),
                           "bytes": p.stat().st_size, "source": provenance.get(p.relative_to(output).as_posix())}
                          for p in sorted(output.rglob("*")) if p.is_file()]}
    write_json(output / "manifest.json", manifest)
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(output).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError("ZIP integrity failed")
    return {"output": str(output), "archive": str(archive), "archive_sha256": digest(archive),
            "files": len(manifest["files"]) + 1, "counts": summary["counts"], "warnings": warnings}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(export_trial(args.workspace, args.campaign, args.output), ensure_ascii=True, indent=2))
