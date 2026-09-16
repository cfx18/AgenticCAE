import base64
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
import json
from pathlib import Path

from PIL import Image

path = Path(__file__).resolve().parents[1] / "evals/geometry-benchmarks/scripts/export_kimi_visual_trace.py"
spec = spec_from_file_location("kimi_trace", path)
module = module_from_spec(spec)
spec.loader.exec_module(module)


def image_url():
    stream = BytesIO()
    Image.new("RGB", (4, 3), "white").save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()


def test_exact_returns_nested_content_duplicates_and_no_private_reasoning():
    payload = json.dumps([{"type": "image_url", "imageUrl": {"url": image_url()}}])
    events = [
        (1, {"role": "assistant", "content": [{"type": "think", "think": "private text"},
             {"type": "text", "text": "Let me inspect the hole."}], "tool_calls": [
             {"id": "c1", "function": {"name": "ReadMediaFile", "arguments": '{"path":"input.png"}'}}]}),
        (2, {"role": "tool", "tool_call_id": "c1", "content": payload}),
        (3, {"role": "assistant", "content": [{"type": "text", "text": "The hole is labeled 6 mm. Let me check again."}],
             "tool_calls": [{"id": "c2", "function": {"name": "ReadMediaFile", "arguments": '{"path":"input.png"}'}}]}),
        (4, {"role": "tool", "tool_call_id": "c2", "content": payload}),
    ]
    assets = {}
    calls, operations, counts = module.extract(events, assets)
    assert len(assets) == 1
    assert calls[0]["images"][0]["width"] == 4
    assert calls[1]["same_pixels_as"] == [1]
    assert calls[1]["same_request_as"] == [1]
    assert calls[0]["found"]["observation_candidates"][0]["text"] == "The hole is labeled 6 mm."
    assert "private text" not in json.dumps(calls)
    assert counts == {"ReadMediaFile": 2}
    assert not operations


def test_missing_image_and_next_action_are_not_invented_observations():
    events = [(1, {"role": "assistant", "tool_calls": [
        {"id": "c1", "function": {"name": "ReadMediaFile", "arguments": '{"path":"missing.png"}'}}]}),
        (2, {"role": "tool", "tool_call_id": "c1", "content": "File missing"}),
        (3, {"role": "assistant", "content": [{"type": "text", "text": "Let me look again."}]}),
    ]
    calls, _, _ = module.extract(events, {})
    assert calls[0]["status"] == "no_image_returned"
    assert calls[0]["found"]["status"] == "not_recorded"
    assert calls[0]["response_text"] == ["File missing"]


def test_partial_tool_call_is_pending_and_parallel_context_is_explicit():
    calls, _, _ = module.extract([(1, {"role": "assistant", "tool_calls": [
        {"id": "c1", "function": {"name": "ReadMediaFile", "arguments": '{"path":"a.png"}'}}]})], {})
    assert calls[0]["status"] == "pending"
    assert "parallel" in calls[0]["found"]["attribution_note"]


def test_unrelated_tool_result_is_not_a_visual_finding():
    events = [(1, {"role": "assistant", "tool_calls": [
        {"id": "c1", "function": {"name": "ReadMediaFile", "arguments": '{"path":"a.png"}'}}]}),
        (2, {"role": "tool", "tool_call_id": "c1", "content": "image read"}),
        (3, {"role": "assistant", "tool_calls": [
            {"id": "c2", "function": {"name": "Read", "arguments": '{"path":"SKILL.md"}'}}]}),
        (4, {"role": "assistant", "content": [{"type": "text", "text": "The skill is minimal."}]}),
    ]
    calls, _, _ = module.extract(events, {})
    assert not calls[0]["found"]["observation_candidates"]
    assert calls[0]["found"]["public_statements"][0]["text"] == "The skill is minimal."


def test_non_image_operations_preserve_code_and_returns():
    events = [(1, {"role": "assistant", "tool_calls": [
        {"id": "c1", "function": {"name": "Write", "arguments": json.dumps({"path": "a.lsp", "content": "(command)"})}}]}),
        (2, {"role": "tool", "tool_call_id": "c1", "content": "File written"})]
    _, operations, _ = module.extract(events, {})
    assert operations[0]["arguments"]["content"] == "(command)"
    assert operations[0]["response_text"] == ["File written"]
    assert operations[0]["status"] == "returned"
