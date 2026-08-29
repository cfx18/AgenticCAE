from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).parents[1] / "batch_codex.py"
SPEC = importlib.util.spec_from_file_location("batch_codex", MODULE_PATH)
BATCH = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(BATCH)


def test_codex_command_keeps_prompt_outside_variadic_images(tmp_path: Path) -> None:
    image = tmp_path / "reference.png"
    image.write_bytes(b"png")
    command = BATCH.codex_command(
        "codex", "gpt-5.6-terra", "medium", tmp_path, [image],
        tmp_path / "audit.jsonl", tmp_path / "final.txt", "MODEL THIS",
    )
    assert command[-1] == "MODEL THIS"
    assert command.index("--image") < command.index("--json")
    assert "--approve-for-me" in command
    assert "--sandbox" not in command


def test_sample_inputs_do_not_duplicate_ledger_defaults(tmp_path: Path) -> None:
    (tmp_path / "task_desc.json").write_text("{}", encoding="utf-8")
    input_dir = tmp_path / "input_files"
    input_dir.mkdir()
    reference = input_dir / "reference.png"
    reference.write_bytes(b"png")
    assert BATCH.sample_inputs(tmp_path) == [tmp_path / "task_desc.json", reference]


def test_prepare_job_seals_evaluator_only_assets(tmp_path: Path) -> None:
    sample = tmp_path / "sample"
    sample.mkdir()
    (sample / "task_desc.json").write_text("{}", encoding="utf-8")
    (sample / "rubrics.json").write_text("{}", encoding="utf-8")
    (sample / "metadata.json").write_text("{}", encoding="utf-8")
    (sample / "input_files").mkdir()
    image = sample / "input_files/reference.png"
    image.write_bytes(b"png")
    (sample / "output_files").mkdir()
    (sample / "output_files/reference.dwg").write_bytes(b"dwg")

    copied_images = BATCH.prepare_job(sample, tmp_path / "job")

    assert copied_images == [tmp_path / "job/input_files/reference.png"]
    assert not (tmp_path / "job/rubrics.json").exists()
    assert not (tmp_path / "job/metadata.json").exists()
    assert not (tmp_path / "job/output_files").exists()


def test_prompt_documents_mcp_timeout_units(tmp_path: Path) -> None:
    prompt = BATCH.prompt_for("sample", "run", "a001", tmp_path / "candidate.dwg")
    assert "measured in seconds" in prompt
    assert "between 0 and 1800" in prompt
    assert "autocad_core_start" in prompt
    assert "isolated" in prompt
    assert "candidate.geometry.dwg" in prompt
    assert "candidate.annotated.dwg" in prompt


def test_codex_command_uses_short_timeout_for_async_mcp_tools(tmp_path: Path) -> None:
    command = BATCH.codex_command(
        "codex", "gpt-5.6-terra", "medium", tmp_path, [],
        tmp_path / "audit.jsonl", tmp_path / "final.txt", "MODEL THIS",
    )
    assert "mcp_servers.autocad.tool_timeout_sec=60" in command
    assert any("AUTOCAD_MCP_BASE_SERVER" in item for item in command)


def test_core_console_prompt_does_not_require_desktop_reset(tmp_path: Path) -> None:
    prompt = BATCH.prompt_for("sample", "run", "a001", tmp_path / "candidate.dwg")
    assert "desktop autocad_send_command" in prompt
    assert "autocad_status confirms" not in prompt


def test_repair_prompt_requires_reflection_and_incremental_native_dimension_fix(tmp_path: Path) -> None:
    previous = tmp_path / "candidate.dwg"
    verdict = tmp_path / "verdict.json"
    repaired = tmp_path / "candidate.a002.dwg"
    reflection = tmp_path / "attempts" / "a002" / "reflection.json"
    diagnostic = tmp_path / "attempts" / "a001" / "diagnostic.json"

    prompt = BATCH.repair_prompt_for(
        "sample", "run", "a002", previous, verdict, repaired, reflection, diagnostic,
    )

    assert previous.as_posix() in prompt
    assert verdict.as_posix() in prompt
    assert repaired.as_posix() in prompt
    assert reflection.as_posix() in prompt
    assert diagnostic.as_posix() in prompt
    assert "Repair the existing drawing instead of recreating it" in prompt
    assert "native AutoCAD DIMENSION entities" in prompt
    assert "Do not modify the skill, verifier, dataset, batch runner" in prompt


def test_activate_proposal_routes_all_candidate_components(tmp_path: Path, monkeypatch) -> None:
    original_values = {
        name: getattr(BATCH, name)
        for name in ("PROMPT_ROOT", "SKILL_PATH", "MCP_SERVER_PATH", "VERIFIER_PATH", "SOURCE_PATHS")
    }
    for name, value in original_values.items():
        monkeypatch.setattr(BATCH, name, value)
    monkeypatch.setattr(BATCH, "EVAL_ROOT", tmp_path / "evals" / "cad-1000-hours")
    proposal = BATCH.EVAL_ROOT / "improvement" / "proposals" / "p1"
    workspace = proposal / "workspace"
    files = [
        "evals/cad-1000-hours/prompts/modeling.md",
        "evals/cad-1000-hours/prompts/repair.md",
        ".agents/skills/autocad-image-modeling/SKILL.md",
        "src/cad_evoloop/backends/autocad/audited.py",
        "src/cad_evoloop/verification/verify.py",
    ]
    for relative in files:
        path = workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("candidate", encoding="utf-8")
    (proposal / "manifest.json").write_text(
        __import__("json").dumps({
            "proposal_id": "p1",
            "status": "proposed",
            "files": [{"path": relative} for relative in files],
        }),
        encoding="utf-8",
    )

    BATCH.activate_proposal("p1")

    assert BATCH.PROMPT_ROOT == workspace / "evals/cad-1000-hours/prompts"
    assert BATCH.SKILL_PATH == workspace / ".agents/skills/autocad-image-modeling/SKILL.md"
    assert BATCH.MCP_SERVER_PATH == workspace / "src/cad_evoloop/backends/autocad/audited.py"
    assert BATCH.VERIFIER_PATH == workspace / "src/cad_evoloop/verification/verify.py"


