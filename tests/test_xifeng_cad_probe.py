import base64
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "probe_xifeng_cad", Path(__file__).resolve().parents[1] / "evals/posttrain/probe_xifeng_cad.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def test_visible_wrapper_decoding():
    target = "https://pan.quark.cn/s/abc?pwd=ABCD"
    wrapper = "https://xifengboke.com/download.php?hk_url=" + base64.b64encode(target.encode()).decode()
    assert probe.public_target(wrapper) == target


@pytest.mark.parametrize("url", ["https://127.0.0.1/a", "http://pan.quark.cn/s/a",
                                "https://pan.quark.cn.evil/s/a", "https://u:p@pan.quark.cn/s/a",
                                "https://pan.quark.cn:8000/s/a", "https://xifengboke.com/?hk_url=invalid!"])
def test_target_host_and_protocol_boundary(url):
    assert probe.public_target(url) is None


def test_claims_are_not_promoted_to_verified_gt():
    html = '''<article class="single-post"><div class="entry">
    <p>18个标准件是stp格式文件</p><p>提取码：YCXK</p>
    </div></article>'''.encode()
    claims = probe.advertised_claims(html)
    assert claims["format_mentions"] == ["STP"]
    assert claims["public_passcodes"] == ["YCXK"]
    assert not claims["claims_verified_against_file_bytes"]


def test_ambiguous_passcodes_not_guessed(monkeypatch):
    class Response:
        status_code = 404

        def raise_for_status(self):
            pass

        def json(self):
            return {"code": 41017, "message": "passcode required"}

    class Session:
        def post(self, url, **kwargs):
            assert kwargs["json"]["passcode"] == ""
            return Response()

    monkeypatch.setattr(probe.time, "sleep", lambda _: None)
    result = probe.list_quark(Session(), "https://pan.quark.cn/s/abc", ["ABCD", "EFGH"])
    assert result["status"] == "unavailable_or_passcode_required"
