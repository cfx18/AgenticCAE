"""Versioned candidate workspace and Codex supervisor for adaptive CAD runs."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from ..protocol.adaptive import ACTION_SCHEMA, build_diagnostic, sha256, validate_action


SESSION_FILES = {
    "prompt": (
        "evals/cad-1000-hours/prompts/modeling.md",
        "evals/cad-1000-hours/prompts/repair.md",
    ),
    "skill": (
        ".agents/skills/autocad-image-modeling/SKILL.md",
        ".agents/skills/autocad-image-modeling/scripts/autocad_mcp_server.py",
    ),
    "mcp": (
        "src/cad_evoloop/backends/autocad/audited.py",
        "src/cad_evoloop/backends/autocad/jobs.py",
        "src/cad_evoloop/backends/autocad/core_console.py",
    ),
    "verifier": (
        "src/cad_evoloop/verification/verify.py",
        "src/cad_evoloop/verification/extract_autocad.py",
        "src/cad_evoloop/verification/extract_core_console.py",
    ),
}

TEXT_SUFFIXES = {".json", ".md", ".py", ".txt"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


class AdaptiveSession:
    def __init__(self, eval_root: Path, session_id: str, *, create: bool = False) -> None:
        self.eval_root = Path(eval_root).resolve()
        self.workspace_root = self.eval_root.parents[1]
        self.root = self.eval_root / "improvement" / "adaptive" / session_id
        self.workspace = self.root / "workspace"
        self.manifest_path = self.root / "manifest.json"
        self.schema_path = self.root / "action.schema.json"
        if create and not self.manifest_path.is_file():
            self._create(session_id)
        if not self.manifest_path.is_file():
            raise FileNotFoundError(self.manifest_path)
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        write_json(self.schema_path, ACTION_SCHEMA)

    @property
    def allowed_files(self) -> dict[str, set[str]]:
        return {component: set(paths) for component, paths in self.manifest["allowed_files"].items()}

    def _create(self, session_id: str) -> None:
        if not session_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in session_id):
            raise ValueError("Invalid adaptive session identifier")
        self.workspace.mkdir(parents=True, exist_ok=False)
        files = []
        for component, paths in SESSION_FILES.items():
            for relative in paths:
                source = self.workspace_root / relative
                destination = self.workspace / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                files.append({"component": component, "path": relative, "initial_sha256": sha256(destination)})
        write_json(self.schema_path, ACTION_SCHEMA)
        write_json(self.manifest_path, {
            "schema_version": "1.0",
            "session_id": session_id,
            "status": "active",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "iteration": 0,
            "allowed_files": {key: list(value) for key, value in SESSION_FILES.items()},
            "files": files,
            "versions": [],
            "decisions": [],
        })

    def path(self, relative: str) -> Path:
        candidate = (self.workspace / relative).resolve()
        candidate.relative_to(self.workspace)
        return candidate

    def source_paths(self) -> tuple[Path, ...]:
        return tuple(self.path(record["path"]) for record in self.manifest["files"])

    def _planner_prompt(self, diagnostic: dict[str, Any]) -> str:
        return f"""You supervise an adaptive AutoCAD agent. Choose the next action from available_actions using the complete diagnostic below.

Success means choosing the action that addresses the diagnosed owner with the least unnecessary work. Treat process failures as system evidence, not drawing failures. You may recommend a candidate-system patch, but production source, original task/rubrics, holdout data, historical trajectories, and the independent final evaluator are immutable. Do not edit files in this planning turn. Return only the JSON object required by the supplied output schema.

Allowed candidate files by component:
{json.dumps({key: sorted(value) for key, value in self.allowed_files.items()}, indent=2)}

