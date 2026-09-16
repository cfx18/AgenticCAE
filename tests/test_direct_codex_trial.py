from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


@pytest.fixture
def trial():
    path = Path(__file__).resolve().parents[1] / "evals/geometry-benchmarks/scripts/direct_codex_trial.py"
    spec = importlib.util.spec_from_file_location("direct_codex_trial", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_direct_prompt_has_no_forced_ir_or_score_loop(trial, tmp_path):
    prompt = trial.direct_prompt(tmp_path, "fixture:1", "trial-1", tmp_path / "candidate.dwg")
    assert "no externally scheduled repair turn" in prompt
    assert "no\nground-truth score tool" in prompt
    assert "Do not stop merely because the first construction succeeds" in prompt
    assert "Do not read parent directories" in prompt
    assert "candidate.dwg" in prompt


@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-6-astra"])
def test_command_preserves_requested_model_and_effort(trial, tmp_path, model):
    command = trial.codex_command(
        "codex.exe", model, "ultra", tmp_path, [tmp_path / "input.png"],
        "fixture", tmp_path / "audit.jsonl", tmp_path / "final.txt",
    )
    assert command[command.index("--model") + 1] == model
    assert 'model_reasoning_effort="ultra"' in command
    assert "--approve-for-me" in command
    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    assert "resume" not in command
    assert "--output-schema" not in command


def test_prepare_stages_only_visible_source_and_refuses_overwrite(trial, monkeypatch, tmp_path):
    source = tmp_path / ".local/datasets/evocad/materialized/geometry-50-v1"
    source.mkdir(parents=True)
    (source / "input.png").write_bytes(b"source-image")
    (source / "secret.step").write_bytes(b"ground-truth")
    (source / "manifest.json").write_text(json.dumps({
        "schema_version": "1.0", "samples": [{
            "sample_id": "omnimech:2", "dataset": "omnimech", "task": "Build fixture",
            "input_images": ["input.png"], "ground_truth_step": "secret.step",
        }],
    }), encoding="utf-8")
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"mock")
    monkeypatch.setattr(trial, "project_root", lambda: tmp_path)
    monkeypatch.setattr(trial.subprocess, "check_output", lambda *a, **k: "mock-codex-version")
    monkeypatch.setattr(sys, "argv", ["trial", "--campaign", "fixture-run", "--prepare-only",
                                      "--executable", str(executable)])
    trial.main()
    campaign = tmp_path / "evals/geometry-benchmarks/batch/fixture-run"
    config = json.loads((campaign / "trial-config.json").read_text())
    assert config["state"] == "prepared"
    assert config["effort"] == "ultra"
    assert config["gt_feedback_during_run"] is False
    assert len(config["input_sha256"]) == 1
    assert not list(campaign.rglob("*.step"))
    assert not list(campaign.rglob("codex-events.jsonl"))
    with pytest.raises(FileExistsError):
        trial.main()
    monkeypatch.setattr(sys, "argv", ["trial", "--campaign", "fixture-run", "--execute-prepared",
                                      "--effort", "medium", "--executable", str(executable)])
    with pytest.raises(ValueError, match="configuration mismatch"):
        trial.main()
    monkeypatch.setattr(sys, "argv", ["trial", "--campaign", "fixture-https", "--prepare-only",
                                      "--transport", "https", "--executable", str(executable)])
    trial.main()
    https_campaign = campaign.with_name("fixture-https")
    command_path = https_campaign / "omnimech-2/gpt-5-6-sol/attempts/a001/command.json"
    command = json.loads(command_path.read_text())["argv"]
    assert 'model_provider="evocad_openai_https"' in command
    provider = next(arg for arg in command if arg.startswith("model_providers.evocad_openai_https="))
    assert "supports_websockets=false" in provider
    assert "requires_openai_auth=true" in provider
    assert "https://chatgpt.com/backend-api/codex" in provider
    assert command[command.index("--model") + 1] == "gpt-5.6-sol"
    assert 'model_reasoning_effort="ultra"' in command
