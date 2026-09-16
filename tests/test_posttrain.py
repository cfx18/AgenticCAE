from __future__ import annotations

import io
import json
from pathlib import Path
import zipfile

from PIL import Image
import pytest

from cad_evoloop.agent.events import GENESIS_HASH, validate_event
from cad_evoloop.ledger.ledger import write_json_atomic
from cad_evoloop.posttrain.bundle import contained_file, export_public, seal_bundle, validate_bundle
from cad_evoloop.posttrain.environment import DockerExecutor, Episode, SandboxUnavailable
from cad_evoloop.posttrain.sources import RangeArchive, safe_member
from cad_evoloop.posttrain.verifier import check_answer, grade_episode, grade_files


@pytest.fixture
def task(tmp_path):
    root = tmp_path / "task"
    for section in ("public", "private", "reference", "tests", "provenance"):
        (root / section).mkdir(parents=True)
    write_json_atomic(root / "public/task.json", {"task_id": "test-task", "query": "Classify A"})
    Image.new("RGB", (80, 60), "white").save(root / "public/drawing.png")
    write_json_atomic(root / "private/verifier.json", {"kind": "json_fields", "expected": {"role": "hidden_edge"}})
    write_json_atomic(root / "reference/answer.json", {"role": "hidden_edge"})
    seal_bundle(root, {"task_id": "test-task", "task_type": "line_role", "ancestry": "source:one",
                       "license": "test-fixture", "split": "test"})
    return root


def test_public_reset_does_not_export_hidden_assets(task, tmp_path):
    episode = Episode.reset(task, tmp_path / "episode")
    assert sorted(p.name for p in (episode.root / "input").iterdir()) == ["drawing.png", "task.json"]
    assert "hidden_edge" not in (episode.root / "input/task.json").read_text()
    assert list((episode.root / "work").iterdir()) == []


def test_task_mutation_rejected(task, tmp_path):
    (task / "public/task.json").write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        export_public(task, tmp_path / "input")


def test_unlisted_task_file_rejected(task):
    (task / "public/gold.json").write_text("{}")
    with pytest.raises(ValueError, match="Unlisted"):
        validate_bundle(task)


@pytest.mark.parametrize("name", ["../secret", "/secret", "C:/secret", "a\\b", "private/../../secret", ""])
def test_escaping_paths_rejected(task, name):
    with pytest.raises(ValueError):
        contained_file(task, name)


def test_existing_episode_not_overwritten(task, tmp_path):
    Episode.reset(task, tmp_path / "episode")
    with pytest.raises(FileExistsError):
        Episode.reset(task, tmp_path / "episode")


def test_reset_repeats_input_hashes(task, tmp_path):
    first = Episode.reset(task, tmp_path / "a")
    second = Episode.reset(task, tmp_path / "b")
    assert first.state["public_inventory"] == second.state["public_inventory"]
    assert first.state["episode_id"] != second.state["episode_id"]


def test_observation_intent_image_and_conclusion_bound(task, tmp_path):
    episode = Episode.reset(task, tmp_path / "episode")
    observation = episode.observe("drawing.png", intent="Inspect A", crop=(5, 6, 35, 46))
    assert observation["dimensions"] == [30, 40]
    with Image.open(episode.root / observation["image"]) as image:
        assert image.size == (30, 40)
    episode.conclude_observation(observation["observation_id"], "The stroke is dashed.")
    previous = GENESIS_HASH
    events = [json.loads(line) for line in (episode.root / "events.jsonl").read_text().splitlines()]
    for index, event in enumerate(events, 1):
        validate_event(event, project_id=episode.state["episode_id"], expected_sequence=index, expected_previous_hash=previous)
        previous = event["event_hash"]
    assert events[-1]["payload"]["observation_id"] == observation["observation_id"]


@pytest.mark.parametrize("crop", [(-1, 0, 10, 10), (0, 0, 90, 10), (4, 4, 2, 2)])
def test_invalid_crop_rejected(task, tmp_path, crop):
    episode = Episode.reset(task, tmp_path / "episode")
    with pytest.raises(ValueError, match="Crop"):
        episode.observe("drawing.png", intent="test", crop=crop)


