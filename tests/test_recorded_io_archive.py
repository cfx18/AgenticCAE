import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import urllib.error
import urllib.request

import pytest

from cad_evoloop.evaluation.review_catalog import RecordedIOArchive
from cad_evoloop.evaluation.human_review import _ReviewServer, GeometryReviewHandler


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def archive_config(tmp_path):
    root = tmp_path / "archive"
    root.mkdir()
    (root / "summary.json").write_text('{"campaign":"test"}', encoding="utf-8")
    (root / "untrusted.html").write_text("<script>throw 'never execute'</script>", encoding="utf-8")
    (root / "not-listed.txt").write_text("not public", encoding="utf-8")
    files = [{"path": name, "sha256": sha(root / name)} for name in ("summary.json", "untrusted.html")]
    (root / "manifest.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    zipped = tmp_path / "archive.zip"
    zipped.write_bytes(b"test binary archive")
    config = {"directory": "archive", "manifest_sha256": sha(root / "manifest.json"),
              "zip_path": "archive.zip", "zip_sha256": sha(zipped)}
    return tmp_path, config


def test_archive_is_allowlisted_and_hash_checked(archive_config):
    root, config = archive_config
    archive = RecordedIOArchive(root, config)
    assert archive.summary == {"campaign": "test"}
    assert archive.file("archive.zip") == root / "archive.zip"
    for path in ("../archive.zip", "..\\archive.zip", "not-listed.txt", "/summary.json"):
        with pytest.raises(KeyError):
            archive.file(path)
    (root / "archive/summary.json").write_text("changed")
    with pytest.raises(ValueError, match="changed"):
        archive.file("summary.json")


def test_archive_rejects_changed_manifest_and_escape(archive_config):
    root, config = archive_config
    with pytest.raises(ValueError, match="manifest hash"):
        RecordedIOArchive(root, {**config, "manifest_sha256": "wrong"})
    manifest = root / "archive/manifest.json"
    manifest.write_text(json.dumps({"files": [{"path": "../secret", "sha256": "bad"}]}))
    with pytest.raises(ValueError, match="file path"):
        RecordedIOArchive(root, {**config, "manifest_sha256": sha(manifest)})


def test_http_archives_are_attachments_and_block_unknown_paths(archive_config):
    root, config = archive_config
    archive = RecordedIOArchive(root, config)
    server = _ReviewServer(("127.0.0.1", 0), GeometryReviewHandler, app_dir=root, bundle_dir=root,
                          store=None, catalog=SimpleNamespace(archives={"test": archive}))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_address[1]}/recorded-io/"
    try:
        with urllib.request.urlopen(base + "test/untrusted.html") as response:
            assert response.headers["Content-Type"] == "application/octet-stream"
            assert response.headers["Content-Disposition"].startswith("attachment;")
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            assert response.read().startswith(b"<script>")
        for path in ("missing/summary.json", "test/%2e%2e/secret", "test/not-listed.txt"):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(base + path)
            assert error.value.code == 404
        (root / "archive.zip").write_bytes(b"changed archive")
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(base + "test/archive.zip")
        assert error.value.code == 409
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
