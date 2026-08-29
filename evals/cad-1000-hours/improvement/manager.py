"""Controlled self-improvement proposals for the CAD agent system."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import re
import shutil
from string import Template
import subprocess
from typing import Any, Iterable


EVAL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = EVAL_ROOT.parents[1]
IMPROVEMENT_ROOT = EVAL_ROOT / "improvement"
PROPOSALS_ROOT = IMPROVEMENT_ROOT / "proposals"
RELEASES_ROOT = IMPROVEMENT_ROOT / "releases"
SPLIT_PATH = IMPROVEMENT_ROOT / "split.json"
CURRENT_PATH = IMPROVEMENT_ROOT / "current.json"
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

COMPONENT_FILES = {
    "prompt": (
        "evals/cad-1000-hours/prompts/modeling.md",
        "evals/cad-1000-hours/prompts/repair.md",
    ),
    "skill": (".agents/skills/autocad-image-modeling/SKILL.md",),
    "mcp": (
        "mcp/autocad_mcp_audited.py",
        "mcp/autocad_jobs.py",
        "mcp/autocad_core_console.py",
    ),
    "verifier": (
        "evals/cad-1000-hours/verifier/verify.py",
        "evals/cad-1000-hours/verifier/extract_core_console.py",
    ),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_json(path: Path, value: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_id(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid proposal identifier: {value!r}")
    return value


def stored_artifact(run_dir: Path, record: dict[str, Any]) -> Path:
    stored = Path(record["stored_path"])
    if record.get("storage") == "reference":
        return (WORKSPACE / stored).resolve() if not stored.is_absolute() else stored.resolve()
    return (run_dir / stored).resolve()


def diagnose(verdict: dict[str, Any], reflection: dict[str, Any] | None) -> dict[str, Any]:
    if reflection and reflection.get("failure_owner") in {
        "drawing", "prompt", "skill", "mcp", "verifier", "task",
    }:
        owner = reflection["failure_owner"]
    else:
        error = str(verdict.get("error", "")).casefold()
        dimensions = verdict.get("dimensions", [])
        if "verifier" in error or "extraction" in error:
            owner = "verifier"
        elif "core console" in error or "timeout" in error or "mcp" in error:
            owner = "mcp"
        elif any(item.get("reason") == "no unmatched native dimension" for item in dimensions):
            owner = "prompt"
        elif float(verdict.get("coverage", 0.0) or 0.0) < 60.0:
            owner = "verifier"
        else:
            owner = "drawing"
    return {
        "failure_owner": owner,
        "score": verdict.get("score"),
        "coverage": verdict.get("coverage"),
        "failed_dimensions": [
            item.get("id") for item in verdict.get("dimensions", []) if item.get("status") == "fail"
        ],
        "failed_rubrics": [
            item.get("id") for item in verdict.get("rubrics", []) if item.get("status") == "fail"
        ],
        "reflection": reflection,
    }


class ImprovementManager:
    def __init__(self, root: Path = IMPROVEMENT_ROOT) -> None:
        self.root = Path(root).resolve()
        self.proposals_root = self.root / "proposals"
        self.releases_root = self.root / "releases"
        self.split_path = self.root / "split.json"
        self.current_path = self.root / "current.json"

    def init_split(self, *, seed: int = 20260828, development: int = 40) -> dict[str, Any]:
        samples = sorted(path.name for path in (EVAL_ROOT / "samples").iterdir() if path.is_dir())
        if not 1 <= development < len(samples):
            raise ValueError("development count must leave at least one holdout sample")
        shuffled = samples[:]
        random.Random(seed).shuffle(shuffled)
        split = {
            "schema_version": "1.0",
            "seed": seed,
            "created_at": utc_now(),
            "development": sorted(shuffled[:development]),
            "holdout": sorted(shuffled[development:]),
        }
        if self.split_path.is_file():
            existing = read_json(self.split_path)
            if existing["development"] != split["development"] or existing["holdout"] != split["holdout"]:
                raise FileExistsError("A different immutable split already exists")
            return existing
        write_json(self.split_path, split)
        return split

    def split(self) -> dict[str, Any]:
        if not self.split_path.is_file():
            return self.init_split()
        return read_json(self.split_path)

    def collect_evidence(self) -> list[dict[str, Any]]:
        development = set(self.split()["development"])
        evidence: list[dict[str, Any]] = []
        for manifest_path in sorted((EVAL_ROOT / "records").glob("*/*/run.json")):
            manifest = read_json(manifest_path)
            sample_id = manifest.get("sample_id")
            if sample_id not in development:
                continue
            run_dir = manifest_path.parent
            for attempt in manifest.get("attempts", []):
                verification = attempt.get("verification")
                if not verification or verification.get("status") == "passed":
                    continue
                artifacts = attempt.get("artifacts", [])
                verdict_record = next((item for item in reversed(artifacts) if item.get("role") == "verdict"), None)
                if not verdict_record:
                    continue
                verdict_path = stored_artifact(run_dir, verdict_record)
                if not verdict_path.is_file():
                    continue
                reflection_record = next((item for item in reversed(artifacts) if item.get("role") == "reflection"), None)
                reflection = None
                if reflection_record:
                    reflection_path = stored_artifact(run_dir, reflection_record)
                    if reflection_path.is_file():
                        try:
                            reflection = read_json(reflection_path)
                        except (json.JSONDecodeError, OSError):
                            reflection = None
                verdict = read_json(verdict_path)
                evidence.append({
                    "sample_id": sample_id,
                    "run_id": manifest.get("run_id"),
                    "attempt_id": attempt.get("attempt_id"),
                    "source_digest": manifest.get("source", {}).get("digest"),
                    "diagnosis": diagnose(verdict, reflection),
                })
        return evidence

    def create_proposal(
        self,
        proposal_id: str,
        components: Iterable[str],
        *,
        minimum_evidence_samples: int = 3,
    ) -> Path:
        proposal_id = validate_id(proposal_id)
        selected = tuple(dict.fromkeys(components))
        unknown = sorted(set(selected) - set(COMPONENT_FILES))
        if unknown or not selected:
            raise ValueError(f"Unknown or empty components: {unknown}")
        proposal_dir = self.proposals_root / proposal_id
        proposal_dir.mkdir(parents=True, exist_ok=False)
        workspace = proposal_dir / "workspace"
        files: list[dict[str, Any]] = []
        for component in selected:
            for relative in COMPONENT_FILES[component]:
                source = WORKSPACE / relative
                destination = workspace / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                files.append({
                    "component": component,
                    "path": relative,
                    "before_sha256": sha256(destination),
                })
        evidence = self.collect_evidence()
        distinct_samples = sorted({item["sample_id"] for item in evidence})
        if len(distinct_samples) < minimum_evidence_samples:
            shutil.rmtree(proposal_dir)
            raise ValueError(
                f"Need evidence from {minimum_evidence_samples} development samples; found {len(distinct_samples)}"
            )
        evidence_path = proposal_dir / "evidence.json"
        write_json(evidence_path, evidence)
        manifest = {
            "schema_version": "1.0",
            "proposal_id": proposal_id,
            "status": "draft",
            "created_at": utc_now(),
            "components": list(selected),
            "files": files,
            "evidence_samples": distinct_samples,
            "evidence_sha256": sha256(evidence_path),
            "gate": None,
        }
        write_json(proposal_dir / "manifest.json", manifest)
        return proposal_dir

    def proposal_prompt(self, proposal_dir: Path) -> str:
        manifest = read_json(proposal_dir / "manifest.json")
        allowed = "\n".join(f"- {item['path']}" for item in manifest["files"])
        return f"""You are the controlled system-improvement agent for CAD evaluation proposal {manifest['proposal_id']}.

