"""Multi-experiment navigation over unchanged, independently reviewed bundles."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil

from .human_review import HumanReviewStore, _canonical_sha256
from cad_evoloop.ledger.ledger import sha256_file


class RecordedIOArchive:
    """Serve only hash-bound files explicitly listed in an experiment export."""

    def __init__(self, root: Path, config: dict) -> None:
        self.root = (root / config["directory"]).resolve()
        self.zip_path = (root / config["zip_path"]).resolve()
        if not self.root.is_relative_to(root) or not self.zip_path.is_relative_to(root):
            raise ValueError("Recorded I/O paths must stay inside the workspace")
        manifest_path = self.root / "manifest.json"
        if sha256_file(manifest_path) != config["manifest_sha256"]:
            raise ValueError("Recorded I/O manifest hash mismatch")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.files = {}
        for item in manifest["files"]:
            path = item["path"]
            if path in self.files or not (self.root / path).resolve().is_relative_to(self.root):
                raise ValueError("Invalid recorded I/O file path")
            self.files[path] = item["sha256"]
        self.files["manifest.json"] = config["manifest_sha256"]
        self.zip_sha256 = config["zip_sha256"]
        self.summary = json.loads(self.file("summary.json").read_text(encoding="utf-8"))
        self.note = config.get("note", "")

    def file(self, relative: str) -> Path:
        if relative == "archive.zip":
            path, expected = self.zip_path, self.zip_sha256
        elif relative in self.files:
            path, expected = (self.root / relative).resolve(), self.files[relative]
            if not path.is_relative_to(self.root):
                raise ValueError("Recorded I/O path escaped the export")
        else:
            raise KeyError(relative)
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError("Recorded I/O file missing or changed")
        return path


class ReviewCatalog:
    def __init__(self, config_path: Path, default_bundle: Path) -> None:
        config_path = config_path.resolve()
        config = json.loads(config_path.read_text(encoding="utf-8"))
        root = (config_path.parent / config.get("workspace_root", ".")).resolve()

        def local_path(relative: str) -> Path:
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Catalog paths must stay inside the workspace")
            return path

        self.stores: dict[str, HumanReviewStore] = {}
        self.archives: dict[str, RecordedIOArchive] = {}
        self.entries = []
        ledgers = set()
        self.default_id = None
        for item in config["bundles"]:
            key = item["id"]
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", key) or key in self.stores:
                raise ValueError(f"Invalid or duplicate catalog ID: {key}")
            bundle = local_path(item["bundle"])
            reviews = local_path(item["reviews"])
            if reviews in ledgers:
                raise ValueError("Catalog entries must have separate review ledgers")
            ledgers.add(reviews)
            store = HumanReviewStore(bundle / "review-data.json", reviews)
            self.stores[key] = store
            self.entries.append({
                "id": key, "harness": item["harness"], "label": item["label"],
                "campaign_id": store.bundle["campaign"]["campaign_id"],
                "bundle_sha256": store.bundle["bundle_sha256"],
                "run_count": len(store.targets),
            })
            if item.get("recorded_io"):
                archive = RecordedIOArchive(root, item["recorded_io"])
                if archive.summary["campaign"] != store.bundle["campaign"]["campaign_id"]:
                    raise ValueError("Recorded I/O and review campaign mismatch")
                self.archives[key] = archive
                self.entries[-1]["recorded_io"] = {
                    "base_url": f"/recorded-io/{key}/", "note": archive.note,
                    "summary": archive.summary,
                }
            if bundle == default_bundle.resolve():
                self.default_id = key
        if not self.entries or self.default_id is None:
            raise ValueError("Default bundle must belong to the catalog")

        # The navigation UI gets its own immutable snapshot, never overwriting
        # the app/evidence snapshots to which historical reviews are bound.
        app_source = local_path(config["app_dir"])
        sources = {
            name: app_source / name
            for name in ("index.html", "app.js", "styles.css", "geometry-viewer.js")
        }
        sources.update({name: app_source / name for name in ("astra.html", "astra.js", "astra.css", "benchmark-metrics.js", "benchmark-metrics.css")
                        if (app_source / name).is_file()})
        sources.update({
            path.relative_to(app_source).as_posix(): path
            for path in (app_source / "vendor").rglob("*") if path.is_file()
        })
        for name, relative in config.get("supplemental_pages", {}).items():
            if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*\.html", name) or name in sources:
                raise ValueError("Invalid or conflicting supplemental review page")
            sources[name] = local_path(relative)
        self.supplemental_pages = sorted(config.get("supplemental_pages", {}))
        files = [{"path": f"app/{name}", "sha256": sha256_file(path)}
                 for name, path in sorted(sources.items())]
        metadata = {
            "schema_version": "1.0", "catalog": config,
            "catalog_sha256": _canonical_sha256(config), "files": files,
            "app_sha256": _canonical_sha256(files),
        }
        self.presentation_sha256 = _canonical_sha256(metadata)
        snapshot = local_path(config["presentation_dir"]) / self.presentation_sha256
        self.app_dir = snapshot / "app"
        self.manifest_path = snapshot / "presentation.json"
        if not snapshot.exists():
            self.app_dir.mkdir(parents=True)
            for name, source in sources.items():
                destination = self.app_dir / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            self.manifest_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        self.presentation = {
            "schema_version": "1.0", "presentation_sha256": self.presentation_sha256,
            "app_sha256": metadata["app_sha256"],
            "catalog_sha256": metadata["catalog_sha256"],
            "manifest_path": self.manifest_path.relative_to(root).as_posix(),
        }
        self.verify_presentation()

    def verify_presentation(self) -> None:
        metadata = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if _canonical_sha256(metadata) != self.presentation_sha256:
            raise ValueError("Review presentation manifest hash mismatch")
        for item in metadata["files"]:
            path = self.manifest_path.parent / item["path"]
            if not path.is_file() or sha256_file(path) != item["sha256"]:
                raise ValueError("Review presentation artifact hash mismatch")

    def response(self) -> dict:
        return {
            "default_id": self.default_id, "bundles": self.entries,
            "presentation_sha256": self.presentation_sha256,
            "supplemental_pages": self.supplemental_pages,
        }
