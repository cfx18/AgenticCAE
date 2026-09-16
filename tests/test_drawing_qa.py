import json

from PIL import Image
import pytest

from cad_evoloop.ledger.ledger import sha256_file, write_json_atomic
from cad_evoloop.posttrain import drawing_qa as qa
from cad_evoloop.posttrain.bundle import validate_bundle
from cad_evoloop.posttrain.environment import Episode
from cad_evoloop.posttrain.smoke_mcp import PublicTools
from cad_evoloop.posttrain.verifier import check_answer, grade_episode


def question():
    return {"question_id": "drawing-01", "source_id": "pdf-001", "task_type": "dimension_chain",
            "query": "Find L minus two equal a margins, in mm.", "answer_kind": "number", "options": [],
            "regions": [{"label": "A", "bbox": [100, 100, 600, 500]}],
            "expected_answer": 60, "unit": "mm", "absolute_tolerance": .05,
            "answer_evidence": "L=100, a=20 shown with common datum.",
            "derivation": {"expression": "L-2*a", "inputs": [
                {"symbol": "L", "value": 100, "drawing_evidence": "overall"},
                {"symbol": "a", "value": 20, "drawing_evidence": "margin"}]},
            "bad_pattern_tags": ["dimension_chain"], "confidence": .95, "ambiguity_notes": ""}


def test_safe_arithmetic():
    q = question()
    assert qa.evaluate_expression(q["derivation"]["expression"], q["derivation"]["inputs"]) == 60
    qa.validate_question(q, q)


@pytest.mark.parametrize("expression", ["__import__('os').system('x')", "L.__class__", "[L][0]", "L**1000", "True", "1e309"])
def test_arithmetic_rejects_code_and_nonfinite(expression):
    with pytest.raises(ValueError):
        qa.evaluate_expression(expression, question()["derivation"]["inputs"])


@pytest.mark.parametrize("box", [[-1, 0, 10, 10], [5, 5, 2, 10], [0, 0, 1001, 200], [0, 0, float("nan"), 500]])
def test_regions_are_bounded(box):
    q = question()
    q["regions"][0]["bbox"] = box
    with pytest.raises(ValueError):
        qa.validate_question(q, q)


def test_inconsistent_calculation_rejected():
    q = question()
    q["expected_answer"] = 61
    with pytest.raises(ValueError, match="does not reproduce"):
        qa.validate_question(q, q)


def test_blind_public_projection_omits_labels():
    public = qa.public_question(question())
    assert "expected_answer" not in public
    assert "answer_evidence" not in public
    assert "derivation" not in public
    assert "confidence" not in public


@pytest.fixture
def pilot(tmp_path, monkeypatch):
    monkeypatch.setattr(qa, "ROOT", tmp_path)
    source, author, audit = (tmp_path / name for name in ("sources", "author", "audit"))
    for directory in (source, author, audit):
        directory.mkdir()
    Image.new("RGB", (200, 100), "white").save(source / "input.png")
    write_json_atomic(source / "sources.json", {"images": [{"source_id": "pdf-001", "image": "input.png",
                      "sha256": sha256_file(source / "input.png"), "rights": "test",
                      "title": "\u4e2d\u6587\u56fe\u7eb8"}]})
    write_json_atomic(author / "questions.json", {"questions": [question()], "validation_errors": [],
                      "source_manifest_sha256": sha256_file(source / "sources.json")})
    write_json_atomic(audit / "audit.json", {"author_questions_sha256": sha256_file(author / "questions.json"),
                      "answers": [{"question_id": "drawing-01", "answer": 60, "answerable": True,
                                   "requires_image": True, "confidence": .95, "evidence": "100 minus 40", "ambiguity_notes": ""}]})
    return source, author, audit, tmp_path / "built"


