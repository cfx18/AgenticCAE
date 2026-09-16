"""Export a copy of the frozen AutoCAD candidate; never alter the scored source."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from cad_evoloop.backends.autocad.core_console import CoreConsoleJobManager, TERMINAL_STATES


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    source, destination = args.source.resolve(), args.destination.resolve()
    if not source.is_relative_to(root) or not destination.is_relative_to(root):
        raise ValueError("All artifacts must stay in the workspace")
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    manager = CoreConsoleJobManager(root, Path("E:/AutoCAD/AutoCAD 2024/accoreconsole.exe"), source)
    path = (destination / "candidate.igs").as_posix()
    lisp = f'''(setvar "FILEDIA" 0)
(setvar "CMDECHO" 1)
(command "_.IGESEXPORT" "{path}" "_All" "")
(princ "\\nIGES_EXPORT_RETURNED")
'''
    job = manager.start(lisp, str(destination / "export-copy.dwg"), str(source), timeout=120,
                        capture_boolean_lineage=False)
    while job["status"] not in TERMINAL_STATES:
        time.sleep(1)
        job = manager.status(job["job_id"])
    job["source_sha256_before"] = before
    job["source_sha256_after"] = hashlib.sha256(source.read_bytes()).hexdigest()
    job["iges_exists"] = (destination / "candidate.igs").is_file()
    (destination / "export-job.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
    print(json.dumps(job, indent=2))
    assert job["source_sha256_after"] == before
    if job["status"] != "succeeded" or not job["iges_exists"]:
        raise RuntimeError("Native IGES export unavailable; inspect export-job.json and native log")


if __name__ == "__main__":
    main()