def test_fabricated_observation_reference_rejected(task, tmp_path):
    episode = Episode.reset(task, tmp_path / "episode")
    with pytest.raises(ValueError):
        episode.conclude_observation("not-observed", "It is good")


def test_event_tampering_rejected(task, tmp_path):
    episode = Episode.reset(task, tmp_path / "episode")
    path = episode.root / "events.jsonl"
    path.write_text(path.read_text().replace('"actor": "environment"', '"actor": "changed"'))
    with pytest.raises(ValueError, match="digest"):
        episode.record("new", {})


def test_grade_only_submitted_snapshot_not_later_work(task, tmp_path):
    episode = Episode.reset(task, tmp_path / "episode")
    path = episode.root / "work/answer.json"
    write_json_atomic(path, {"role": "hidden_edge"})
    episode.submit(["answer.json"])
    write_json_atomic(path, {"role": "visible_edge"})
    assert grade_episode(task, episode)["passed"] is True
    with pytest.raises(ValueError, match="already submitted"):
        episode.submit(["answer.json"])


def test_grade_requires_explicit_submission(task, tmp_path):
    episode = Episode.reset(task, tmp_path / "episode")
    with pytest.raises(ValueError, match="explicit final"):
        grade_episode(task, episode)


def test_snapshot_mutation_rejected(task, tmp_path):
    episode = Episode.reset(task, tmp_path / "episode")
    write_json_atomic(episode.root / "work/answer.json", {"role": "hidden_edge"})
    submission = episode.submit(["answer.json"])
    (episode.root / submission["files"][0]["snapshot"]).write_text("{}")
    with pytest.raises(ValueError, match="snapshot changed"):
        grade_episode(task, episode)


def test_public_input_mutation_rejected_at_grade(task, tmp_path):
    episode = Episode.reset(task, tmp_path / "episode")
    write_json_atomic(episode.root / "work/answer.json", {"role": "hidden_edge"})
    episode.submit(["answer.json"])
    (episode.root / "input/task.json").write_text("{}")
    with pytest.raises(ValueError, match="input changed"):
        grade_episode(task, episode)


@pytest.mark.parametrize("candidate", [True, float("nan"), float("inf"), "25", None, 26])
def test_numeric_gold_rejects_nonfinite_bool_and_wrong_type(candidate):
    assert check_answer({"diameter": candidate}, {"diameter": 25.0}, .001) == {"diameter": False}


def test_json_arrays_are_not_answers(task, tmp_path):
    path = tmp_path / "answer.json"
    path.write_text("[]")
    assert grade_files(task, answer=path)["passed"] is False


def test_bool_gold_does_not_accept_one():
    assert not check_answer({"sufficient": 1}, {"sufficient": True}, .001)["sufficient"]


def test_altered_verifier_rejected(task):
    (task / "private/verifier.json").write_text('{"kind":"always_pass"}')
    with pytest.raises(ValueError, match="changed"):
        grade_files(task, answer=task / "reference/answer.json")


def test_docker_is_fail_closed_without_local_runtime(monkeypatch, tmp_path):
    from cad_evoloop.posttrain import environment
    monkeypatch.setattr(environment.shutil, "which", lambda name: None)
    executor = DockerExecutor("cad@sha256:" + "a"*64)
    with pytest.raises(SandboxUnavailable):
        executor.execute(tmp_path, tmp_path, ["python", "model.py"], 30)


def test_container_image_must_be_digest_pinned():
    with pytest.raises(ValueError, match="digest"):
        DockerExecutor("cad:latest")


@pytest.mark.parametrize("name", ["../outside", "/outside", "C:/outside", "a\\b"])
def test_archive_member_traversal_rejected(name):
    with zipfile.ZipFile(io.BytesIO(), "w") as archive:
        with pytest.raises(ValueError, match="Unsafe"):
            safe_member(archive, name)


