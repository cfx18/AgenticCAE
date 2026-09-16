from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
import pytest

from cad_evoloop.ledger.ledger import write_json_atomic
from cad_evoloop.posttrain.bundle import seal_bundle
from cad_evoloop.posttrain.environment import Episode
from cad_evoloop.posttrain.smoke_mcp import PublicTools
from cad_evoloop.posttrain.verifier import grade_episode
from cad_evoloop.posttrain.web_discovery import allowed_url, parse_article, parse_index


@pytest.fixture
def smoke(tmp_path):
    task = tmp_path / "task"
    for section in ("public", "private", "reference", "tests", "provenance"):
        (task / section).mkdir(parents=True)
    write_json_atomic(task / "public/task.json", {"task_id": "smoke", "query": "Classify A", "input_images": ["drawing.png"]})
    Image.new("RGB", (60, 50), "white").save(task / "public/drawing.png")
    write_json_atomic(task / "private/verifier.json", {"kind": "json_fields", "expected": {"role": "hidden_edge"}})
    write_json_atomic(task / "reference/answer.json", {"role": "hidden_edge"})
    seal_bundle(task, {"task_id": "smoke", "task_type": "line_role", "ancestry": "test:one",
                      "license": "test", "split": "test"})
    episode = Episode.reset(task, tmp_path / "episode")
    return task, episode, PublicTools(episode.root)


@pytest.mark.parametrize("image", ["../private/verifier.json", "task.json", "C:/secret.png", "drawing.png/../task.json"])
def test_mcp_cannot_read_unlisted_inputs(smoke, image):
    with pytest.raises(ValueError, match="Only listed"):
        smoke[2].call("observe", {"image": image, "intent": "inspect"})


@pytest.mark.parametrize("tool", ["Bash", "Read", "execute", "grade", "fetch", "unknown"])
def test_mcp_has_no_arbitrary_execution_or_grading(smoke, tool):
    with pytest.raises(ValueError, match="Unknown"):
        smoke[2].call(tool, {})


def test_mcp_exact_image_receipt_and_final_only(smoke):
    task, episode, api = smoke
    result = api.call("observe", {"image": "drawing.png", "intent": "Inspect stroke", "crop": [1, 2, 20, 30]})
    receipt = json.loads(result["content"][0]["text"])
    assert receipt["dimensions"] == [19, 28]
    assert result["content"][1]["type"] == "image"
    api.call("conclude", {"observation_id": receipt["observation_id"], "finding": "Dashed stroke"})
    result = api.call("submit", {"answer": {"role": "hidden_edge"}})
    assert "passed" not in json.dumps(result)
    assert grade_episode(task, Episode(episode.root))["passed"]
    with pytest.raises(ValueError, match="already submitted"):
        api.call("submit", {"answer": {"role": "wrong"}})


@pytest.mark.parametrize("crop", [[], [1, 2], [True, 2, 20, 30], [0, 0, 61, 50]])
def test_mcp_crop_validation(smoke, crop):
    with pytest.raises(ValueError):
        smoke[2].call("observe", {"image": "drawing.png", "intent": "inspect", "crop": crop})


@pytest.mark.parametrize("url", ["http://xifengboke.com/", "https://xifengboke.com.evil/", "https://127.0.0.1/",
                                 "https://xifengboke.com:8772/", "https://u:p@xifengboke.com/"])
def test_discovery_host_boundary(url):
    assert not allowed_url(url)


def test_index_excludes_navigation_and_external_sources():
    rows = parse_index(b'<h3><a href="/post/20.html">CAD</a></h3><a href="/post/99.html">sidebar</a>'
                       b'<h3><a href="https://example.org/post/2.html">external</a></h3>',
                       "https://xifengboke.com/category-8_2.html")
    assert [row["post_id"] for row in rows] == ["20"]


def test_article_separates_solution_input_and_rights():
    html = '''<article class="single-post"><h1>Example</h1><div class="entry">
    <img src="/zb_users/upload/logo.ico"><h3>图纸</h3><img src="/zb_users/upload/input.png">
    <h3>建模步骤</h3><img src="/zb_users/upload/solution.png">
    <p>只有本站VIP用户才能直接查看隐藏内容</p>
    <a href="https://pan.quark.cn/s/test">点击下载</a></div></article>'''.encode()
    row = parse_article(html, "https://xifengboke.com/post/1.html")
    assert len(row["images"]) == 2
    assert [i["role_hint"] for i in row["images"]] == ["input_drawing_candidate", "solution_step_candidate"]
    assert row["source_file_access"] == "mixed_public_links_and_gated_sections"
    assert row["has_gated_sections"]
    assert row["download_links"][0]["status"] == "not_followed"
    assert not row["rights"]["training_eligible"]
    assert row["ground_truth_status"] == "no_cad_file_acquired_or_verified"


def test_unknown_article_layout_fails_closed():
    with pytest.raises(ValueError, match="structure"):
        parse_article(b'<html>login</html>', "https://xifengboke.com/post/1.html")


def test_gated_article_without_public_links_stays_gated():
    html = '''<article class="single-post"><h1>Example</h1><div class="entry">
    <p>只有本站VIP用户才能直接查看隐藏内容</p></div></article>'''.encode()
    row = parse_article(html, "https://xifengboke.com/post/1.html")
    assert row["source_file_access"] == "vip_or_login_required"