def test_build_and_real_mcp_submission(pilot):
    summary = qa.build_tasks(*pilot)
    assert summary["eligible"] == 1 and summary["human_accepted"] == 0
    task = pilot[3] / "tasks/drawing-01"
    manifest = validate_bundle(task)
    assert manifest["label_status"] == "model_proposed_not_gt"
    with Image.open(task / "public/region-A.png") as crop:
        assert crop.size == (100, 40)
    public = json.loads((task / "public/task.json").read_text())
    assert "expected" not in json.dumps(public) and "derivation" not in public
    episode = Episode.reset(task, pilot[3] / "test-episode")
    tools = PublicTools(episode.root)
    tools.call("observe", {"image": "region-A.png", "intent": "Read margin"})
    tools.call("submit", {"answer": {"answer": 60}})
    assert grade_episode(task, Episode(episode.root))["passed"]
    assert not (episode.root / "input/annotation.json").exists()


def test_disagreement_quarantined_but_reviewable(pilot):
    path = pilot[2] / "audit.json"
    record = json.loads(path.read_text())
    record["answers"][0]["answer"] = 70
    write_json_atomic(path, record)
    summary = qa.build_tasks(*pilot)
    assert summary["completed"] == 1 and summary["eligible"] == 0
    assert summary["quarantined"][0]["reasons"] == ["author_blind_answer_disagreement"]
    assert not validate_bundle(pilot[3] / "tasks/drawing-01")["diagnostic_eligible"]


def test_changed_source_fails_closed(pilot):
    Image.new("RGB", (100, 100), "black").save(pilot[0] / "input.png")
    with pytest.raises(ValueError, match="hash mismatch"):
        qa.build_tasks(*pilot)


def test_nonvisual_question_is_not_a_vision_success(pilot):
    path = pilot[2] / "audit.json"
    record = json.loads(path.read_text())
    record["answers"][0]["requires_image"] = False
    write_json_atomic(path, record)
    summary = qa.build_tasks(*pilot)
    assert summary["eligible"] == 0
    assert "question_solvable_without_image" in summary["quarantined"][0]["reasons"]


def test_nan_audit_confidence_fails_closed(pilot):
    path = pilot[2] / "audit.json"
    record = json.loads(path.read_text())
    record["answers"][0]["confidence"] = float("nan")
    # Malformed external JSON must not pass merely because comparisons with NaN are false.
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid audit confidence"):
        qa.build_tasks(*pilot)


def test_changed_teacher_answers_invalidate_audit(pilot):
    path = pilot[1] / "questions.json"
    value = json.loads(path.read_text())
    value["questions"][0]["expected_answer"] = 30
    write_json_atomic(path, value)
    with pytest.raises(ValueError, match="different questions"):
        qa.build_tasks(*pilot)


def test_fresh_output_required(pilot):
    qa.build_tasks(*pilot)
    with pytest.raises(FileExistsError):
        qa.build_tasks(*pilot)


def boxed_question():
    q = question()
    q.update(query="\u6846\u793a\u957f\u5ea6\u662f\u591a\u5c11\u6beb\u7c73\uff1f", accepted_answers=[])
    return q


def test_boxed_short_public_prompt():
    q = boxed_question()
    qa.validate_question(q, q, boxed=True)
    public = qa.public_question(q, boxed=True)
    assert set(public) == {"question_id", "query", "answer_format", "unit"}
    for key in ("options", "regions", "task_type", "source_id", "accepted_answers", "derivation"):
        assert key not in public


@pytest.mark.parametrize("change", [{"query": "x" * 36}, {"query": "Subtract 20"},
                                    {"regions": question()["regions"] * 2},
                                    {"options": [{"value": "x", "label": "x"}]}])
def test_boxed_no_wordy_hints_or_options(change):
    q = boxed_question()
    q.update(change)
    with pytest.raises(ValueError):
        qa.validate_question(q, q, boxed=True)


