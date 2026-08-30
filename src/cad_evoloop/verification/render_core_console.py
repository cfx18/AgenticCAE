"""Render native DWG model-space geometry through isolated AutoCAD Core Console."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import tempfile

from .extract_core_console import CORE_CONSOLE, decode_console_output, lisp_path


def render_lisp(output: Path, sentinel: Path) -> str:
    return f'''(setvar "FILEDIA" 0)
(setvar "CMDECHO" 0)
(setvar "TILEMODE" 1)
(setvar "CTAB" "Model")
(command "_.UCS" "_World")
(command "_.VPOINT" "1,-1,1")
(command "_.ZOOM" "_Extents")
(setq mcp-render-ss (ssget "_X" '((410 . "Model"))))
(if mcp-render-ss
  (command "_.PNGOUT" "{lisp_path(output)}" mcp-render-ss ""))
(if (findfile "{lisp_path(output)}")
  (progn
    (setq mcp-render-f (open "{lisp_path(sentinel)}" "w"))
    (write-line "DONE" mcp-render-f)
    (close mcp-render-f)))
(princ)
'''


def render_dwg_core(path: str | Path, output: str | Path, timeout: int = 120) -> Path:
    candidate = Path(path).resolve()
    output = Path(output).resolve()
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cad-core-render-", dir=output.parent) as temp:
        job_dir = Path(temp)
        sentinel = job_dir / "render.done"
        payload = job_dir / "render.lsp"
        script = job_dir / "render.scr"
        payload.write_text(render_lisp(output, sentinel), encoding="utf-8", newline="\n")
        script.write_text(
            f'(setvar "SECURELOAD" 0)\n(load "{lisp_path(payload)}")\n_.QUIT\n_N\n',
            encoding="utf-8",
            newline="\n",
        )
        completed = subprocess.run(
            [str(CORE_CONSOLE), "/i", str(candidate), "/s", str(script)],
            cwd=candidate.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0 or not sentinel.is_file() or not output.is_file():
            diagnostic = "\n".join(filter(None, (
                decode_console_output(completed.stdout),
                decode_console_output(completed.stderr),
            )))[-4000:]
            raise RuntimeError(
                f"Core Console render failed with code {completed.returncode}: {diagnostic}"
            )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    print(render_dwg_core(args.candidate, args.output, args.timeout))


if __name__ == "__main__":
    main()
