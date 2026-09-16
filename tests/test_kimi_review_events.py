import json

from cad_evoloop.evaluation.geometry_review import _public_events


def test_kimi_review_preserves_public_text_and_tool_requests(tmp_path):
    path = tmp_path / "kimi-events.jsonl"
    records = [
        {"role": "assistant", "content": [
            {"type": "think", "think": "private content"},
            {"type": "text", "text": "Inspect the section view."},
        ], "tool_calls": [{"id": "image-1", "function": {
            "name": "ReadMediaFile", "arguments": '{"path":"input.png"}',
        }}]},
        {"role": "tool", "content": [{"type": "image_url", "image_url": {
            "url": "data:image/png;base64,unneeded",
        }}]},
        {"role": "assistant", "content": "Finished."},
    ]
    path.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")
    events = _public_events(path, "action")
    assert [event["type"] for event in events] == ["agent_message", "tool_call", "agent_message"]
    assert events[1]["arguments"] == {"path": "input.png"}
    assert events[1]["status"] == "requested"
    assert "private content" not in json.dumps(events)
    assert "data:image" not in json.dumps(events)


def test_kimi_review_keeps_malformed_tool_arguments(tmp_path):
    path = tmp_path / "kimi-events.jsonl"
    path.write_text(json.dumps({"role": "assistant", "tool_calls": [
        {"function": {"name": "Bash", "arguments": "unfinished {"}},
    ]}), encoding="utf-8")
    assert _public_events(path, "action")[0]["arguments"] == {"raw": "unfinished {"}