def test_aliases_are_explicit_not_fuzzy_matching():
    expected = {"answer": "\u4e2d\u5fc3\u7ebf"}
    aliases = {"answer": ["centerline", "centre line"]}
    assert check_answer({"answer": " Centerline. "}, expected, 0, aliases)["answer"]
    assert not check_answer({"answer": "hidden line or centerline"}, expected, 0, aliases)["answer"]
    assert not check_answer({"answer": "centerline"}, expected, 0)["answer"]
    assert not check_answer({"answer": "60"}, {"answer": 60}, .1, {"answer": []})["answer"]


def test_frozen_line_terminology_does_not_ignore_arbitrary_parentheses():
    q = boxed_question()
    q.update(task_type="line_role", answer_kind="text", expected_answer="\u5c3a\u5bf8\u754c\u7ebf")
    aliases = {"answer": qa.frozen_aliases(q)}
    expected = {"answer": q["expected_answer"]}
    assert check_answer({"answer": "\u5c3a\u5bf8\u754c\u7ebf\uff08\u7ec6\u5b9e\u7ebf\uff09"}, expected, 0, aliases)["answer"]
    assert not check_answer({"answer": "\u5c3a\u5bf8\u754c\u7ebf\uff08\u4e0d\u662f\uff09"}, expected, 0, aliases)["answer"]
    assert not check_answer({"answer": "\u7ec6\u5b9e\u7ebf"}, expected, 0, aliases)["answer"]
    assert not check_answer({"answer": "\u5c3a\u5bf8\u7ebf"}, expected, 0, aliases)["answer"]


def prepare_boxed_pilot(pilot):
    source, author, audit, output = pilot
    record = json.loads((author / "questions.json").read_text(encoding="utf-8"))
    record.update(questions=[boxed_question()], protocol=qa.BOXED_PROTOCOL)
    write_json_atomic(author / "questions.json", record)
    image = audit / "boxed-images/drawing-01.png"
    qa.render_boxed_image(source / "input.png", boxed_question()["regions"][0], image)
    record = json.loads((audit / "audit.json").read_text(encoding="utf-8"))
    record.update(author_questions_sha256=sha256_file(author / "questions.json"),
                  boxed_image_hashes={"drawing-01": sha256_file(image)})
    write_json_atomic(audit / "audit.json", record)


def test_boxed_exact_audited_image_and_no_answer_leak(pilot):
    prepare_boxed_pilot(pilot)
    summary = qa.build_tasks(*pilot)
    assert summary["eligible"] == 1 and summary["protocol"] == qa.BOXED_PROTOCOL
    task = pilot[3] / "tasks/drawing-01"
    public = json.loads((task / "public/task.json").read_text(encoding="utf-8"))
    assert public["input_images"] == ["drawing-boxed.png"]
    assert set(public) == {"task_id", "query", "input_images", "answer_format", "answer_file"}
    assert len(list((task / "public").iterdir())) == 2
    image = task / "public/drawing-boxed.png"
    assert sha256_file(image) == sha256_file(pilot[2] / "boxed-images/drawing-01.png")
    with Image.open(image) as rendered:
        assert rendered.size == (200, 100)
        assert rendered.getpixel((20, 10)) == (220, 35, 45)
        assert rendered.getpixel((40, 30)) == (255, 255, 255)
    episode = Episode.reset(task, pilot[3] / "test-episode")
    PublicTools(episode.root).call("submit", {"answer": {"answer": 60}})
    assert grade_episode(task, episode)["passed"]


def test_boxed_changed_audited_image_fails(pilot):
    prepare_boxed_pilot(pilot)
    path = pilot[2] / "audit.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["boxed_image_hashes"]["drawing-01"] = "0" * 64
    write_json_atomic(path, record)
    with pytest.raises(ValueError, match="differs from blind-audited"):
        qa.build_tasks(*pilot)


def test_tiny_box_rejected(tmp_path):
    source = tmp_path / "source.png"
    Image.new("RGB", (100, 100)).save(source)
    with pytest.raises(ValueError, match="too small"):
        qa.render_boxed_image(source, {"bbox": [0, 0, 10, 10]}, tmp_path / "box.png")


