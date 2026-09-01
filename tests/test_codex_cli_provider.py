from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from cad_evoloop.agent.models import CodexCLIConfig, CodexCLIProvider, ModelRequest


def fake_codex_run(command, **kwargs):
    kwargs["stdout"].write(json.dumps({"type": "thread.started", "thread_id": "thread-123"}) + "\n")
    kwargs["stdout"].write(json.dumps({
        "type": "turn.completed",
        "usage": {"input_tokens": 12, "output_tokens": 4},
    }) + "\n")
    final = Path(command[command.index("--output-last-message") + 1])
    final.write_text('{"decision":"continue"}\n', encoding="utf-8")
    return SimpleNamespace(returncode=0)


def provider(tmp_path: Path, monkeypatch) -> CodexCLIProvider:
    monkeypatch.setattr("cad_evoloop.agent.models.codex_cli.subprocess.run", fake_codex_run)
    return CodexCLIProvider(CodexCLIConfig(
        cwd=tmp_path,
        artifact_root=tmp_path / "model-events",
        executable="codex-test",
        model="gpt-5.6-sol",
    ))


def test_codex_provider_records_a_canonical_turn(tmp_path: Path, monkeypatch) -> None:
    model = provider(tmp_path, monkeypatch)
    schema = {
        "type": "object",
        "properties": {"decision": {"type": "string"}},
        "required": ["decision"],
        "additionalProperties": False,
    }

    handle, turn = model.start(ModelRequest(
        instructions="Decide the next action",
        messages=[{"role": "user", "content": "Inspect verifier feedback"}],
        response_schema=schema,
        metadata={"work_unit_id": "geometry"},
    ))

    assert handle.conversation_id == "thread-123"
    assert turn.structured_output == {"decision": "continue"}
    assert turn.usage == {"input_tokens": 12, "output_tokens": 4}
    assert turn.finish_reason == "stop"
    artifact_dir = Path(turn.provider_metadata["artifacts"]["directory"])
    assert (artifact_dir / "command.json").is_file()
    assert (artifact_dir / "events.jsonl").is_file()
    command = json.loads((artifact_dir / "command.json").read_text(encoding="utf-8"))
    assert command[command.index("--model") + 1] == "gpt-5.6-sol"
    assert "--output-schema" in command


def test_codex_provider_resumes_provider_thread_without_changing_domain_identity(
    tmp_path: Path, monkeypatch,
) -> None:
    model = provider(tmp_path, monkeypatch)
    handle, _ = model.start(ModelRequest(instructions="Start"))

    resumed, turn = model.continue_(handle, ModelRequest(instructions="Continue"))

    command_path = Path(turn.provider_metadata["artifacts"]["directory"]) / "command.json"
    command = json.loads(command_path.read_text(encoding="utf-8"))
    assert command[-3:] == ["resume", "thread-123", "Continue"]
    assert resumed.conversation_id == handle.conversation_id
    assert resumed.opaque_state != handle.opaque_state


def test_codex_provider_capabilities_reflect_tool_configuration(tmp_path: Path) -> None:
    without_tools = CodexCLIProvider(CodexCLIConfig(
        cwd=tmp_path, artifact_root=tmp_path / "a", executable="codex-test",
    ))
    with_tools = CodexCLIProvider(CodexCLIConfig(
        cwd=tmp_path, artifact_root=tmp_path / "b", executable="codex-test",
        config_overrides=('mcp_servers.autocad.command="python"',),
    ))

    assert without_tools.capabilities().tools is False
    assert with_tools.capabilities().tools is True