Diagnostic:
{json.dumps(diagnostic, indent=2, ensure_ascii=False)}
"""

    def decide(
        self,
        diagnostic: dict[str, Any],
        *,
        model: str,
        effort: str,
        executable: str = "codex",
        timeout: int = 900,
    ) -> dict[str, Any]:
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        existing_iterations = [
            int(path.name[1:]) for path in (self.root / "decisions").glob("i[0-9][0-9][0-9]")
            if path.is_dir()
        ] if (self.root / "decisions").is_dir() else []
        iteration = max([int(self.manifest.get("iteration", 0)), *existing_iterations]) + 1
        decision_dir = self.root / "decisions" / f"i{iteration:03d}"
        decision_dir.mkdir(parents=True, exist_ok=False)
        diagnostic_path = decision_dir / "diagnostic.json"
        action_path = decision_dir / "action.json"
        events_path = decision_dir / "planner-events.jsonl"
        stderr_path = decision_dir / "planner-stderr.log"
        write_json(diagnostic_path, diagnostic)
        command = [
            executable, "exec", "--ephemeral", "--skip-git-repo-check",
            "--ignore-user-config", "--ignore-rules", "--sandbox", "read-only",
            "--model", model, "--cd", str(self.root),
            "-c", f'model_reasoning_effort="{effort}"',
            "--output-schema", str(self.schema_path),
            "--json", "--output-last-message", str(action_path),
            self._planner_prompt(diagnostic),
        ]
        with events_path.open("w", encoding="utf-8", newline="\n") as events, stderr_path.open(
            "w", encoding="utf-8", newline="\n",
        ) as errors:
            completed = subprocess.run(
                command, cwd=self.root, stdin=subprocess.DEVNULL,
                stdout=events, stderr=errors, text=True, encoding="utf-8",
                errors="replace", timeout=timeout, check=False,
            )
        if completed.returncode != 0 or not action_path.is_file():
            self.manifest["iteration"] = iteration
            self.manifest["updated_at"] = utc_now()
            self.manifest["decisions"].append({
                "iteration": iteration,
                "created_at": utc_now(),
                "diagnostic": diagnostic_path.relative_to(self.root).as_posix(),
                "action": None,
                "action_name": None,
                "owner": None,
                "planner_return_code": completed.returncode,
                "status": "planner-failed",
            })
            write_json(self.manifest_path, self.manifest)
            raise RuntimeError(f"Adaptive supervisor failed with exit code {completed.returncode}")
        action = validate_action(json.loads(action_path.read_text(encoding="utf-8")), self.allowed_files)
        if action["action"] not in diagnostic.get("available_actions", []):
            raise ValueError(
                f"Supervisor chose {action['action']} outside diagnostic available_actions"
            )
        record = {
            "iteration": iteration,
            "created_at": utc_now(),
            "diagnostic": diagnostic_path.relative_to(self.root).as_posix(),
            "action": action_path.relative_to(self.root).as_posix(),
            "action_name": action["action"],
            "owner": action["owner"],
            "planner_return_code": completed.returncode,
        }
        self.manifest["iteration"] = iteration
        self.manifest["updated_at"] = utc_now()
        self.manifest["decisions"].append(record)
        write_json(self.manifest_path, self.manifest)
        return action

    def _snapshot(self, destination: Path) -> dict[str, str]:
        hashes = {}
        for paths in self.allowed_files.values():
            for relative in paths:
                source = self.path(relative)
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                hashes[relative] = sha256(source)
        return hashes

    def _normalize_approved_text_files(self, paths: list[str]) -> None:
        """Remove BOMs introduced by Windows editing tools before validation."""
        for relative in paths:
            candidate = self.path(relative)
            if not candidate.is_file() or candidate.suffix.lower() not in TEXT_SUFFIXES:
                continue
            raw = candidate.read_bytes()
            if raw.startswith(b"\xef\xbb\xbf"):
                text = raw.decode("utf-8-sig").lstrip("\ufeff")
                candidate.write_bytes(text.encode("utf-8"))

    def _remove_transient_artifacts(self) -> None:
        for name in ("__pycache__", ".pytest_cache"):
            for directory in sorted(self.workspace.rglob(name), reverse=True):
                if directory.is_dir():
                    shutil.rmtree(directory)
        for path in self.workspace.rglob("*.pyc"):
            if path.is_file():
                path.unlink()

    def _restore_snapshot(
        self,
        before_dir: Path,
        before_hashes: dict[str, str],
        extra_files: set[str],
    ) -> None:
        for relative in before_hashes:
            target = self.path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(before_dir / relative, target)
        for relative in extra_files:
            target = self.path(relative)
            if target.is_file():
                target.unlink()
        self._remove_transient_artifacts()

    def apply_patch(
        self,
        action: dict[str, Any],
        diagnostic: dict[str, Any],
        *,
        model: str,
        effort: str,
        executable: str = "codex",
        timeout: int = 1800,
    ) -> dict[str, Any]:
        action = validate_action(action, self.allowed_files)
        if not action["action"].startswith("patch_") and action["action"] != "add_test":
            return {"status": "not-applicable", "action": action["action"]}
        iteration = int(self.manifest.get("iteration", 0))
        decision_dir = self.root / "decisions" / f"i{iteration:03d}"
        before_dir = self.root / "versions" / f"v{iteration:03d}-before"
        before_hashes = self._snapshot(before_dir)
        known_files = set(before_hashes)
        events_path = decision_dir / "modifier-events.jsonl"
        stderr_path = decision_dir / "modifier-stderr.log"
        final_path = decision_dir / "modifier-final.txt"
        allowed = action["files"]
        prompt = f"""Apply the approved adaptive CAD system change in this isolated candidate workspace.

