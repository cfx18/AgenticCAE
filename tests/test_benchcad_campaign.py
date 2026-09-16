from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from PIL import Image

from cad_evoloop.evaluation.benchcad_campaign import _action_prompt, image_verdict
from cad_evoloop.evaluation.benchcad_dataset import select_family_diverse
from cad_evoloop.evaluation.benchcad_report import summarize_checkpoint_scores


def test_image_verdict_identical_teal_shape(tmp_path: Path) -> None:
    image = Image.new("RGB", (12, 12), "white")
    for x in range(3, 9):
        for y in range(2, 10):
            image.putpixel((x, y), (77, 137, 135))
    target = tmp_path / "target.png"
    candidate = tmp_path / "candidate.png"
    overlay = tmp_path / "overlay.png"
    image.save(target)
    image.save(candidate)
    result = image_verdict(target, candidate, overlay)
    assert result["silhouette_iou"] == 1.0
    assert result["gt_geometry_used"] is False
    assert overlay.is_file()


def test_image_verdict_penalizes_missing_geometry(tmp_path: Path) -> None:
    target_image = Image.new("RGB", (8, 8), (77, 137, 135))
    candidate_image = Image.new("RGB", (8, 8), "white")
    target = tmp_path / "target.png"
    candidate = tmp_path / "candidate.png"
    target_image.save(target)
    candidate_image.save(candidate)
    result = image_verdict(target, candidate, tmp_path / "overlay.png")
    assert result["silhouette_iou"] == 0.0
    assert result["missing_fraction"] == 1.0


def test_image_verdict_supports_olive_corpus_palette(tmp_path: Path) -> None:
    image = Image.new("RGB", (10, 10), "white")
    for x in range(2, 8):
        for y in range(2, 8):
            image.putpixel((x, y), (180, 180, 96))
    target = tmp_path / "target.png"
    image.save(target)
    result = image_verdict(target, target, tmp_path / "overlay.png")
    assert result["target_pixels"] == 36
    assert result["silhouette_iou"] == 1.0


def test_family_selection_is_deterministic_and_unique() -> None:
    rows = [
        {"family": family, "stem": f"{family}-{index}"}
        for family in ("a", "b", "c") for index in range(3)
    ]
    first = select_family_diverse(rows, 2, "fixed")
    second = select_family_diverse(list(reversed(rows)), 2, "fixed")
    assert first == second
    assert len({row["family"] for row in first}) == 2


def test_checkpoint_summary_attributes_loop_uplift_and_regret() -> None:
    cases = [
        {
            "difficulty": "easy", "iterations": 2,
            "first_iou": 0.4, "final_iou": 0.8, "best_iou": 0.9,
            "final_image_iou": 0.75,
        },
        {
            "difficulty": "hard", "iterations": 3,
            "first_iou": 0.7, "final_iou": 0.6, "best_iou": 0.7,
            "final_image_iou": 0.65,
        },
    ]
    result = summarize_checkpoint_scores(cases, max_iterations=3)
    assert result["official_iou"]["mean"] == 0.7
    assert result["loop_uplift"]["improved"] == 1
    assert result["loop_uplift"]["regressed"] == 1
    assert result["selection_regret"]["mean"] == 0.1
    assert result["execution"]["safety_ceiling_reached"] == 1


def test_baseline_action_prompt_does_not_claim_an_ir() -> None:
    prompt = _action_prompt(None, 1, None)
    assert "No structured reconstruction record is provided" in prompt
    assert "reconstruction-ir.json" not in prompt


def test_forced_ir_action_prompt_exposes_hypothesis() -> None:
    prompt = _action_prompt({"features": [{"operation": "cut"}]}, 1, None)
    assert "reconstruction-ir.json" in prompt
    assert "Treat it as a hypothesis" in prompt
    assert '"operation": "cut"' in prompt


