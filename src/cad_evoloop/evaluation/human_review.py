"""Append-only human review ledger and local review API."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from typing import Any
import urllib.parse
import uuid

from cad_evoloop.ledger.ledger import file_lock, sha256_file


DECISIONS = {"agree", "partially_agree", "disagree", "uncertain"}
PASS_ASSESSMENTS = {"correct", "false_positive", "false_negative", "uncertain"}
SELECTION_ASSESSMENTS = {"correct", "incorrect", "uncertain", "not_applicable"}
RECOMMENDED_ACTIONS = {
    "keep", "override_pass", "override_fail", "exclude_sample",
    "revise_verifier", "rerun", "needs_expert",
}
ISSUE_TYPES = {
    "agent_geometry", "agent_reasoning", "input_ambiguity", "ground_truth_error",
    "verifier_metric", "verifier_threshold", "alignment_error", "export_error",
    "mcp_error", "harness_error", "attempt_selection", "none",
}
FINDING_CATEGORIES = ISSUE_TYPES - {"none"}
SEVERITIES = {"note", "minor", "major", "critical"}
RATING_FIELDS = {
    "evidence_sufficiency", "geometry_fidelity", "verifier_validity", "reflection_quality",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _required_string(value: Any, label: str, *, maximum: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    value = value.strip()
    if len(value) > maximum:
        raise ValueError(f"{label} exceeds {maximum} characters")
    return value


def _enum(value: Any, allowed: set[str], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"{label} must be one of {sorted(allowed)}")
    return value


def _validate_submission(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Review body must be a JSON object")
    reviewer = value.get("reviewer")
    if not isinstance(reviewer, dict):
        raise ValueError("reviewer must be an object")
    reviewer_id = _required_string(reviewer.get("id"), "reviewer.id", maximum=120)
    expertise = reviewer.get("expertise", "unspecified")
    if not isinstance(expertise, str) or len(expertise) > 120:
        raise ValueError("reviewer.expertise must be a string of at most 120 characters")
    ratings = value.get("ratings")
    if not isinstance(ratings, dict) or set(ratings) != RATING_FIELDS:
        raise ValueError(f"ratings must contain exactly {sorted(RATING_FIELDS)}")
    for key, rating in ratings.items():
        if rating is not None and (not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5):
            raise ValueError(f"ratings.{key} must be null or an integer from 1 to 5")
    issue_types = value.get("issue_types")
    if not isinstance(issue_types, list) or not issue_types:
        raise ValueError("issue_types must be a non-empty list")
    if any(item not in ISSUE_TYPES for item in issue_types) or len(set(issue_types)) != len(issue_types):
        raise ValueError(f"issue_types must be unique values from {sorted(ISSUE_TYPES)}")
    if "none" in issue_types and len(issue_types) != 1:
        raise ValueError("issue_types 'none' cannot be combined with another issue")
    findings = value.get("findings", [])
    if not isinstance(findings, list) or len(findings) > 50:
        raise ValueError("findings must be a list with at most 50 entries")
    clean_findings = []
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            raise ValueError(f"findings[{index}] must be an object")
        clean_findings.append({
            "category": _enum(finding.get("category"), FINDING_CATEGORIES, f"findings[{index}].category"),
            "severity": _enum(finding.get("severity"), SEVERITIES, f"findings[{index}].severity"),
            "location": str(finding.get("location", "")).strip()[:500],
            "observation": _required_string(
                finding.get("observation"), f"findings[{index}].observation", maximum=4000,
            ),
            "recommendation": str(finding.get("recommendation", "")).strip()[:4000],
        })
    notes = str(value.get("notes", "")).strip()
    if len(notes) > 12000:
        raise ValueError("notes exceeds 12000 characters")
    decision = _enum(value.get("verifier_decision"), DECISIONS, "verifier_decision")
    if decision != "agree" and not notes and not clean_findings:
        raise ValueError("A non-agree decision requires notes or a structured finding")
    duration = value.get("duration_seconds")
    if duration is not None and (
        not isinstance(duration, (int, float)) or isinstance(duration, bool) or not 0 <= duration <= 86400
    ):
        raise ValueError("duration_seconds must be null or between 0 and 86400")
    supersedes = value.get("supersedes_review_id")
    if supersedes is not None:
        supersedes = _required_string(supersedes, "supersedes_review_id", maximum=64)
    return {
        "target_id": _required_string(value.get("target_id"), "target_id", maximum=64),
        "attempt_id": _required_string(value.get("attempt_id"), "attempt_id", maximum=64),
        "reviewer": {"id": reviewer_id, "expertise": expertise.strip() or "unspecified"},
        "verifier_decision": decision,
        "strict_pass_assessment": _enum(
            value.get("strict_pass_assessment"), PASS_ASSESSMENTS, "strict_pass_assessment",
        ),
        "selected_attempt_assessment": _enum(
            value.get("selected_attempt_assessment"), SELECTION_ASSESSMENTS,
            "selected_attempt_assessment",
        ),
        "ratings": ratings,
        "issue_types": issue_types,
        "recommended_action": _enum(
            value.get("recommended_action"), RECOMMENDED_ACTIONS, "recommended_action",
        ),
        "findings": clean_findings,
        "notes": notes,
        "duration_seconds": round(float(duration), 1) if duration is not None else None,
        "supersedes_review_id": supersedes,
    }


class HumanReviewStore:
    """Persist immutable, hash-chained human adjudications for a review bundle."""

    def __init__(self, bundle_path: str | Path, reviews_path: str | Path) -> None:
        self.bundle_path = Path(bundle_path).resolve()
        self.reviews_path = Path(reviews_path).resolve()
        self.lock_path = self.reviews_path.with_suffix(self.reviews_path.suffix + ".lock")
        self.bundle = json.loads(self.bundle_path.read_text(encoding="utf-8"))
        self.targets = {item["target_id"]: item for item in self.bundle.get("runs", [])}
        bundle_integrity = self.verify_bundle()
        if not bundle_integrity["ok"]:
            raise ValueError(f"Review bundle integrity failed: {bundle_integrity['errors']}")

    def verify_bundle(self) -> dict[str, Any]:
        errors = []
        declared = self.bundle.get("bundle_sha256")
        content = {key: value for key, value in self.bundle.items() if key != "bundle_sha256"}
        if declared != _canonical_sha256(content):
            errors.append({"artifact": "review-data.json", "error": "bundle hash mismatch"})
        for run in self.bundle.get("runs", []):
            assets = list(run.get("input_evidence", []))
            for attempt in run.get("attempts", []):
                image_paths = attempt.get("images") or {}
                image_evidence = (attempt.get("evidence") or {}).get("render_images") or {}
                for name, evidence in image_evidence.items():
                    if evidence and image_paths.get(name):
                        assets.append({"path": image_paths[name], **evidence})
                geometry_paths = attempt.get("geometry") or {}
                geometry_evidence = (attempt.get("evidence") or {}).get("geometry_assets") or {}
                for name, evidence in geometry_evidence.items():
                    if evidence and geometry_paths.get(name):
                        assets.append({"path": geometry_paths[name], **evidence})
            for evidence in assets:
                relative = evidence.get("path")
                if not relative:
                    continue
                path = (self.bundle_path.parent / relative).resolve()
                try:
                    path.relative_to(self.bundle_path.parent.resolve())
                except ValueError:
                    errors.append({"artifact": relative, "error": "asset path escapes bundle"})
                    continue
                if not path.is_file():
                    errors.append({"artifact": relative, "error": "asset missing"})
                elif sha256_file(path) != evidence.get("sha256"):
                    errors.append({"artifact": relative, "error": "asset hash mismatch"})
        review_system = self.bundle.get("review_system") or {}
        for evidence in [
            *review_system.get("served_app", []),
            *review_system.get("source_snapshot", []),
        ]:
            relative = evidence.get("path")
            path = (self.bundle_path.parent / str(relative)).resolve()
            try:
                path.relative_to(self.bundle_path.parent.resolve())
            except ValueError:
                errors.append({"artifact": relative, "error": "review system path escapes bundle"})
                continue
            if not path.is_file():
                errors.append({"artifact": relative, "error": "review system artifact missing"})
            elif sha256_file(path) != evidence.get("sha256"):
                errors.append({"artifact": relative, "error": "review system hash mismatch"})
        return {"ok": not errors, "bundle_sha256": declared, "errors": errors}

    def _records_unlocked(self) -> list[dict[str, Any]]:
        if not self.reviews_path.is_file():
            return []
        rows = []
        for number, line in enumerate(
            self.reviews_path.read_text(encoding="utf-8").splitlines(), start=1,
        ):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid review JSONL at line {number}: {exc}") from exc
            rows.append(value)
        return rows

    def records(self) -> list[dict[str, Any]]:
        if not self.reviews_path.is_file():
            return []
        with file_lock(self.lock_path):
            return self._records_unlocked()

    def _binding(self, target_id: str, attempt_id: str) -> dict[str, Any]:
        run = self.targets.get(target_id)
        if not run:
            raise ValueError(f"Unknown review target: {target_id}")
        attempt = next((item for item in run.get("attempts", []) if item.get("attempt_id") == attempt_id), None)
        if not attempt:
            raise ValueError(f"Unknown attempt {attempt_id!r} for target {target_id}")
        campaign = self.bundle["campaign"]
        return {
            "bundle_sha256": self.bundle["bundle_sha256"],
            "campaign_id": campaign["campaign_id"],
            "campaign_manifest_sha256": campaign["campaign_manifest_sha256"],
            "source_manifest_sha256": campaign.get("source_manifest_sha256"),
            "protocol": campaign.get("protocol"),
            "target_id": target_id,
            "run_id": run.get("run_id"),
            "sample_id": run["sample_id"],
            "model": run["model"],
            "attempt_id": attempt_id,
            "attempt_evidence_sha256": attempt["evidence_sha256"],
            "candidate_sha256": (attempt.get("evidence") or {}).get("candidate", {}).get("sha256")
            if (attempt.get("evidence") or {}).get("candidate") else None,
            "verdict_sha256": (attempt.get("evidence") or {}).get("verdict", {}).get("sha256")
            if (attempt.get("evidence") or {}).get("verdict") else None,
        }

    def append(self, submission: Any) -> dict[str, Any]:
        clean = _validate_submission(submission)
        bundle_integrity = self.verify_bundle()
        if not bundle_integrity["ok"]:
            raise ValueError(f"Review bundle integrity failed: {bundle_integrity['errors']}")
        binding = self._binding(clean.pop("target_id"), clean.pop("attempt_id"))
        self.reviews_path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self.lock_path):
            records = self._records_unlocked()
            supersedes = clean.get("supersedes_review_id")
            if supersedes:
                prior = next((row for row in records if row.get("review_id") == supersedes), None)
                if not prior:
                    raise ValueError(f"Unknown supersedes_review_id: {supersedes}")
                if prior.get("binding") != binding:
                    raise ValueError("A review can only supersede a review of the same evidence")
            record = {
                "schema_version": "1.0",
                "review_id": uuid.uuid4().hex,
                "created_at": _utc_now(),
                "previous_record_sha256": records[-1].get("record_sha256") if records else None,
                "binding": binding,
                **clean,
            }
            record["record_sha256"] = _canonical_sha256(record)
            with self.reviews_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            return record

    def _verify_records(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        bundle_integrity = self.verify_bundle()
        errors = [
            {"line": None, **error} for error in bundle_integrity["errors"]
        ]
        previous = None
        identifiers = set()
        for index, record in enumerate(records, start=1):
            expected = record.get("record_sha256")
            content = {key: value for key, value in record.items() if key != "record_sha256"}
            if expected != _canonical_sha256(content):
                errors.append({"line": index, "error": "record hash mismatch"})
            if record.get("previous_record_sha256") != previous:
                errors.append({"line": index, "error": "previous hash mismatch"})
            review_id = record.get("review_id")
            if review_id in identifiers:
                errors.append({"line": index, "error": "duplicate review_id"})
            identifiers.add(review_id)
            binding = record.get("binding") or {}
            try:
                if binding != self._binding(binding.get("target_id", ""), binding.get("attempt_id", "")):
                    errors.append({"line": index, "error": "evidence binding mismatch"})
            except ValueError as exc:
                errors.append({"line": index, "error": str(exc)})
            previous = expected
        return {
            "ok": not errors,
            "bundle": bundle_integrity,
            "records": len(records),
            "head_sha256": previous,
            "errors": errors,
        }

    def verify(self) -> dict[str, Any]:
        if not self.reviews_path.is_file():
            return self._verify_records([])
        with file_lock(self.lock_path):
            return self._verify_records(self._records_unlocked())

    def response(self) -> dict[str, Any]:
        if self.reviews_path.is_file():
            with file_lock(self.lock_path):
                records = self._records_unlocked()
                integrity = self._verify_records(records)
        else:
            records = []
            integrity = self._verify_records(records)
        superseded = {row.get("supersedes_review_id") for row in records if row.get("supersedes_review_id")}
        active = [row for row in records if row.get("review_id") not in superseded]
        reviewed_targets = {row["binding"]["target_id"] for row in active}
        decisions = {name: sum(row.get("verifier_decision") == name for row in active) for name in DECISIONS}
        pass_labels = {
            name: sum(row.get("strict_pass_assessment") == name for row in active)
            for name in PASS_ASSESSMENTS
        }
        issue_counts = {
            name: sum(name in row.get("issue_types", []) for row in active)
            for name in ISSUE_TYPES if name != "none"
        }
        evidence_decisions: dict[tuple[str, str], set[str]] = {}
        for row in active:
            binding = row["binding"]
            evidence_decisions.setdefault(
                (binding["target_id"], binding["attempt_id"]), set(),
            ).add(row["verifier_decision"])
        rating_means = {}
        for name in RATING_FIELDS:
            values = [row["ratings"].get(name) for row in active if row["ratings"].get(name) is not None]
            rating_means[name] = round(sum(values) / len(values), 2) if values else None
        return {
            "records": records,
            "active_records": len(active),
            "summary": {
                "reviewed_targets": len(reviewed_targets),
                "total_targets": len(self.targets),
                "decisions": decisions,
                "strict_pass_assessments": pass_labels,
                "issue_counts": issue_counts,
                "conflicted_evidence": sum(len(values) > 1 for values in evidence_decisions.values()),
                "rating_means": rating_means,
            },
            "integrity": integrity,
        }


class _ReviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, *, app_dir: Path, bundle_dir: Path, store: HumanReviewStore):
        super().__init__(address, handler)
        self.app_dir = app_dir
        self.bundle_dir = bundle_dir
        self.store = store


class GeometryReviewHandler(BaseHTTPRequestHandler):
    server: _ReviewServer

    def _json(self, status: HTTPStatus, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _static(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        payload = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    @staticmethod
    def _safe_child(root: Path, relative: str) -> Path | None:
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            return None
        return candidate

    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/health":
            self._json(HTTPStatus.OK, {"ok": True})
            return
        if path == "/api/reviews":
            try:
                self._json(HTTPStatus.OK, self.server.store.response())
            except ValueError as exc:
                self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
            return
        if path == "/data/review-data.json":
            self._static(self.server.store.bundle_path)
            return
        if path.startswith("/assets/"):
            child = self._safe_child(self.server.bundle_dir, path.lstrip("/"))
            if child is None:
                self.send_error(HTTPStatus.BAD_REQUEST)
            else:
                self._static(child)
            return
        relative = "index.html" if path == "/" else path.lstrip("/")
        child = self._safe_child(self.server.app_dir, relative)
        if child is None:
            self.send_error(HTTPStatus.BAD_REQUEST)
        else:
            self._static(child)

    def do_POST(self) -> None:  # noqa: N802
        if urllib.parse.urlparse(self.path).path != "/api/reviews":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 1024 * 1024:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid request size"})
            return
        try:
            value = json.loads(self.rfile.read(length))
            record = self.server.store.append(value)
        except (json.JSONDecodeError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._json(HTTPStatus.CREATED, record)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"review-server {self.address_string()} {format % args}")


def serve_geometry_review(
    bundle_dir: str | Path,
    reviews_path: str | Path,
    *,
    app_dir: str | Path,
    host: str = "127.0.0.1",
    port: int = 8766,
) -> None:
    bundle_dir = Path(bundle_dir).resolve()
    app_dir = Path(app_dir).resolve()
    store = HumanReviewStore(bundle_dir / "review-data.json", reviews_path)
    if app_dir != (bundle_dir / "app").resolve():
        raise ValueError("The review server must use the frozen app stored inside the bundle")
    server = _ReviewServer((host, port), GeometryReviewHandler, app_dir=app_dir, bundle_dir=bundle_dir, store=store)
    print(f"Geometry Review Workbench: http://{host}:{port}/")
    print(f"Review ledger: {store.reviews_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
