from pathlib import Path
import json

import pytest
from jsonschema import ValidationError

from cad_evoloop.agent.models.kimi_geometry import (
    KimiGeometryTransport, decision_json, final_text, read_kimi_events,
)


def test_public_final_excludes_thinking_and_tool_messages(tmp_path):
    path = tmp_path / "events.jsonl"
    rows = [
        {"role": "assistant", "content": [{"type": "think", "think": "private"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "working"}], "tool_calls": [{}]},
        {"role": "tool", "content": "not a final"},
        {"role": "assistant", "content": [{"type": "text", "text": '{"decision":"stop"}'}]},
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    assert final_text(path) == '{"decision":"stop"}'
    assert read_kimi_events(path) == {"thread_id": None, "usage": {}, "errors": []}


def test_decision_requires_schema_without_synthesizing_fields():
    schema = {"type": "object", "required": ["decision"],
              "properties": {"decision": {"enum": ["stop", "continue"]}}}
    assert decision_json('```json\n{"decision":"stop"}\n```', schema)["decision"] == "stop"
    with pytest.raises(ValidationError):
        decision_json('{}', schema)
    with pytest.raises(json.JSONDecodeError):
        decision_json('Here is my answer: {"decision":"stop"}', schema)


def test_session_is_scoped_and_resumes_exact_identity(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "session_index.jsonl").write_text(json.dumps({
        "sessionId": "session-first", "workDir": str(tmp_path),
    }) + "\n", encoding="utf-8")
    assert KimiGeometryTransport._session(home, tmp_path, None) == "session-first"
    assert KimiGeometryTransport._session(home, tmp_path, "session-first") == "session-first"
    with pytest.raises(ValueError):
        KimiGeometryTransport._session(home, tmp_path, "session-other")


def test_large_prompt_is_staged_without_secret_in_request(tmp_path):
    adapter = object.__new__(KimiGeometryTransport)
    adapter.workspace = tmp_path
    adapter.invocation = ["node", "kimi.mjs"]
    adapter.environment = {"KIMI_MODEL_NAME": "kimi-k3", "KIMI_MODEL_THINKING_EFFORT": "max",
                           "KIMI_MODEL_API_KEY": "secret"}
    final = tmp_path / "final.txt"
    command = adapter.start_command("unused", "kimi-k3", "max", tmp_path, [], "x" * 60000,
                                    tmp_path / "audit.jsonl", final)
    assert sum(map(len, command)) < 1000
    request = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
    assert len(request["argv"][1]) == 60000
    assert "secret" not in json.dumps(request)
