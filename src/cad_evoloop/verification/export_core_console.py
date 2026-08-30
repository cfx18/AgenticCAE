"""Export model-space solids from DWG to STL through isolated Core Console."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

from cad_evoloop.paths import project_root

from .extract_core_console import core_console_command, decode_console_output, lisp_path


def export_lisp(output: Path, status: Path, facet_resolution: float = 10.0) -> str:
    if not 0.01 <= facet_resolution <= 10.0:
        raise ValueError("facet_resolution must be between 0.01 and 10")
    return f'''(setvar "FILEDIA" 0)
(setvar "CMDECHO" 0)
(setvar "TILEMODE" 1)
(setvar "CTAB" "Model")
(setvar "FACETRES" {facet_resolution:g})
(defun mcp-export-status (value / f)
  (setq f (open "{lisp_path(status)}" "w"))
  (write-line value f)
  (close f))
(setq mcp-export-ss (ssget "_X" '((0 . "3DSOLID,MESH") (410 . "Model"))))
(if mcp-export-ss
  (progn
    (command "_.STLOUT" mcp-export-ss "" "_Yes" "{lisp_path(output)}")
    (if (findfile "{lisp_path(output)}")
      (mcp-export-status "DONE")
      (mcp-export-status "EXPORT_FAILED")))
  (mcp-export-status "NO_SOLIDS"))
(princ)
'''


def export_dwg_core(
    path: str | Path,
    output: str | Path,
    timeout: int = 120,
    *,
    facet_resolution: float = 10.0,
) -> Path:
    candidate = Path(path).resolve()
    output = Path(output).resolve()
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    if output.suffix.casefold() != ".stl":
        raise ValueError("Core Console geometry output must use the .stl extension")
    try:
        output.relative_to(project_root())
    except ValueError as exc:
        raise ValueError(f"output must be inside workspace: {project_root()}") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="cad-core-export-", dir=output.parent, ignore_cleanup_errors=True,
    ) as temp:
        job_dir = Path(temp)
        user_data_dir = job_dir / "autocad-user-data"
        status_path = job_dir / "export.status"
        payload = job_dir / "export.lsp"
        script = job_dir / "export.scr"
        working_candidate = job_dir / "input.dwg"
        shutil.copy2(candidate, working_candidate)
        payload.write_text(
            export_lisp(output, status_path, facet_resolution),
            encoding="utf-8",
            newline="\n",
        )
        script.write_text(
            f'(setvar "SECURELOAD" 0)\n(load "{lisp_path(payload)}")\n_.QUIT\n_N\n',
            encoding="utf-8",
            newline="\n",
        )
        completed = subprocess.run(
            core_console_command(working_candidate, script, user_data_dir),
            cwd=candidate.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        status = status_path.read_text(encoding="utf-8").strip() if status_path.is_file() else None
        if completed.returncode != 0 or status != "DONE" or not output.is_file():
            diagnostic = "\n".join(filter(None, (
                decode_console_output(completed.stdout),
                decode_console_output(completed.stderr),
            )))[-4000:]
            reason = status or f"CORE_CONSOLE_EXIT_{completed.returncode}"
            raise RuntimeError(f"Core Console STL export failed ({reason}): {diagnostic}")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--facet-resolution", type=float, default=10.0)
    args = parser.parse_args()
    print(export_dwg_core(
        args.candidate,
        args.output,
        args.timeout,
        facet_resolution=args.facet_resolution,
    ))


if __name__ == "__main__":
    main()