@pytest.mark.parametrize("mode", ["baseline", "forced_ir", "specialist_ir"])
def test_campaign_conversation_and_source_visibility(tmp_path, monkeypatch, mode):
    import cad_evoloop.evaluation.benchcad_campaign as campaign
    from cad_evoloop.agent.models.base import ConversationHandle, ModelTurn

    upstream = tmp_path / "upstream"
    (upstream / ".venv/Scripts").mkdir(parents=True)
    (upstream / ".venv/Scripts/python.exe").touch()
    data = tmp_path / "data"
    (data / "steps").mkdir(parents=True)
    Image.new("RGB", (20, 20), (77, 137, 135)).save(data / "steps/part.png")
    (data / "records.jsonl").write_text(json.dumps({
        "record_id": "part", "family": "plate", "step_path": "gt.step", "code_path": "gt.py",
    }))
    requests = []
    builders = []

    class Provider:
        name = "fake"

        def __init__(self, config):
            self.config = config

        def start(self, request):
            return self.continue_(ConversationHandle(self.name, "fresh-modeling"), request)

        def continue_(self, handle, request):
            requests.append((handle.conversation_id, request))
            if request.metadata["stage"] == "action":
                (self.config.cwd / "candidate.py").write_text("result = object()")
            return handle, ModelTurn(content="ok", finish_reason="stop", structured_output={
                "decision": "stop", "reason": "done", "next_action": "", "confidence": 1,
            })

    def build(provider, **kwargs):
        builders.append((provider, kwargs))
        return SimpleNamespace(value={"features": [{"operation": "extrude"}]}, conversation_id="perception")

    def bridge(python, args, timeout):
        if "execute" in args:
            Path(args[args.index("--step") + 1]).write_text("STEP")
            Image.new("RGB", (20, 20), (77, 137, 135)).save(args[args.index("--render") + 1])
            return {"ok": True}
        return {"ok": True, "iou": 1.0, "composite": 1.0}

    monkeypatch.setattr(campaign, "CodexCLIProvider", Provider)
    monkeypatch.setattr(campaign, "build_reconstruction_ir", build)
    monkeypatch.setattr(campaign, "_run_bridge", bridge)
    result = campaign.run_benchcad_campaign(campaign.BenchCADConfig(
        upstream=upstream, data_dir=data, output=tmp_path / "out", campaign=mode,
        max_iterations=1, reconstruction_mode=mode,
    ))
    workspace = tmp_path / "out" / mode / "part/agent_workspace"
    assert result["scored"] == 1
    assert len(builders) == (0 if mode == "baseline" else 1)
    assert requests[0][0] == ("perception" if mode == "forced_ir" else "fresh-modeling")
    if mode == "specialist_ir":
        assert all(not request.images for _, request in requests)
        assert not (workspace / "target.png").exists()
        assert not (workspace / "view_0.png").exists()
        assert not (workspace / "difference.png").exists()
        assert (workspace / "reconstruction-ir.json").exists()
        assert builders[0][0].config.cwd != workspace
        assert "Source images are withheld" in requests[0][1].instructions
    else:
        assert requests[0][1].images == [workspace / "target.png"]
        assert (workspace / "difference.png").exists()


def test_supervisor_archives_only_interrupted_work(tmp_path, monkeypatch):
    import cad_evoloop.evaluation.benchcad_supervisor as supervisor

    monkeypatch.setattr(supervisor, "project_root", lambda: tmp_path)
    campaign_dir = tmp_path / "campaign"
    pending = campaign_dir / "pending/agent_workspace"
    pending.mkdir(parents=True)
    (pending / "candidate.py").write_text("partial")
    done = campaign_dir / "done"
    done.mkdir()
    (done / "result.json").write_text(json.dumps({"record_id": "done", "status": "scored"}))
    (campaign_dir / "_control").mkdir()
    archived = supervisor.archive_incomplete(campaign_dir)
    assert len(archived) == 1
    assert (campaign_dir / archived[0] / "agent_workspace/candidate.py").read_text() == "partial"
    assert not pending.exists()
    assert (done / "result.json").is_file()
    assert supervisor.progress(campaign_dir)["completed"] == 1
    assert supervisor.archive_incomplete(campaign_dir) == []
    with pytest.raises(ValueError):
        supervisor.archive_incomplete(tmp_path.parent)
