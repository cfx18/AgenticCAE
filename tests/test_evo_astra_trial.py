import importlib.util
from pathlib import Path
from unittest.mock import patch

from cad_evoloop.evaluation import geometry_campaign


def test_https_trial_preserves_action_and_feedback_semantics(tmp_path):
    path = Path(__file__).resolve().parents[1] / "evals/geometry-benchmarks/scripts/evo_astra_omnimech2_trial.py"
    spec = importlib.util.spec_from_file_location("evo_astra_trial", path)
    trial = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trial)
    builder = geometry_campaign.build_codex_exec_command
    with patch.object(geometry_campaign, "build_codex_exec_command", trial.with_https(builder)):
        action = geometry_campaign.codex_command(
            "codex.exe", "gpt-6-astra", "ultra", tmp_path, [], "prompt",
            tmp_path / "audit.jsonl", tmp_path / "final.txt",
        )
        feedback = geometry_campaign.codex_resume_command(
            "codex.exe", "gpt-6-astra", "ultra", tmp_path, "same-thread", "feedback",
            tmp_path / "decision.txt", with_autocad=False, output_schema=tmp_path / "decision.schema.json",
        )
    assert geometry_campaign.build_codex_exec_command is builder
    for command in (action, feedback):
        assert command[command.index("--model") + 1] == "gpt-6-astra"
        assert 'model_reasoning_effort="ultra"' in command
        assert all(override in command for override in trial.HTTPS_OVERRIDES)
    assert feedback[-3:] == ["resume", "same-thread", "-"]
    assert "--output-schema" in feedback
    assert any("mcp_servers.autocad" in value for value in action)
