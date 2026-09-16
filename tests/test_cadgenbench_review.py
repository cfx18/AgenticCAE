import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "evals/cadgenbench/scripts/prepare_111_review.py"
spec = importlib.util.spec_from_file_location("prepare_111_review", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_report_parser_extracts_only_requested_fixture(tmp_path):
    def card(sample, value):
        return f'''<div class="fixture-card"><h2 class="card-title">{sample} <span class="status-valid">valid</span></h2>
        <div class="headline-cad"><span class="headline-value">{value}</span></div>
        <div class="headline-shape"><span class="headline-value">0.500</span><span>Surface Distance F1: 0.400 &middot; Volume IoU: 0.600</span></div>
        <div class="headline-iface"><span class="headline-value">0.700</span></div>
        <div class="headline-topo"><span class="headline-value">0.800</span><span class="headline-sub">cand (1,2,0) vs gt (1,3,0)</span></div></div>'''
    path = tmp_path / "report.html"
    path.write_text(card("110", "0.990") + card("111", "0.650"))
    values = module.parse_report(path)
    assert values["cad_score"] == 0.650
    assert values["volume_iou"] == 0.600
    assert values["surface_f1"] == 0.400
    assert values["valid"] is True
    with pytest.raises(ValueError, match="Expected one"):
        module.parse_report(path, "999")


def test_published_111_is_unscored_and_assets_are_bound():
    from cad_evoloop.evaluation.human_review import HumanReviewStore
    root = SCRIPT.parents[3]
    bundle = root / "reports/generated/cadgenbench-astra-111-review/review-data.json"
    if not bundle.is_file():
        pytest.skip("Local generated experiment is not part of a clean checkout")
    store = HumanReviewStore(bundle, root / "evals/cadgenbench/human-reviews/111-astra-ultra.jsonl")
    run = store.bundle["runs"][0]
    assert run["score"] is None and run["passed"] is None
    comparison = run["attempts"][0]["benchmark_comparison"]
    assert not comparison["candidate"]["metrics"]
    assert all(r["sample_id"] == "111" for r in comparison["references"])
    assert store.verify_bundle()["ok"]
