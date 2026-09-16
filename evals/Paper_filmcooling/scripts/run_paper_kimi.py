"""Run one autonomous paper-to-AutoCAD trajectory with Kimi Code and K3."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit


ENV_KEYS = {
    "KIMI_MODEL_BASE_URL",
    "KIMI_MODEL_API_KEY",
    "KIMI_MODEL_NAME",
    "KIMI_MODEL_PROVIDER_TYPE",
    "KIMI_MODEL_MAX_CONTEXT_SIZE",
    "KIMI_MODEL_CAPABILITIES",
    "KIMI_MODEL_THINKING_EFFORT",
}
PLACEHOLDER_MARKERS = ("your-", "replace", "changeme", "<", ">")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    temporary.replace(path)


def parse_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(f"Kimi environment file not found: {path}")
    values: dict[str, str] = {}
    assignment = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = assignment.match(line)
        if not match:
            raise ValueError(f"Invalid .env assignment at {path}:{line_number}")
        key, raw_value = match.groups()
        if key not in ENV_KEYS:
            raise ValueError(f"Unsupported key in Kimi .env: {key}")
        value = raw_value.strip()
        if value[:1] in {'\"', "'"}:
            quote = value[0]
            if len(value) < 2 or value[-1] != quote:
                raise ValueError(f"Unclosed quote at {path}:{line_number}")
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def validate_kimi_env(values: dict[str, str]) -> None:
    required = ("KIMI_MODEL_BASE_URL", "KIMI_MODEL_API_KEY", "KIMI_MODEL_NAME")
    missing = [key for key in required if not values.get(key, "").strip()]
    if missing:
        raise ValueError(f"Fill these values in .env before running: {', '.join(missing)}")
    for key in required:
        folded = values[key].strip().casefold()
        if any(marker in folded for marker in PLACEHOLDER_MARKERS):
            raise ValueError(f"Replace the placeholder value for {key} in .env")
    endpoint = urlsplit(values["KIMI_MODEL_BASE_URL"])
    if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
        raise ValueError("KIMI_MODEL_BASE_URL must be an absolute http(s) URL")
    if endpoint.username or endpoint.password:
        raise ValueError("Do not embed credentials in KIMI_MODEL_BASE_URL")
    if endpoint.query or endpoint.fragment:
        raise ValueError("KIMI_MODEL_BASE_URL must not contain a query string or fragment")
    if values.get("KIMI_MODEL_PROVIDER_TYPE", "kimi") != "kimi":
        raise ValueError("This experiment requires KIMI_MODEL_PROVIDER_TYPE=kimi")


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def find_kimi_invocation(root: Path, override: Path | None) -> list[str]:
    if override is not None:
        executable = override.resolve()
        if not executable.is_file():
            raise FileNotFoundError(f"Kimi executable not found: {executable}")
        if executable.suffix.casefold() in {".js", ".mjs", ".cjs"}:
            node = shutil.which("node")
            if not node:
                raise FileNotFoundError("Node.js is required to launch the Kimi CLI script")
            return [node, str(executable)]
        return [str(executable)]

    package_json = root / ".local/kimi-code/node_modules/@moonshot-ai/kimi-code/package.json"
    if package_json.is_file():
        package = json.loads(package_json.read_text(encoding="utf-8"))
        bin_value = package.get("bin")
        if isinstance(bin_value, dict):
            relative = bin_value.get("kimi") or next(iter(bin_value.values()), None)
        else:
            relative = bin_value
        if isinstance(relative, str):
            entry = (package_json.parent / relative).resolve()
            node = shutil.which("node")
            if entry.is_file() and node:
                return [node, str(entry)]

    discovered = shutil.which("kimi")
    if discovered:
        return [discovered]
    raise FileNotFoundError(
        "Kimi Code CLI is not installed. Run npm install --prefix .local/kimi-code "
        "@moonshot-ai/kimi-code@latest from the repository root."
    )


def find_autocad_python(override: Path | None) -> Path:
    candidates: list[Path] = []
    if override is not None:
        candidates.append(override.resolve())
    candidates.append(Path(sys.executable).resolve())
    discovered = shutil.which("python")
    if discovered:
        candidates.append(Path(discovered).resolve())
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen or not candidate.is_file():
            continue
        seen.add(candidate)
        probe = subprocess.run(
            [str(candidate), "-c", "import pythoncom, win32com.client"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if probe.returncode == 0:
            return candidate
    suffix = f" at {override.resolve()}" if override is not None else ""
    raise RuntimeError(f"No Python interpreter with pywin32 was found{suffix}")


def minimal_prompt(root: Path, task_dir: Path, source_pdf: Path) -> str:
    return f"""Read {source_pdf.as_posix()} and reproduce in AutoCAD the baseline shaped
film-cooling hole described in the paper.

Use the configured AutoCAD MCP. Independently decide how to interpret, construct, verify,
and represent the geometry. Clearly record any assumptions caused by missing information.

