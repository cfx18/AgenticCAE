import json

from PIL import Image
import pytest

from cad_evoloop.ledger.ledger import sha256_file, write_json_atomic
from cad_evoloop.posttrain import drawing_qa, spot_check
from cad_evoloop.posttrain.bundle import validate_bundle
from cad_evoloop.posttrain.environment import Episode
from cad_evoloop.posttrain.smoke_mcp import PublicTools
from cad_evoloop.posttrain.verifier import grade_episode


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(drawing_qa, "ROOT", tmp_path)
    source = tmp_path / "drawing.png"
    Image.new("RGB", (500, 300), "white").save(source)
    value = {"task_id": "probe-01", "source_id": "sample-01", "source": str(source),
             "source_sha256": sha256_file(source), "bbox": [100, 100, 200, 200],
             "query": "What does the boxed line mean?", "selection_note": "Private target interpretation"}
    path = tmp_path / "probe.json"
    write_json_atomic(path, value)
    return path, tmp_path / "built"


def test_probe_preserves_unknown_ground_truth_and_public_only_input(config):
    path, output = config
    assert spot_check.build(path, output)["eligible"] == 1
    task = output / "tasks/probe-01"
    assert validate_bundle(task)["label_status"] == "unlabeled_probe"
    annotation = json.loads((task / "private/annotation.json").read_text(encoding="utf-8"))
    assert annotation["author_model"] is None and annotation["blind_audit"] is None
    episode = Episode.reset(task, output / "episode")
    assert {p.name for p in (episode.root / "input").iterdir()} == {"task.json", "drawing-boxed.png"}
    assert "Private target interpretation" not in (episode.root / "input/task.json").read_text()
    PublicTools(episode.root).call("submit", {"answer": {"answer": "An unverified answer"}})
    verdict = grade_episode(task, episode)
    assert verdict["passed"] is None and verdict["score"] is None
    assert verdict["checks"] == {"valid_answer_submission": True}
    assert verdict["human_review_required"]
    with pytest.raises(FileExistsError):
        spot_check.build(path, output)


@pytest.mark.parametrize("override", [{"bbox": [0, 0, 1001, 500]}, {"bbox": [200, 100, 100, 200]},
                                     {"task_id": "../escape"}, {"query": ""}, {"source_sha256": "wrong"}])
def test_probe_rejects_invalid_config_before_packaging(config, override):
    path, output = config
    value = json.loads(path.read_text())
    write_json_atomic(path, {**value, **override})
    with pytest.raises(ValueError):
        spot_check.build(path, output)
    assert not output.exists()