def test_blind_audit_sees_only_actual_boxed_image_and_minimal_query(pilot, monkeypatch):
    prepare_boxed_pilot(pilot)
    write_json_atomic(pilot[1] / "plan.json", {"protocol": qa.BOXED_PROTOCOL,
                      "assignments": [{"batch": "a", "question_id": "drawing-01"}]})
    seen = []

    def fake_astra(root, stage, request):
        seen.append(request)
        content = request.messages[0]["content"]
        assert content["image_order"] == ["drawing-01"]
        assert content["questions"] == [qa.public_question(boxed_question(), boxed=True)]
        assert len(request.images) == 1
        with Image.open(request.images[0]) as image:
            assert image.getpixel((20, 10)) == (220, 35, 45)
        return {"answers": [{"question_id": "drawing-01", "answer": 60, "answerable": True,
                "requires_image": True, "confidence": .95, "evidence": "test", "ambiguity_notes": ""}]}

    monkeypatch.setattr(qa, "call_astra", fake_astra)
    audit = pilot[0].parent / "new-audit"
    result = qa.audit_questions(pilot[0], pilot[1], audit)
    assert len(seen) == 1
    assert result["boxed_image_hashes"]["drawing-01"] == sha256_file(audit / "boxed-images/drawing-01.png")
    assert qa.build_tasks(pilot[0], pilot[1], audit, pilot[3])["eligible"] == 1


def test_unlisted_text_is_flagged_for_review_before_claiming_model_error(pilot):
    prepare_boxed_pilot(pilot)
    path = pilot[1] / "questions.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["questions"][0].update(task_type="line_role", query="What is this line?", answer_kind="text",
                                 expected_answer="centerline", accepted_answers=["centre line"],
                                 unit="none", absolute_tolerance=0,
                                 derivation={"expression": "", "inputs": []})
    write_json_atomic(path, record)
    path = pilot[2] / "audit.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["author_questions_sha256"] = sha256_file(pilot[1] / "questions.json")
    record["answers"][0]["answer"] = "centerline"
    write_json_atomic(path, record)
    assert qa.build_tasks(*pilot)["eligible"] == 1
    task = pilot[3] / "tasks/drawing-01"
    episode = Episode.reset(task, pilot[3] / "test-episode")
    PublicTools(episode.root).call("submit", {"answer": {"answer": "A centre line marking the axis"}})
    verdict = grade_episode(task, episode)
    assert verdict["human_review_required"] and verdict["unmatched_text_fields"] == ["answer"]
    assert verdict["passed"] is None and verdict["score"] is None


def prepare_context_pilot(pilot, scope="cross_view"):
    prepare_boxed_pilot(pilot)
    source, author, audit, _ = pilot
    assignment = {key: boxed_question()[key] for key in ("question_id", "source_id", "task_type")}
    assignment.update(batch="a", required_evidence_scopes=["cross_view"], focus="private target requirement")
    write_json_atomic(author / "plan.json", {"protocol": qa.BOXED_PROTOCOL,
        "challenge_profile": qa.CONTEXT_CHALLENGE, "authoring_brief": "PRIVATE teacher guidance",
        "assignments": [assignment]})
    record = json.loads((author / "questions.json").read_text(encoding="utf-8"))
    record["author_plan_sha256"] = sha256_file(author / "plan.json")
    write_json_atomic(author / "questions.json", record)
    record = json.loads((audit / "audit.json").read_text(encoding="utf-8"))
    record.update(author_questions_sha256=sha256_file(author / "questions.json"),
                  author_plan_sha256=sha256_file(author / "plan.json"), challenge_profile=qa.CONTEXT_CHALLENGE)
    record["answers"][0].update(evidence_scope=scope, difficulty_evidence="Correspondence between two projections.")
    write_json_atomic(audit / "audit.json", record)