Keep all generated files and execution records inside {task_dir.as_posix()}. Save the final
editable AutoCAD model somewhere in this task directory and clearly identify its path in your
final response. You may read the AutoCAD skill at
{root.as_posix()}/.agents/skills/autocad-image-modeling/SKILL.md. Do not inspect previous
experiments or external solutions.
"""


def safe_endpoint_label(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return f"{parsed.scheme}://{host}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_inventory(task_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(task_dir.rglob("*")):
        if not path.is_file() or path.name in {"run.json", "result.json"}:
            continue
        rows.append({
            "path": path.relative_to(task_dir).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return rows


def discover_deliverable_dwgs(task_dir: Path) -> list[Path]:
    deliverables: list[Path] = []
    for path in sorted(task_dir.rglob("*.dwg")):
        relative_parts = path.relative_to(task_dir).parts
        if len(relative_parts) >= 2 and relative_parts[:2] == ("mcp", "jobs"):
            continue
        deliverables.append(path)
    return deliverables


def write_mcp_config(root: Path, task_dir: Path, attempt_dir: Path, python: Path) -> Path:
    kimi_home = attempt_dir / "kimi-home"
    config_path = kimi_home / "mcp.json"
    audited_server = root / "src/cad_evoloop/backends/autocad/audited.py"
    base_server = root / ".agents/skills/autocad-image-modeling/scripts/autocad_mcp_server.py"
    topology_source = root / "mcp/autocad-topology/EvoCadTopology.cs"
    isolated_topology_source = task_dir / "mcp/autocad-topology/EvoCadTopology.cs"
    isolated_topology_source.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(topology_source, isolated_topology_source)
    config = {
        "mcpServers": {
            "autocad": {
                "command": str(python),
                "args": [str(audited_server)],
                "cwd": str(root),
                "env": {
                    "AUTOCAD_MCP_WORKSPACE": str(task_dir),
                    "AUTOCAD_MCP_AUDIT_PATH": str(attempt_dir / "mcp-audit.jsonl"),
                    "AUTOCAD_MCP_BASE_SERVER": str(base_server),
                    "AUTOCAD_TOPOLOGY_PLUGIN": str(
                        task_dir / ".local/autocad-topology/EvoCadTopology.dll"
                    ),
                    "KIMI_MODEL_API_KEY": "",
                    "KIMI_MODEL_BASE_URL": "",
                    "PYTHONPATH": str(root / "src"),
                },
                "startupTimeoutMs": 30000,
                "toolTimeoutMs": 180000,
            }
        }
    }
    write_json(config_path, config)
    (kimi_home / "config.toml").write_text(
        'telemetry = false\n\n[loop_control]\nmax_steps_per_turn = 0\n',
        encoding="utf-8",
        newline="\n",
    )
    return kimi_home


def run_process(
    command: list[str], cwd: Path, env: dict[str, str], stdout_path: Path,
    stderr_path: Path, timeout: int,
) -> tuple[int, bool]:
    with stdout_path.open("wb") as stdout_stream, stderr_path.open("wb") as stderr_stream:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout_stream,
            stderr=stderr_stream,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            return process.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)
            return process.returncode if process.returncode is not None else -9, True


def extract_final_text(events_path: Path) -> str:
    candidates: list[str] = []
    for raw_line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        message = event.get("message", event)
        if not isinstance(message, dict) or str(message.get("role", "")).casefold() != "assistant":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            candidates.append(content.strip())
        elif isinstance(content, list):
            text_parts = [
                item.get("text", "") for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            joined = "\n".join(part for part in text_parts if part.strip()).strip()
            if joined:
                candidates.append(joined)
    return candidates[-1] if candidates else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=5400)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--autocad-python", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()

    root = project_root().resolve()
    source = args.source.resolve()
    env_file = args.env_file.resolve()
    if not source.is_file() or source.suffix.casefold() != ".pdf":
        raise FileNotFoundError(f"Source PDF not found: {source}")
    if not args.campaign.replace("-", "").isalnum() or args.timeout < 1:
        parser.error("Use a safe campaign identifier and a positive timeout")

    kimi_values = parse_dotenv(env_file)
    validate_kimi_env(kimi_values)
    invocation = find_kimi_invocation(root, args.executable)
    autocad_python = find_autocad_python(args.autocad_python)
    version = subprocess.check_output(
        [*invocation, "--version"], text=True, encoding="utf-8", errors="replace"
    ).strip()
    if args.validate_only:
        print(json.dumps({
            "status": "ready",
            "kimi_version": version,
            "model": kimi_values["KIMI_MODEL_NAME"],
            "endpoint": safe_endpoint_label(kimi_values["KIMI_MODEL_BASE_URL"]),
            "autocad_python": str(autocad_python),
        }, indent=2))
        return 0

    task_dir = root / "evals/Paper_filmcooling/runs" / args.campaign
    attempt_dir = task_dir / "attempts/a001"
    input_dir = task_dir / "input"
    output_dir = task_dir / "outputs"
    task_dir.mkdir(parents=True, exist_ok=False)
    attempt_dir.mkdir(parents=True)
    input_dir.mkdir()
    output_dir.mkdir()
    staged_pdf = input_dir / "source-paper.pdf"
    shutil.copy2(source, staged_pdf)

    prompt = minimal_prompt(root, task_dir, staged_pdf)
    (attempt_dir / "action-prompt.md").write_text(prompt, encoding="utf-8", newline="\n")
    kimi_home = write_mcp_config(root, task_dir, attempt_dir, autocad_python)
    events_path = attempt_dir / "kimi-events.jsonl"
    stderr_path = attempt_dir / "kimi-stderr.log"
    final_path = attempt_dir / "kimi-final.md"
    command = [*invocation, "--prompt", prompt, "--output-format", "stream-json"]
    write_json(attempt_dir / "command.json", {
        "argv": command,
        "environment": {
            "KIMI_CODE_HOME": kimi_home.relative_to(task_dir).as_posix(),
            "KIMI_MODEL_API_KEY": "[REDACTED]",
            "KIMI_MODEL_BASE_URL": safe_endpoint_label(kimi_values["KIMI_MODEL_BASE_URL"]),
            "KIMI_MODEL_NAME": kimi_values["KIMI_MODEL_NAME"],
            "KIMI_MODEL_THINKING_EFFORT": kimi_values.get("KIMI_MODEL_THINKING_EFFORT", ""),
        },
    })
    run_record = {
        "schema_version": "1.0",
        "state": "running",
        "created_at": utc_now(),
        "started_at": utc_now(),
        "campaign": args.campaign,
        "source_original": source.as_posix(),
        "source_staged": staged_pdf.relative_to(task_dir).as_posix(),
        "source_sha256": sha256_file(staged_pdf),
        "model": kimi_values["KIMI_MODEL_NAME"],
        "reasoning_effort": kimi_values.get("KIMI_MODEL_THINKING_EFFORT", ""),
        "api_endpoint": safe_endpoint_label(kimi_values["KIMI_MODEL_BASE_URL"]),
        "harness": "native-kimi-code-autonomous-paper-to-cad-v1",
        "prompt_mode": "minimal-autonomous",
        "kimi_version": version,
        "autocad_mcp_python": autocad_python.as_posix(),
        "timeout_seconds": args.timeout,
        "human_geometry_preprocessing": False,
        "human_geometry_specification": False,
        "autocad_mcp_audited": True,
    }
    write_json(task_dir / "run.json", run_record)

    child_env = os.environ.copy()
    child_env.update(kimi_values)
    child_env.update({
        "KIMI_CODE_HOME": str(kimi_home),
        "KIMI_DISABLE_TELEMETRY": "1",
        "KIMI_SHELL_PATH": str(Path(r"C:\Program Files\Git\bin\bash.exe")),
        "KIMI_MCP_STARTUP_TIMEOUT_MS": "30000",
        "KIMI_MCP_TOOL_TIMEOUT_MS": "180000",
        "KIMI_CODE_BACKGROUND_PRINT_BACKGROUND_MODE": "drain",
        "KIMI_CODE_BACKGROUND_PRINT_WAIT_CEILING_S": str(args.timeout),
    })

    started = time.perf_counter()
    print(f"START {args.campaign}", flush=True)
    try:
        return_code, timed_out = run_process(
            command, task_dir, child_env, events_path, stderr_path, args.timeout
        )
        elapsed = round(time.perf_counter() - started, 3)
        final_text = extract_final_text(events_path)
        if final_text:
            final_path.write_text(final_text + "\n", encoding="utf-8", newline="\n")
        discovered_dwgs = discover_deliverable_dwgs(task_dir)
        complete = return_code == 0 and not timed_out and bool(final_text) and bool(discovered_dwgs)
        result: dict[str, object] = {
            "schema_version": "1.0",
            "status": "artifacts_ready_for_human_review" if complete else "incomplete",
            "return_code": return_code,
            "timed_out": timed_out,
            "elapsed_seconds": elapsed,
            "final_message_captured": bool(final_text),
            "discovered_dwgs": [path.relative_to(task_dir).as_posix() for path in discovered_dwgs],
            "missing_outputs": [] if discovered_dwgs else ["agent-selected final editable DWG"],
        }
        run_record.update(
            state="completed" if complete else "incomplete",
            completed_at=utc_now(),
            elapsed_seconds=elapsed,
        )
    except Exception as exc:
        result = {
            "schema_version": "1.0",
            "status": "execution_error",
            "error": repr(exc),
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
        run_record.update(state="execution_error", completed_at=utc_now(), error=repr(exc))
    write_json(task_dir / "run.json", run_record)
    result["artifacts"] = file_inventory(task_dir)
    write_json(task_dir / "result.json", result)
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "artifacts_ready_for_human_review" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
