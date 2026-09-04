from __future__ import annotations

import json
from pathlib import Path

import pytest

from cad_evoloop.evaluation import gt_trajectory


SOURCE = """\
import cadquery as cq
wp0 = cq.Workplane(cq.Plane(cq.Vector(0, 0, 0), cq.Vector(0, 1, 0), cq.Vector(1, 0, 0)))
loop0 = wp0.moveTo(0, 0).lineTo(2, 0).lineTo(2, 1).lineTo(0, 1).close()
solid0 = wp0.add(loop0).extrude(0.5, both=True)
solid = solid0
wp1 = cq.Workplane(cq.Plane(cq.Vector(0, 1, 0), cq.Vector(0, 1, 0), cq.Vector(1, 0, 0)))
loop1 = wp1.circle(0.25)
solid1 = wp1.add(loop1).extrude(1.0)
solid = solid.cut(solid1)
"""


def _inside_workspace(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(gt_trajectory, "project_root", lambda: tmp_path)
    return tmp_path


def test_static_extraction_builds_feature_dag_without_executing_source(
    tmp_path, monkeypatch,
) -> None:
    root = _inside_workspace(tmp_path, monkeypatch)
    marker = root / "must-not-exist"
    source = root / "ground_truth.py"
    source.write_text(SOURCE + f"\nopen({str(marker)!r}, 'w').write('bad')\n", encoding="utf-8")

    trajectory = gt_trajectory.extract_gt_feature_trajectory(source, sample_id="ortho2cad:test")

    assert not marker.exists()
    assert trajectory["extractor"] == "static-python-ast-no-execution"
    assert [node["operation"] for node in trajectory["feature_dag"]["nodes"]] == [
        "extrude", "extrude", "cut",
    ]
    assert trajectory["feature_dag"]["nodes"][-1]["parents"] == ["f001", "f002"]
    assert [row["after_node"] for row in trajectory["checkpoints"]] == ["f001", "b001"]


def test_oracle_levels_do_not_leak_source_or_order_into_perception(tmp_path, monkeypatch) -> None:
    root = _inside_workspace(tmp_path, monkeypatch)
    source = root / "ground_truth.py"
    source.write_text(SOURCE, encoding="utf-8")
    trajectory = gt_trajectory.extract_gt_feature_trajectory(source, sample_id="ortho2cad:test")

    perception = gt_trajectory.oracle_packet(trajectory, "perception")
    plan = gt_trajectory.oracle_packet(trajectory, "plan")
    serialized = json.dumps(perception)

    assert "unordered_exact_features" in perception
    assert "ordered_stages" not in perception
    assert "ground_truth.py" not in serialized
    assert "loop0" not in serialized
    assert "wp0" not in serialized
    assert [stage["operation"] for stage in plan["ordered_stages"]] == [
        "extrude", "extrude", "cut",
    ]


@pytest.mark.parametrize(
    ("conditions", "expected"),
    [
        ({"normal": {"passed": False}}, None),
        ({
            "normal": {"passed": False}, "perception": {"passed": True},
            "plan": {"passed": True}, "executor": {"passed": True},
        }, "agent_perception_or_feedback_design"),
        ({
            "normal": {"passed": False}, "perception": {"passed": False},
            "plan": {"passed": True}, "executor": {"passed": True},
        }, "planning_policy"),
        ({
            "normal": {"passed": False}, "perception": {"passed": False},
            "plan": {"passed": False}, "executor": {"passed": True},
        }, "model_tool_use_or_action_translation"),
        ({
            "normal": {"passed": False}, "perception": {"passed": False},
            "plan": {"passed": False}, "executor": {"passed": False},
        }, "executor_or_cad_interface"),
    ],
)
def test_attribution_ladder_requires_counterfactuals(conditions, expected) -> None:
    complete = {name: conditions.get(name) for name in ("normal", "perception", "plan", "executor")}
    result = gt_trajectory.infer_failure_attribution(
        complete, {"passed": True},
    )
    assert result["primary_layer"] == expected
    assert result["status"] == ("not_identified" if expected is None else result["status"])


def test_load_oracle_context_rejects_digest_changes(tmp_path, monkeypatch) -> None:
    root = _inside_workspace(tmp_path, monkeypatch)
    value = {
        "schema_version": "1.0",
        "protocol": gt_trajectory.ORACLE_PROTOCOL,
        "sample_ids": [],
        "sample_count": 0,
        "samples": {},
    }
    value["oracle_manifest_sha256"] = gt_trajectory._canonical_hash(
        value, "oracle_manifest_sha256",
    )
    path = root / "oracle.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    gt_trajectory.load_oracle_context(path)

    value["sample_count"] = 1
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="sample count"):
        gt_trajectory.load_oracle_context(path)


def test_unavailable_executor_is_a_missing_counterfactual() -> None:
    result = gt_trajectory.infer_failure_attribution(
        {
            "normal": {"passed": False},
            "perception": {"passed": False},
            "plan": {"passed": False},
            "executor": {"passed": None, "status": "unavailable"},
        },
        {"passed": True},
    )

    assert result["status"] == "not_identified"
    assert result["missing_conditions"] == ["executor"]


def test_experimental_controls_reject_model_and_gt_hash_mismatch() -> None:
    trajectory = {
        "source": {"sha256": "source"},
        "ground_truth_step": {"sha256": "step"},
    }
    result = gt_trajectory._check_experimental_controls(
        {
            "normal": {"model": "sol", "reasoning_effort": "medium", "agent_loop_protocol": "v3"},
            "perception": {"model": "other", "reasoning_effort": "medium", "agent_loop_protocol": "v3"},
            "plan": None,
        },
        {"source_sha256": "wrong", "ground_truth_sha256": "step"},
        trajectory,
    )

    assert result["valid"] is False
    assert {(row["condition"], row["field"]) for row in result["mismatches"]} == {
        ("perception", "model"), ("executor", "source_sha256"),
    }


def test_stage_oracle_context_binds_sample_and_embeds_prompt(tmp_path, monkeypatch) -> None:
    from cad_evoloop.evaluation import geometry_campaign

    root = _inside_workspace(tmp_path, monkeypatch)
    monkeypatch.setattr(geometry_campaign, "project_root", lambda: root)
    job = root / "job"
    job.mkdir()
    (job / "task.json").write_text("{}", encoding="utf-8")
    packet = {
        "schema_version": "1.0",
        "protocol": gt_trajectory.ORACLE_PROTOCOL,
        "sample_id": "ortho2cad:test",
        "oracle_level": "plan",
        "ordered_stages": [],
    }
    packet["oracle_packet_sha256"] = gt_trajectory._canonical_hash(
        packet, "oracle_packet_sha256",
    )
    source = root / "oracle.json"
    source.write_text(json.dumps(packet), encoding="utf-8")

    staged = geometry_campaign.stage_oracle_context(source, "ortho2cad:test", job)
    template = root / "prompt.md"
    template.write_text("sample $sample_id $candidate $skill_path", encoding="utf-8")
    prompt = geometry_campaign._prompt(
        template,
        sample_id="ortho2cad:test", run_id="r", attempt_id="a001",
        candidate=job / "candidate.dwg", oracle_context=staged,
    )

    assert "EVALUATOR ORACLE INTERVENTION" in prompt
    assert '"oracle_level": "plan"' in prompt
    assert json.loads((job / "task.json").read_text())["oracle_context"]["level"] == "plan"