@pytest.mark.parametrize("scope,eligible", [("local_reading", 0), ("cross_view", 1), (None, 0)])
def test_contextual_difficulty_is_gated_without_leaking_teacher_brief(pilot, scope, eligible):
    prepare_context_pilot(pilot, scope)
    summary = qa.build_tasks(*pilot)
    assert summary["eligible"] == eligible
    task = pilot[3] / "tasks/drawing-01"
    public = json.loads((task / "public/task.json").read_text(encoding="utf-8"))
    assert "focus" not in public and "challenge" not in json.dumps(public)
    assert "PRIVATE" not in json.dumps(public)
    annotation = json.loads((task / "private/annotation.json").read_text(encoding="utf-8"))
    assert annotation["challenge_assignment"]["focus"] == "private target requirement"
    if not eligible:
        assert "contextual_difficulty_not_confirmed" in summary["quarantined"][0]["reasons"]


def test_contextual_plan_cannot_be_relaxed_after_blind_audit(pilot):
    prepare_context_pilot(pilot)
    path = pilot[1] / "plan.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["assignments"][0]["required_evidence_scopes"].append("local_reading")
    write_json_atomic(path, record)
    with pytest.raises(ValueError, match="not bound"):
        qa.build_tasks(*pilot)


def test_context_auditor_gets_rubric_but_not_assignment_or_answers(pilot, monkeypatch):
    prepare_context_pilot(pilot)

    def fake_astra(root, stage, request):
        assert request.response_schema == qa.CONTEXT_AUDIT_SCHEMA
        assert "MINIMUM evidence" in request.instructions
        assert request.messages[0]["content"]["questions"] == [qa.public_question(boxed_question(), boxed=True)]
        assert "PRIVATE" not in json.dumps(request.messages)
        assert "required_evidence_scopes" not in json.dumps(request.messages)
        return {"answers": [{"question_id": "drawing-01", "answer": 60, "answerable": True,
            "requires_image": True, "confidence": .95, "evidence": "test", "ambiguity_notes": "",
            "evidence_scope": "cross_view", "difficulty_evidence": "Two projections must correspond."}]}

    monkeypatch.setattr(qa, "call_astra", fake_astra)
    audit = pilot[0].parent / "context-audit"
    result = qa.audit_questions(pilot[0], pilot[1], audit)
    assert result["author_plan_sha256"] == sha256_file(pilot[1] / "plan.json")
    assert qa.build_tasks(pilot[0], pilot[1], audit, pilot[3])["eligible"] == 1


def test_dimension_challenge_counts_used_operands_not_decorative_inputs():
    q = boxed_question()
    assignment = {**q, "minimum_dimension_operands": 3, "minimum_arithmetic_operations": 2}
    q["derivation"]["inputs"].append({"symbol": "b", "value": 20, "drawing_evidence": "second margin"})
    with pytest.raises(ValueError, match="used operands"):
        qa.validate_question(q, assignment, boxed=True)
    q["derivation"]["expression"] = "L-a-b"
    qa.validate_question(q, assignment, boxed=True)


def test_author_brief_is_private_and_binds_canonical_saved_plan(pilot, monkeypatch):
    prepare_context_pilot(pilot)
    plan = json.loads((pilot[1] / "plan.json").read_text(encoding="utf-8"))
    plan["assignments"] = [{**plan["assignments"][0], "question_id": f"hard-{i:02d}"} for i in range(10)]
    path = pilot[0].parent / "input-plan.json"
    path.write_text(json.dumps(plan, separators=(",", ":")), encoding="utf-8")

    def fake_astra(root, stage, request):
        content = request.messages[0]["content"]
        assert content["authoring_brief"] == plan["authoring_brief"]
        return {"questions": [{**boxed_question(), "question_id": assignment["question_id"]}
                              for assignment in content["assignments"]]}

    monkeypatch.setattr(qa, "call_astra", fake_astra)
    output = pilot[0].parent / "fresh-author"
    result = qa.author_questions(pilot[0], path, output)
    assert not result["validation_errors"]
    assert result["author_plan_sha256"] == sha256_file(output / "plan.json")
