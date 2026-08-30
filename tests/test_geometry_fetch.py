from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "evals/geometry-benchmarks/scripts/fetch.py"
)


def load_fetch_module():
    spec = importlib.util.spec_from_file_location("geometry_fetch", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_geometry_pilot_sources_are_pinned_and_locally_scoped(tmp_path: Path) -> None:
    fetch = load_fetch_module()

    assert len(fetch.BENCHCAD_REVISION) == 40
    assert len(fetch.ORTHO2CAD_REVISION) == 40
    assert fetch.SOURCES["benchcad"]["license"] == "CC-BY-4.0"
    assert fetch.SOURCES["ortho2cad"]["license"] is None
    assert all(
        not Path(item["path"]).is_absolute()
        for source in fetch.SOURCES.values()
        for item in source["artifacts"]
    )

    cached = tmp_path / "cached.bin"
    cached.write_bytes(b"cad")
    fetch.download("https://invalid.example/file", cached, 3)
    assert cached.read_bytes() == b"cad"


def test_hugging_face_artifact_paths_are_url_encoded() -> None:
    fetch = load_fetch_module()

    url = fetch.hf_url("owner/data", "abc123", "folder/a drawing.png")

    assert url.endswith("folder/a%20drawing.png")

