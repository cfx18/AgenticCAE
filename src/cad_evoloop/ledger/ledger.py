"""Append-only trajectory records with content-addressed CAD artifacts."""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import time
from typing import Any, Callable, Iterable, Iterator
import uuid


SCHEMA_VERSION = "1.0"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SECRET_KEYS = ("authorization", "cookie", "password", "secret", "token", "api_key", "apikey")
FILE_ACCESS_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.6, 3.2, 5.0, 5.0)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def retry_file_access(operation: Callable[[], Any]) -> Any:
    """Retry transient Windows sharing violations without hiding persistent failures."""
    for delay in (*FILE_ACCESS_RETRY_DELAYS, None):
        try:
            return operation()
        except PermissionError:
            if delay is None:
                raise
            time.sleep(delay)
    raise AssertionError("unreachable")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if any(token in key.casefold() for token in SECRET_KEYS) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def validate_identifier(value: str, label: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must match {IDENTIFIER.pattern}")
    return value


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


@contextlib.contextmanager
def file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class RunLedger:
    def __init__(self, eval_root: str | Path) -> None:
        self.eval_root = Path(eval_root).resolve()
        self.workspace_root = self.eval_root.parents[1]
        self.records_root = self.eval_root / "records"
        self.index_path = self.records_root / "run-index.sqlite3"

    def _git_state(self) -> dict[str, Any]:
        try:
            root = subprocess.run(
                ["git", "-C", str(self.workspace_root), "rev-parse", "--show-toplevel"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            commit = subprocess.run(
                ["git", "-C", root, "rev-parse", "HEAD"],
                check=False,
                capture_output=True,
                text=True,
            ).stdout.strip() or None
            dirty = bool(subprocess.run(
                ["git", "-C", root, "status", "--porcelain"],
                check=False,
                capture_output=True,
                text=True,
            ).stdout)
            return {"root": root, "commit": commit, "dirty": dirty}
        except (FileNotFoundError, subprocess.CalledProcessError):
            return {"root": None, "commit": None, "dirty": None}

    def _connect(self) -> sqlite3.Connection:
        self.records_root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.index_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                sample_id TEXT NOT NULL,
                parent_run_id TEXT,
                status TEXT NOT NULL,
                score REAL,
                coverage REAL,
                eqc REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source_digest TEXT NOT NULL,
                relative_path TEXT NOT NULL
            )
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        if "eqc" not in columns:
            connection.execute("ALTER TABLE runs ADD COLUMN eqc REAL")
        connection.execute("CREATE INDEX IF NOT EXISTS runs_sample_id ON runs(sample_id, created_at)")
        return connection

    def _update_index(self, manifest: dict[str, Any], run_dir: Path) -> None:
        result = manifest.get("result") or {}
        with contextlib.closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, sample_id, parent_run_id, status, score, coverage, eqc,
                    created_at, updated_at, source_digest, relative_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status=excluded.status,
                    score=excluded.score,
                    coverage=excluded.coverage,
                    eqc=excluded.eqc,
                    updated_at=excluded.updated_at,
                    source_digest=excluded.source_digest,
                    relative_path=excluded.relative_path
                """,
                (
                    manifest["run_id"], manifest["sample_id"], manifest.get("parent_run_id"),
                    manifest["status"], result.get("score"), result.get("coverage"), result.get("eqc"),
                    manifest["created_at"], manifest["updated_at"], manifest["source"]["digest"],
                    run_dir.relative_to(self.eval_root).as_posix(),
                ),
            )
            connection.commit()

    def _resolve_run(self, run: str | Path) -> Path:
        candidate = Path(run)
        if candidate.is_dir() and (candidate / "run.json").is_file():
            return candidate.resolve()
        matches = list(self.records_root.glob(f"*/{run}"))
        if len(matches) != 1:
            raise FileNotFoundError(f"Expected one run named {run!s}, found {len(matches)}")
        return matches[0].resolve()

    def _snapshot_file(self, source: Path, destination_root: Path, category: str) -> dict[str, Any]:
        source = source.resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        try:
            relative = source.relative_to(self.workspace_root)
        except ValueError:
            relative = Path("external") / source.name
        destination = destination_root / category / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        retry_file_access(lambda: shutil.copy2(source, destination))
        return {
            "source_path": source.as_posix(),
            "stored_path": destination.relative_to(destination_root).as_posix(),
            "sha256": sha256_file(destination),
            "bytes": destination.stat().st_size,
        }

    @staticmethod
    def _source_digest(records: Iterable[dict[str, Any]]) -> str:
        digest = hashlib.sha256()
        for record in sorted(records, key=lambda item: item["stored_path"]):
            digest.update(record["stored_path"].encode("utf-8"))
            digest.update(record["sha256"].encode("ascii"))
        return digest.hexdigest()

    def start(
        self,
        sample_id: str,
        *,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        agent: dict[str, Any] | None = None,
        source_paths: Iterable[str | Path] = (),
        input_paths: Iterable[str | Path] = (),
    ) -> Path:
        validate_identifier(sample_id, "sample_id")
        run_id = validate_identifier(
            run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8],
            "run_id",
        )
        if parent_run_id:
            validate_identifier(parent_run_id, "parent_run_id")
        sample_dir = self.eval_root / "samples" / sample_id
        if not sample_dir.is_dir():
            raise FileNotFoundError(sample_dir)
        run_dir = self.records_root / sample_id / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "attempts").mkdir()
        (run_dir / "source").mkdir()
        (run_dir / "inputs").mkdir()

        default_inputs = [
            sample_dir / name for name in ("task_desc.json", "rubrics.json", "metadata.json")
            if (sample_dir / name).is_file()
        ]
        sources = [self._snapshot_file(Path(path), run_dir, "source") for path in source_paths]
        inputs = [
            self._snapshot_file(Path(path), run_dir, "inputs")
            for path in [*default_inputs, *(Path(path) for path in input_paths)]
        ]
        now = utc_now()
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "sample_id": sample_id,
            "parent_run_id": parent_run_id,
            "status": "running",
            "created_at": now,
            "updated_at": now,
            "agent": redact(agent or {"system": "codex"}),
            "source": {
                "git": self._git_state(),
                "digest": self._source_digest(sources),
                "files": sources,
            },
            "inputs": inputs,
            "attempts": [],
            "result": None,
            "event_count": 0,
        }
        write_json_atomic(run_dir / "run.json", manifest)
        self._append_event_locked(run_dir, "run.started", "pass", "Run record created", "system", None, {})
        return run_dir

    def _append_event_unlocked(
        self,
        run_dir: Path,
        event_type: str,
        status: str,
        summary: str,
        actor: str,
        attempt_id: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        event = {
            "schema_version": SCHEMA_VERSION,
            "event_id": uuid.uuid4().hex,
            "sequence": int(manifest.get("event_count", 0)) + 1,
            "timestamp": utc_now(),
            "run_id": manifest["run_id"],
            "attempt_id": attempt_id,
            "actor": actor,
            "type": event_type,
            "status": status,
            "summary": summary,
            "payload": redact(payload),
        }
        with (run_dir / "trajectory.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        manifest["event_count"] = event["sequence"]
        manifest["updated_at"] = event["timestamp"]
        write_json_atomic(run_dir / "run.json", manifest)
        self._update_index(manifest, run_dir)
        return event

    def _append_event_locked(self, run_dir: Path, *args: Any) -> dict[str, Any]:
        with file_lock(run_dir / ".ledger.lock"):
            return self._append_event_unlocked(run_dir, *args)

    def event(
        self,
        run: str | Path,
        event_type: str,
        summary: str,
        *,
        status: str = "pass",
        actor: str = "agent",
        attempt_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_dir = self._resolve_run(run)
        return self._append_event_locked(
            run_dir, event_type, status, summary, actor, attempt_id, payload or {},
        )

    def add_attempt(
        self,
        run: str | Path,
        *,
        label: str,
        status: str = "running",
        parent_attempt_id: str | None = None,
        summary: str = "",
    ) -> str:
        run_dir = self._resolve_run(run)
        with file_lock(run_dir / ".ledger.lock"):
            manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            attempt_id = f"a{len(manifest['attempts']) + 1:03d}"
            if parent_attempt_id is None and manifest["attempts"]:
                parent_attempt_id = manifest["attempts"][-1]["attempt_id"]
            attempt = {
                "attempt_id": attempt_id,
                "parent_attempt_id": parent_attempt_id,
                "label": label,
                "status": status,
                "summary": summary,
                "created_at": utc_now(),
                "artifacts": [],
                "verification": None,
            }
            manifest["attempts"].append(attempt)
            manifest["updated_at"] = attempt["created_at"]
            write_json_atomic(run_dir / "run.json", manifest)
            self._append_event_unlocked(
                run_dir, "attempt.started", status, summary or label, "agent", attempt_id,
                {"label": label, "parent_attempt_id": parent_attempt_id},
            )
        return attempt_id

    def add_artifact(
        self,
        run: str | Path,
        attempt_id: str,
        path: str | Path,
        *,
        role: str,
        copy: bool = True,
    ) -> dict[str, Any]:
        run_dir = self._resolve_run(run)
        source = Path(path).resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        validate_identifier(attempt_id, "attempt_id")
        safe_role = validate_identifier(role, "role")
        with file_lock(run_dir / ".ledger.lock"):
            manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            attempt = next((item for item in manifest["attempts"] if item["attempt_id"] == attempt_id), None)
            if attempt is None:
                raise KeyError(f"Unknown attempt: {attempt_id}")
            if copy:
                destination = run_dir / "attempts" / attempt_id / safe_role / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                source_digest = retry_file_access(lambda: sha256_file(source))
                if destination.exists() and sha256_file(destination) != source_digest:
                    destination = destination.with_name(f"{destination.stem}-{uuid.uuid4().hex[:8]}{destination.suffix}")
                if source != destination:
                    retry_file_access(lambda: shutil.copy2(source, destination))
                stored_path = destination.relative_to(run_dir).as_posix()
                digest_path = destination
            else:
                try:
                    stored_path = source.relative_to(self.workspace_root).as_posix()
                except ValueError:
                    stored_path = source.as_posix()
                digest_path = source
            record = {
                "role": role,
                "stored_path": stored_path,
                "storage": "copy" if copy else "reference",
                "source_path": source.as_posix(),
                "sha256": retry_file_access(lambda: sha256_file(digest_path)),
                "bytes": digest_path.stat().st_size,
                "created_at": utc_now(),
            }
            attempt["artifacts"].append(record)
            manifest["updated_at"] = record["created_at"]
            write_json_atomic(run_dir / "run.json", manifest)
            self._append_event_unlocked(
                run_dir, "artifact.recorded", "pass", f"Recorded {role}: {source.name}",
                "system", attempt_id, record,
            )
        return record

    def finish(
        self,
        run: str | Path,
        attempt_id: str,
        verdict_path: str | Path,
    ) -> dict[str, Any]:
        verdict_path = Path(verdict_path).resolve()
        verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        eqc = verdict.get("eqc") or {}
        artifact = self.add_artifact(run, attempt_id, verdict_path, role="verdict")
        run_dir = self._resolve_run(run)
        with file_lock(run_dir / ".ledger.lock"):
            manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            attempt = next(item for item in manifest["attempts"] if item["attempt_id"] == attempt_id)
            legacy_status = "passed" if verdict.get("passed") else "failed"
            status = (
                "passed" if eqc.get("success") is True
                else "failed" if eqc.get("success") is False
                else legacy_status
            )
            result = {
                "status": status,
                "legacy_status": legacy_status,
                "score": verdict.get("score"),
                "coverage": verdict.get("coverage"),
                "eqc": eqc.get("eqc"),
                "eqc_success": eqc.get("success"),
                "evaluation_status": (
                    "passed" if eqc.get("success") is True
                    else "failed" if eqc.get("success") is False
                    else "unavailable"
                ),
                "verdict_artifact": artifact["stored_path"],
                "verdict_sha256": artifact["sha256"],
            }
            attempt["status"] = status
            attempt["verification"] = result
            attempt["completed_at"] = utc_now()
            manifest["status"] = status
            manifest["result"] = result
            manifest["updated_at"] = attempt["completed_at"]
            write_json_atomic(run_dir / "run.json", manifest)
            self._append_event_unlocked(
                run_dir, "verifier.completed", status, f"Verifier score: {result['score']}",
                "verifier", attempt_id, result,
            )
        return result

    def select_attempt(self, run: str | Path, attempt_id: str) -> dict[str, Any]:
        """Select a verified checkpoint as the run result without deleting later attempts."""
        run_dir = self._resolve_run(run)
        validate_identifier(attempt_id, "attempt_id")
        with file_lock(run_dir / ".ledger.lock"):
            manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            attempt = next(
                (item for item in manifest["attempts"] if item["attempt_id"] == attempt_id),
                None,
            )
            if attempt is None or not attempt.get("verification"):
                raise ValueError(f"Attempt is not verified: {attempt_id}")
            result = {**attempt["verification"], "selected_attempt_id": attempt_id}
            manifest["status"] = result["status"]
            manifest["result"] = result
            manifest["selected_attempt_id"] = attempt_id
            manifest["updated_at"] = utc_now()
            write_json_atomic(run_dir / "run.json", manifest)
            self._append_event_unlocked(
                run_dir,
                "run.selection",
                result["status"],
                f"Selected checkpoint {attempt_id} with EQC {result.get('eqc')}",
                "supervisor",
                attempt_id,
                result,
            )
        return result

    def verify_integrity(self, run: str | Path) -> dict[str, Any]:
        run_dir = self._resolve_run(run)
        manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        checked = 0
        errors = []
        records = [*manifest["source"]["files"], *manifest["inputs"]]
        for attempt in manifest["attempts"]:
            records.extend(attempt["artifacts"])
        for record in records:
            stored = Path(record["stored_path"])
            if record.get("storage") == "reference":
                path = self.workspace_root / stored if not stored.is_absolute() else stored
            else:
                path = (run_dir / stored).resolve()
                try:
                    path.relative_to(run_dir)
                except ValueError:
                    errors.append({"path": str(path), "error": "stored path escaped run directory"})
                    continue
            checked += 1
            if not path.is_file():
                errors.append({"path": str(path), "error": "missing"})
                continue
            actual = sha256_file(path)
            if actual != record["sha256"]:
                errors.append({"path": str(path), "error": "sha256 mismatch", "actual": actual})
        trajectory_lines = (run_dir / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()
        if len(trajectory_lines) != manifest["event_count"]:
            errors.append({
                "path": "trajectory.jsonl", "error": "event count mismatch",
                "expected": manifest["event_count"], "actual": len(trajectory_lines),
            })
        event_ids = set()
        for index, line in enumerate(trajectory_lines, start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append({"path": "trajectory.jsonl", "line": index, "error": str(exc)})
                continue
            if event.get("sequence") != index:
                errors.append({
                    "path": "trajectory.jsonl", "line": index, "error": "non-contiguous sequence",
                    "actual": event.get("sequence"),
                })
            if event.get("run_id") != manifest["run_id"]:
                errors.append({"path": "trajectory.jsonl", "line": index, "error": "run_id mismatch"})
            event_id = event.get("event_id")
            if not event_id or event_id in event_ids:
                errors.append({"path": "trajectory.jsonl", "line": index, "error": "duplicate or missing event_id"})
            event_ids.add(event_id)
        return {"ok": not errors, "checked_files": checked, "events": len(trajectory_lines), "errors": errors}

    def reindex(self) -> int:
        if self.index_path.exists():
            self.index_path.unlink()
        count = 0
        for manifest_path in self.records_root.glob("*/*/run.json"):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self._update_index(manifest, manifest_path.parent)
            count += 1
        return count

    def ingest_mcp_audit(
        self,
        run: str | Path,
        audit_path: str | Path | None = None,
    ) -> dict[str, int]:
        run_dir = self._resolve_run(run)
        manifest = self.show(run_dir)
        path = Path(audit_path).resolve() if audit_path else self.records_root / "mcp-audit.jsonl"
        if not path.is_file():
            return {"matched": 0, "imported": 0, "duplicates": 0}
        existing_ids = set()
        for line in (run_dir / "trajectory.jsonl").read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            source_id = event.get("payload", {}).get("mcp_audit_event_id")
            if source_id:
                existing_ids.add(source_id)
        matched = imported = duplicates = 0
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("run_id") != manifest["run_id"]:
                continue
            matched += 1
            source_id = event.get("event_id")
            if source_id in existing_ids:
                duplicates += 1
                continue
            self.event(
                run_dir,
                "tool.call",
                f"AutoCAD MCP: {event.get('tool', 'unknown')}",
                status=str(event.get("status", "unknown")),
                actor="autocad-mcp",
                attempt_id=event.get("attempt_id"),
                payload={
                    "mcp_audit_event_id": source_id,
                    "observed_at": event.get("timestamp"),
                    "tool": event.get("tool"),
                    "duration_ms": event.get("duration_ms"),
                    "arguments": event.get("arguments", {}),
                    "response": event.get("response"),
                    "audit_line": line_number,
                },
            )
            existing_ids.add(source_id)
            imported += 1
        return {"matched": matched, "imported": imported, "duplicates": duplicates}

    def list_runs(self, sample_id: str | None = None) -> list[dict[str, Any]]:
        query = (
            "SELECT run_id, sample_id, parent_run_id, status, score, coverage, eqc, "
            "created_at, updated_at, source_digest, relative_path FROM runs"
        )
        parameters: tuple[Any, ...] = ()
        if sample_id:
            query += " WHERE sample_id = ?"
            parameters = (sample_id,)
        query += " ORDER BY created_at DESC"
        with contextlib.closing(self._connect()) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(query, parameters)]

    def reusable_artifact(
        self,
        sample_id: str,
        *,
        role: str = "candidate",
        output: str | Path | None = None,
    ) -> dict[str, Any]:
        candidates = [row for row in self.list_runs(sample_id) if row["status"] == "passed"]
        candidates.sort(
            key=lambda row: (row["score"] if row["score"] is not None else -1, row["updated_at"]),
            reverse=True,
        )
        for candidate in candidates:
            run_dir = self.eval_root / candidate["relative_path"]
            manifest = self.show(run_dir)
            for attempt in reversed(manifest["attempts"]):
                for artifact in reversed(attempt["artifacts"]):
                    if artifact["role"] != role:
                        continue
                    stored = Path(artifact["stored_path"])
                    if artifact.get("storage") == "reference":
                        source = (self.workspace_root / stored).resolve() if not stored.is_absolute() else stored.resolve()
                        try:
                            source.relative_to(self.workspace_root)
                        except ValueError:
                            continue
                    else:
                        source = (run_dir / stored).resolve()
                        try:
                            source.relative_to(run_dir)
                        except ValueError:
                            continue
                    if not source.is_file() or sha256_file(source) != artifact["sha256"]:
                        continue
                    result = {
                        "run_id": manifest["run_id"],
                        "attempt_id": attempt["attempt_id"],
                        "score": candidate["score"],
                        "coverage": candidate["coverage"],
                        "eqc": candidate["eqc"],
                        "role": role,
                        "path": str(source),
                        "sha256": artifact["sha256"],
                    }
                    if output is not None:
                        destination = Path(output).resolve()
                        try:
                            destination.relative_to(self.workspace_root)
                        except ValueError as exc:
                            raise ValueError("reuse output must stay inside the workspace") from exc
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, destination)
                        result["output"] = str(destination)
                    return result
        raise FileNotFoundError(f"No verified {role!r} artifact for sample {sample_id}")

    def diff_runs(self, from_run: str | Path, to_run: str | Path) -> dict[str, Any]:
        before = self.show(from_run)
        after = self.show(to_run)
        before_files = {item["source_path"]: item for item in before["source"]["files"]}
        after_files = {item["source_path"]: item for item in after["source"]["files"]}
        before_paths = set(before_files)
        after_paths = set(after_files)
        changed = []
        for path in sorted(before_paths & after_paths):
            if before_files[path]["sha256"] != after_files[path]["sha256"]:
                changed.append({
                    "path": path,
                    "from_sha256": before_files[path]["sha256"],
                    "to_sha256": after_files[path]["sha256"],
                })
        before_result = before.get("result") or {}
        after_result = after.get("result") or {}
        return {
            "from_run": before["run_id"],
            "to_run": after["run_id"],
            "source": {
                "from_digest": before["source"]["digest"],
                "to_digest": after["source"]["digest"],
                "added": sorted(after_paths - before_paths),
                "removed": sorted(before_paths - after_paths),
                "changed": changed,
            },
            "result": {
                "from_status": before["status"],
                "to_status": after["status"],
                "score_delta": (
                    after_result["score"] - before_result["score"]
                    if isinstance(before_result.get("score"), (int, float))
                    and isinstance(after_result.get("score"), (int, float))
                    else None
                ),
                "coverage_delta": (
                    after_result["coverage"] - before_result["coverage"]
                    if isinstance(before_result.get("coverage"), (int, float))
                    and isinstance(after_result.get("coverage"), (int, float))
                    else None
                ),
            },
        }

    def show(self, run: str | Path) -> dict[str, Any]:
        run_dir = self._resolve_run(run)
        return json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