def test_all_samples_dry_run_uses_stable_complete_sample_set(tmp_path: Path, monkeypatch, capsys) -> None:
    import json

    eval_root = tmp_path / "evals" / "cad-1000-hours"
    for name in ("sample-c", "sample-a", "sample-b"):
        sample = eval_root / "samples" / name
        sample.mkdir(parents=True)
        (sample / "task_desc.json").write_text("{}", encoding="utf-8")
        (sample / "rubrics.json").write_text("{}", encoding="utf-8")
    (eval_root / "manifest.json").write_text(json.dumps({
        "source": "test", "revision": "test", "license": None,
    }), encoding="utf-8")
    (eval_root / "improvement").mkdir()
    (eval_root / "improvement/split.json").write_text(json.dumps({
        "development": ["sample-a", "sample-b", "sample-c"], "holdout": [],
    }), encoding="utf-8")
    source = tmp_path / "source.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(BATCH, "EVAL_ROOT", eval_root)
    monkeypatch.setattr(BATCH, "SOURCE_PATHS", (source,))
    monkeypatch.setattr(BATCH.shutil, "which", lambda _: "codex")
    monkeypatch.setattr(sys, "argv", [
        "batch_codex.py", "--campaign", "dry", "--all-samples", "--dry-run",
    ])

    BATCH.main()

    plan = __import__("json").loads(capsys.readouterr().out)
    assert plan["samples"] == ["sample-a", "sample-b", "sample-c"]


def test_allocate_job_dir_preserves_orphan_and_increments_retry(tmp_path: Path) -> None:
    primary, retry = BATCH.allocate_job_dir(tmp_path, "sample", "gpt-5.5")
    assert retry == 0
    primary.mkdir(parents=True)
    second, retry = BATCH.allocate_job_dir(tmp_path, "sample", "gpt-5.5")
    assert retry == 1
    assert second.name == "gpt-5-5.retry-001"
    second.mkdir()
    third, retry = BATCH.allocate_job_dir(tmp_path, "sample", "gpt-5.5")
    assert retry == 2
    assert third.name == "gpt-5-5.retry-002"


def test_only_stable_results_are_terminal() -> None:
    assert BATCH.is_terminal_result({"status": "passed"})
    assert BATCH.is_terminal_result({"status": "failed", "score": 25})
    assert BATCH.is_terminal_result({"status": "evaluation-incomplete", "score": 100})
    assert not BATCH.is_terminal_result({"status": "harness-error"})
    assert not BATCH.is_terminal_result({"status": "failed", "interrupted": True})
    assert not BATCH.is_terminal_result({"status": "failed", "timed_out": True})
    assert not BATCH.is_terminal_result({"status": "failed", "return_code": 1})


def test_adaptive_pass_requires_minimum_coverage() -> None:
    assert BATCH.below_minimum_coverage({"passed": True, "coverage": 35.48}, 80.0)
    assert not BATCH.below_minimum_coverage({"passed": True, "coverage": 82.35}, 80.0)
    assert not BATCH.below_minimum_coverage({"passed": False, "coverage": 100.0}, 80.0)


def test_load_resumable_results_archives_transient_rows(tmp_path: Path) -> None:
    import json

    results_path = tmp_path / "results.json"
    stable = {"sample_id": "stable", "model": "m", "status": "failed", "return_code": 0}
    transient = {"sample_id": "retry", "model": "m", "status": "failed", "return_code": 1}
    results_path.write_text(json.dumps([stable, transient]), encoding="utf-8")

    assert BATCH.load_resumable_results(results_path) == [stable]
    assert json.loads(results_path.read_text(encoding="utf-8")) == [stable]
    archived = [json.loads(line) for line in (tmp_path / "retry-history.jsonl").read_text().splitlines()]
    assert archived == [transient]


def test_load_resumable_results_retries_verifier_infrastructure_failure(tmp_path: Path) -> None:
    import json

    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "verdict.json").write_text(json.dumps({
        "passed": False,
        "score": 0,
        "error": "Verifier failed with exit code 1",
    }), encoding="utf-8")
    result = {
        "sample_id": "retry", "model": "m", "status": "failed",
        "return_code": 0, "job_dir": str(job_dir),
    }
    results_path = tmp_path / "results.json"
    results_path.write_text(json.dumps([result]), encoding="utf-8")

    assert BATCH.load_resumable_results(results_path) == []
    assert json.loads(results_path.read_text(encoding="utf-8")) == []


def test_failed_verdict_labels_verifier_infrastructure_error(tmp_path: Path) -> None:
    import json

    verdict = tmp_path / "verdict.json"
    BATCH.failed_verdict(
        verdict,
        "Verifier failed with exit code 1",
        error_type="verifier-infrastructure",
    )

    value = json.loads(verdict.read_text(encoding="utf-8"))
    assert value["passed"] is False
    assert value["error_type"] == "verifier-infrastructure"