Read ../evidence.json. Aggregate patterns across samples and distinguish drawing failures from prompt, skill, MCP, verifier, and task failures. You may edit only these candidate files in the current proposal workspace:
{allowed}

Do not access or modify production source, samples, rubrics, records, batch outputs, or the holdout split. Do not weaken checks to make scores rise. Prefer the smallest general change supported by multiple evidence samples. MCP changes must preserve unrestricted CAD geometry operations and add tests or diagnostics only when justified. Keep SKILL.md basic and concise; put workflow policy in prompt templates.

Write change-proposal.json in the current directory with keys evidence_summary, failure_owners, changed_files, expected_impact, risks, and validation_plan. A proposal may recommend no source change when evidence is insufficient."""

    def codex_command(self, proposal_dir: Path, model: str, effort: str, executable: str = "codex") -> list[str]:
        workspace = proposal_dir / "workspace"
        return [
            executable, "exec", "--ephemeral", "--skip-git-repo-check",
            "--ignore-user-config", "--ignore-rules", "--approve-for-me",
            "--model", model, "--cd", str(workspace),
            "-c", f'model_reasoning_effort="{effort}"',
            "--json", "--output-last-message", str(proposal_dir / "agent-final.txt"),
            self.proposal_prompt(proposal_dir),
        ]

    def finalize_agent_changes(self, proposal_dir: Path) -> dict[str, Any]:
        manifest_path = proposal_dir / "manifest.json"
        manifest = read_json(manifest_path)
        if sha256(proposal_dir / "evidence.json") != manifest["evidence_sha256"]:
            manifest["status"] = "invalid"
            manifest["invalid_reason"] = "evidence bundle was modified"
            write_json(manifest_path, manifest)
            return manifest
        events_path = proposal_dir / "agent-events.jsonl"
        protected = [
            EVAL_ROOT / "samples",
            EVAL_ROOT / "records",
            EVAL_ROOT / "batch",
            self.split_path,
            WORKSPACE / ".agents/skills/autocad-image-modeling",
            WORKSPACE / "mcp",
            EVAL_ROOT / "prompts",
            EVAL_ROOT / "verifier",
        ]
        violations = []
        if events_path.is_file():
            for line_number, line in enumerate(events_path.read_text(encoding="utf-8").splitlines(), start=1):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                item = event.get("item", {})
                command = str(item.get("command", "")).casefold()
                for path in protected:
                    token = str(path.resolve()).casefold()
                    if token in command:
                        violations.append({"line": line_number, "path": str(path)})
        if violations:
            manifest["status"] = "invalid"
            manifest["invalid_reason"] = "agent accessed protected production or evaluation paths"
            manifest["access_violations"] = violations
            write_json(manifest_path, manifest)
            return manifest
        allowed = {item["path"] for item in manifest["files"]}
        workspace = proposal_dir / "workspace"
        unexpected = [
            path.relative_to(workspace).as_posix() for path in workspace.rglob("*")
            if path.is_file() and path.relative_to(workspace).as_posix() not in allowed | {"change-proposal.json"}
        ]
        if unexpected:
            manifest["status"] = "invalid"
            manifest["invalid_reason"] = f"unexpected candidate files: {unexpected}"
            write_json(manifest_path, manifest)
            return manifest
        changed = []
        for record in manifest["files"]:
            path = workspace / record["path"]
            record["after_sha256"] = sha256(path)
            if record["after_sha256"] != record["before_sha256"]:
                changed.append(record["path"])
        manifest["changed_files"] = changed
        manifest["status"] = "proposed" if changed else "no-change"
        manifest["updated_at"] = utc_now()
        write_json(manifest_path, manifest)
        return manifest

    def run_agent(self, proposal_id: str, model: str, effort: str = "medium") -> dict[str, Any]:
        proposal_dir = self.proposals_root / validate_id(proposal_id)
        command = self.codex_command(proposal_dir, model, effort, shutil.which("codex") or "codex")
        with (proposal_dir / "agent-events.jsonl").open("w", encoding="utf-8") as stdout, (
            proposal_dir / "agent-stderr.log"
        ).open("w", encoding="utf-8") as stderr:
            completed = subprocess.run(
                command, cwd=proposal_dir / "workspace", stdin=subprocess.DEVNULL,
                stdout=stdout, stderr=stderr, text=True, encoding="utf-8",
                errors="replace", timeout=1800, check=False,
            )
        manifest = self.finalize_agent_changes(proposal_dir)
        manifest["agent"] = {"model": model, "effort": effort, "return_code": completed.returncode}
        write_json(proposal_dir / "manifest.json", manifest)
        return manifest

    def validate_static(self, proposal_id: str) -> dict[str, Any]:
        proposal_dir = self.proposals_root / validate_id(proposal_id)
        manifest = read_json(proposal_dir / "manifest.json")
        workspace = proposal_dir / "workspace"
        checks: list[dict[str, Any]] = []
        required_placeholders = {
            "evals/cad-1000-hours/prompts/modeling.md": {
                "sample_id", "run_id", "attempt_id", "skill_path",
                "geometry_checkpoint", "annotation_checkpoint", "candidate",
            },
            "evals/cad-1000-hours/prompts/repair.md": {
                "sample_id", "run_id", "attempt_id", "previous_candidate",
                "previous_verdict", "previous_diagnostic", "candidate", "reflection",
            },
        }
        for record in manifest["files"]:
            relative = record["path"]
            candidate = workspace / relative
            production = WORKSPACE / relative
            checks.append({
                "id": f"production-unchanged:{relative}",
                "passed": production.is_file() and sha256(production) == record["before_sha256"],
            })
            if candidate.suffix == ".py":
                try:
                    compile(candidate.read_text(encoding="utf-8"), str(candidate), "exec")
                    compiled = True
                except SyntaxError:
                    compiled = False
                checks.append({"id": f"python-syntax:{relative}", "passed": compiled})
            if relative in required_placeholders:
                template = Template(candidate.read_text(encoding="utf-8"))
                identifiers = set(template.get_identifiers())
                checks.append({
                    "id": f"prompt-placeholders:{relative}",
                    "passed": template.is_valid() and identifiers == required_placeholders[relative],
                    "actual": sorted(identifiers),
                })
        proposal_path = workspace / "change-proposal.json"
        try:
            proposal = read_json(proposal_path)
            required_keys = {
                "evidence_summary", "failure_owners", "changed_files",
                "expected_impact", "risks", "validation_plan",
            }
            proposal_valid = required_keys <= set(proposal)
        except (FileNotFoundError, json.JSONDecodeError):
            proposal_valid = False
        checks.append({"id": "change-proposal-schema", "passed": proposal_valid})
        result = {"passed": all(item["passed"] for item in checks), "checks": checks, "validated_at": utc_now()}
        write_json(proposal_dir / "static-validation.json", result)
        return result

    def build_report(
        self,
        results_path: Path,
        output_path: Path,
        *,
        model: str,
        tests_passed: bool,
    ) -> dict[str, Any]:
        results = json.loads(Path(results_path).read_text(encoding="utf-8"))
        rows = [item for item in results if item.get("model") == model]
        sample_ids = [item.get("sample_id") for item in rows]
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError("Evaluation report contains duplicate sample/model results")
        report = {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "model": model,
            "tests": {"passed": tests_passed},
            "results_sha256": sha256(Path(results_path)),
            "samples": [
                {
                    "sample_id": item.get("sample_id"),
                    "status": item.get("status"),
                    "score": item.get("score"),
                    "coverage": item.get("coverage"),
                    "integrity": item.get("integrity"),
                }
                for item in rows
            ],
        }
        write_json(Path(output_path), report)
        return report

    @staticmethod
    def _subset_metrics(report: dict[str, Any], sample_ids: set[str]) -> dict[str, Any]:
        rows = [item for item in report.get("samples", []) if item.get("sample_id") in sample_ids]
        found = {item.get("sample_id") for item in rows}
        if found != sample_ids:
            missing = sorted(sample_ids - found)
            extra = sorted(found - sample_ids)
            raise ValueError(f"Report sample mismatch; missing={missing}, extra={extra}")
        if not all(item.get("integrity", {}).get("ok") is True for item in rows):
            raise ValueError("Report contains a run with failed integrity")
        return {
            "count": len(rows),
            "average_score": sum(float(item.get("score", 0.0)) for item in rows) / len(rows),
            "average_coverage": sum(float(item.get("coverage", 0.0)) for item in rows) / len(rows),
            "pass_rate": sum(item.get("status") == "passed" for item in rows) / len(rows),
            "scores": {item["sample_id"]: float(item.get("score", 0.0)) for item in rows},
        }

    def gate(
        self,
        proposal_id: str,
        baseline_report: Path,
        candidate_report: Path,
        *,
        independent_verifier_approval: bool = False,
        max_sample_regression: float = 2.0,
    ) -> dict[str, Any]:
        proposal_dir = self.proposals_root / validate_id(proposal_id)
        manifest = read_json(proposal_dir / "manifest.json")
        baseline = read_json(Path(baseline_report))
        candidate = read_json(Path(candidate_report))
        split = self.split()
        if not candidate.get("tests", {}).get("passed"):
            raise ValueError("Candidate report must record passing tests")
        development = set(split["development"])
        holdout = set(split["holdout"])
        metrics = {}
        checks = []
        for name, ids in (("development", development), ("holdout", holdout)):
            before = self._subset_metrics(baseline, ids)
            after = self._subset_metrics(candidate, ids)
            metrics[name] = {"baseline": before, "candidate": after}
            checks.extend([
                {"id": f"{name}_average_score", "passed": after["average_score"] >= before["average_score"]},
                {"id": f"{name}_average_coverage", "passed": after["average_coverage"] >= before["average_coverage"]},
                {"id": f"{name}_pass_rate", "passed": after["pass_rate"] >= before["pass_rate"]},
                {
                    "id": f"{name}_sample_regression",
                    "passed": all(
                        after["scores"][sample] >= before["scores"][sample] - max_sample_regression
                        for sample in ids
                    ),
                },
            ])
        verifier_changed = any(
            item.get("component") == "verifier"
            and item.get("after_sha256") != item.get("before_sha256")
            for item in manifest.get("files", [])
        )
        checks.append({
            "id": "verifier_independent_approval",
            "passed": not verifier_changed or independent_verifier_approval,
        })
        result = {
            "passed": all(item["passed"] for item in checks),
            "evaluated_at": utc_now(),
            "checks": checks,
            "metrics": metrics,
            "baseline_report_sha256": sha256(Path(baseline_report)),
            "candidate_report_sha256": sha256(Path(candidate_report)),
        }
        manifest["gate"] = result
        manifest["status"] = "gate-passed" if result["passed"] else "gate-rejected"
        write_json(proposal_dir / "manifest.json", manifest)
        return result

    def promote(self, proposal_id: str) -> dict[str, Any]:
        proposal_dir = self.proposals_root / validate_id(proposal_id)
        manifest = read_json(proposal_dir / "manifest.json")
        if manifest.get("status") != "gate-passed":
            raise ValueError("Only a gate-passed proposal can be promoted")
        release_dir = self.releases_root / proposal_id
        release_dir.mkdir(parents=True, exist_ok=False)
        for record in manifest["files"]:
            relative = Path(record["path"])
            production = WORKSPACE / relative
            candidate = proposal_dir / "workspace" / relative
            if sha256(candidate) != record["after_sha256"]:
                raise ValueError(f"Candidate changed after gating: {record['path']}")
            before = release_dir / "before" / relative
            after = release_dir / "source" / relative
            before.parent.mkdir(parents=True, exist_ok=True)
            after.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(production, before)
            shutil.copy2(candidate, after)
            shutil.copy2(candidate, production)
        release = {
            "schema_version": "1.0",
            "release_id": proposal_id,
            "promoted_at": utc_now(),
            "proposal_manifest_sha256": sha256(proposal_dir / "manifest.json"),
            "files": manifest["files"],
        }
        write_json(release_dir / "manifest.json", release)
        write_json(self.current_path, release)
        manifest["status"] = "promoted"
        manifest["promoted_at"] = release["promoted_at"]
        write_json(proposal_dir / "manifest.json", manifest)
        return release

    def rollback(self, release_id: str) -> dict[str, Any]:
        release_dir = self.releases_root / validate_id(release_id)
        release = read_json(release_dir / "manifest.json")
        for record in release["files"]:
            relative = Path(record["path"])
            shutil.copy2(release_dir / "before" / relative, WORKSPACE / relative)
        result = {"release_id": release_id, "rolled_back_at": utc_now()}
        write_json(self.current_path, result)
        return result