Edit only these files: {json.dumps(allowed)}
Do not access production source, datasets, rubrics, holdout data, batch outputs, or historical records. Implement the requested change, keep behavior general, and do not weaken evaluation criteria.
Preserve existing line endings where practical. Write text as UTF-8 without a byte-order mark.

Approved action:
{json.dumps(action, indent=2, ensure_ascii=False)}

Diagnostic evidence:
{json.dumps(diagnostic, indent=2, ensure_ascii=False)}
"""
        command = [
            executable, "exec", "--ephemeral", "--skip-git-repo-check",
            "--ignore-user-config", "--ignore-rules", "--approve-for-me",
            "--model", model, "--cd", str(self.workspace),
            "-c", f'model_reasoning_effort="{effort}"',
            "--json", "--output-last-message", str(final_path), prompt,
        ]
        with events_path.open("w", encoding="utf-8", newline="\n") as events, stderr_path.open(
            "w", encoding="utf-8", newline="\n",
        ) as errors:
            completed = subprocess.run(
                command, cwd=self.workspace, stdin=subprocess.DEVNULL,
                stdout=events, stderr=errors, text=True, encoding="utf-8",
                errors="replace", timeout=timeout, check=False,
            )
        self._normalize_approved_text_files(allowed)
        self._remove_transient_artifacts()
        workspace_files = {
            path.relative_to(self.workspace).as_posix(): path
            for path in self.workspace.rglob("*") if path.is_file()
        }
        allowed_new = set(allowed) if action["action"] == "add_test" else set()
        missing_existing = sorted(known_files - set(workspace_files))
        unexpected = sorted(set(workspace_files) - known_files - allowed_new)
        tracked = known_files | allowed_new
        after_hashes = {
            relative: sha256(self.path(relative))
            for relative in tracked if self.path(relative).is_file()
        }
        changed = sorted(
            relative for relative in tracked
            if after_hashes.get(relative) != before_hashes.get(relative)
        )
        unauthorized = sorted(set(changed) - set(allowed))
        boundary_errors = []
        if missing_existing:
            boundary_errors.append(f"Modifier deleted managed files: {missing_existing}")
        if unexpected:
            boundary_errors.append(f"Modifier created unauthorized files: {unexpected}")
        if unauthorized:
            boundary_errors.append(f"Modifier changed unauthorized files: {unauthorized}")
        if completed.returncode != 0:
            boundary_errors.append(f"Adaptive modifier failed with exit code {completed.returncode}")
        if not changed:
            boundary_errors.append("Adaptive modifier completed without changing an approved file")
        test_result = (
            {
                "passed": False,
                "return_code": completed.returncode or 1,
                "targets": [],
                "errors": boundary_errors,
            }
            if boundary_errors
            else self.run_validation(action["component"], action.get("files", ()))
        )
        version = {
            "iteration": iteration,
            "created_at": utc_now(),
            "action": action["action"],
            "changed_files": changed,
            "before_hashes": {key: before_hashes.get(key) for key in changed},
            "after_hashes": {key: after_hashes.get(key) for key in changed},
            "tests": test_result,
            "rolled_back": not test_result["passed"],
        }
        if not test_result["passed"]:
            self._restore_snapshot(
                before_dir,
                before_hashes,
                set(workspace_files) - known_files,
            )
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if test_result["passed"] and action["action"] == "add_test":
            test_files = self.manifest["allowed_files"].setdefault("test", [])
            recorded_paths = {record["path"] for record in self.manifest["files"]}
            for relative in changed:
                if relative not in test_files:
                    test_files.append(relative)
                if relative not in recorded_paths:
                    self.manifest["files"].append({
                        "component": "test",
                        "path": relative,
                        "initial_sha256": after_hashes[relative],
                    })
        self.manifest["versions"].append(version)
        self.manifest["updated_at"] = utc_now()
        self.manifest["status"] = "active" if test_result["passed"] else "validation-failed"
        write_json(self.manifest_path, self.manifest)
        write_json(decision_dir / "patch-result.json", version)
        return version

    def run_validation(self, component: str | None, files: Any = ()) -> dict[str, Any]:
        commands = {
            "prompt": [],
            "skill": [self.workspace_root / "mcp/tests"],
            "mcp": [self.workspace_root / "mcp/tests"],
            "verifier": [self.eval_root / "verifier/tests"],
        }
        targets = commands.get(component, [])
        if component == "test":
            targets = [str(self.workspace / path) for path in files]
        syntax_errors = []
        for relative in files:
            candidate = self.path(relative)
            if candidate.suffix == ".py" and candidate.is_file():
                try:
                    compile(candidate.read_text(encoding="utf-8"), str(candidate), "exec")
                except SyntaxError as exc:
                    syntax_errors.append(str(exc))
        if component == "prompt":
            from string import Template

            required = {
                "evals/cad-1000-hours/prompts/modeling.md": {
                    "sample_id", "run_id", "attempt_id", "skill_path",
                    "geometry_checkpoint", "annotation_checkpoint", "candidate",
                },
                "evals/cad-1000-hours/prompts/repair.md": {
                    "sample_id", "run_id", "attempt_id", "previous_candidate",
                    "previous_verdict", "previous_diagnostic", "candidate", "reflection",
                },
            }
            for relative in files:
                if relative in required:
                    template = Template(self.path(relative).read_text(encoding="utf-8"))
                    if not template.is_valid() or set(template.get_identifiers()) != required[relative]:
                        syntax_errors.append(f"Invalid prompt placeholders: {relative}")
        if syntax_errors:
            return {"passed": False, "return_code": 1, "targets": [], "errors": syntax_errors}
        if not targets:
            return {"passed": True, "return_code": 0, "targets": []}
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join((
            str(self.workspace / "src"),
            str(self.workspace),
            str(self.workspace / "evals/cad-1000-hours"),
            str(self.eval_root),
        ))
        completed = subprocess.run(
            [shutil.which("python") or "python", "-m", "pytest", *(str(item) for item in targets), "-q"],
            cwd=self.workspace, capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, timeout=300, check=False,
        )
        return {
            "passed": completed.returncode == 0,
            "return_code": completed.returncode,
            "targets": [str(item) for item in targets],
            "stdout_tail": completed.stdout[-8000:],
            "stderr_tail": completed.stderr[-8000:],
        }