def test_archive_budget_rejects_before_network():
    archive = RangeArchive.__new__(RangeArchive)
    archive.transferred = 10
    archive.budget = 15
    with pytest.raises(ValueError, match="budget"):
        archive._fetch(0, 10)


@pytest.mark.parametrize(("status", "content_range", "etag", "body"), [
    (200, "bytes 0-2/10", '"v1"', b"abc"),
    (206, "bytes 1-3/10", '"v1"', b"abc"),
    (206, "bytes 0-2/10", '"changed"', b"abc"),
    (206, "bytes 0-2/10", '"v1"', b"ab"),
    (206, "bytes 0-2/10", '"v1"', b"abcd"),
])
def test_range_archive_rejects_ignored_changed_or_truncated_ranges(status, content_range, etag, body):
    from types import SimpleNamespace
    class Response:
        status_code = status
        headers = {"Content-Range": content_range, "ETag": etag}
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, size): yield body
    archive = RangeArchive.__new__(RangeArchive)
    archive.url = "https://example.test/archive.zip"
    archive.transferred, archive.budget, archive.etag, archive.length = 0, 100, '"v1"', 10
    archive.session = SimpleNamespace(get=lambda *args, **kwargs: Response(), close=lambda: None)
    with pytest.raises(ValueError):
        archive._fetch(0, 2)


def test_docker_action_has_only_public_mounts_and_no_network(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from cad_evoloop.posttrain import environment
    calls = []
    monkeypatch.setattr(environment.shutil, "which", lambda name: "/usr/bin/docker")
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=b"done", stderr=b"")
    monkeypatch.setattr(environment.subprocess, "run", run)
    result = DockerExecutor("cad@sha256:" + "a"*64).execute(tmp_path / "input", tmp_path / "work", ["python", "program.py"], 30)
    command = calls[0]
    assert result["status"] == "completed"
    assert "--network=none" in command and "--read-only" in command and "--cap-drop=ALL" in command
    assert command.count("--mount") == 2
    assert str(tmp_path / "private") not in " ".join(command)
    assert calls[1][:3] == ["docker", "rm", "-f"]
    assert calls[1][3] == command[command.index("--name") + 1]


def test_geometric_controls():
    cq = pytest.importorskip("cadquery")
    from cad_evoloop.posttrain.geometry import shape_verdict
    target = cq.Workplane("XY").box(20, 30, 10, centered=False).val()
    assert shape_verdict(target, target)["passed"]
    assert not shape_verdict(target.translate((1,0,0)), target)["passed"]
    tiny_missing_hole = target.cut(cq.Solid.makeCylinder(.4, 10, (10,15,0)))
    assert not shape_verdict(tiny_missing_hole, target)["passed"]
    same_volume_wrong_shape = cq.Workplane("XY").box(30, 20, 10, centered=False).val()
    assert abs(same_volume_wrong_shape.Volume() - target.Volume()) < 1e-6
    assert not shape_verdict(same_volume_wrong_shape, target)["passed"]


def test_cylinder_inside_outside_not_inferred_from_smallest_radius():
    cq = pytest.importorskip("cadquery")
    from cad_evoloop.posttrain.geometry import cylinders
    shaft = cq.Solid.makeCylinder(4, 20).fuse(cq.Solid.makeCylinder(8, 2, (0,0,20)))
    assert all(not face["internal"] for face in cylinders(shaft))
    washer = cq.Solid.makeCylinder(8, 5).cut(cq.Solid.makeCylinder(4, 5))
    assert sorted((round(face["radius_mm"]), face["internal"]) for face in cylinders(washer)) == [(4, True), (8, False)]


def test_pilot_allocation_and_ancestry_limit():
    config = json.loads((Path(__file__).parents[1] / "evals/posttrain/pilot.json").read_text())
    from collections import Counter
    tasks = config["tasks"]
    assert len(tasks) == 20
    assert len({task["part"] for task in tasks}) >= 12
    assert max(Counter(task["part"] for task in tasks).values()) <= 3
    assert all(not task["part"].startswith("omnimech") for task in tasks)
