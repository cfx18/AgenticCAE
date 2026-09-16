"""Episode receipts and a fail-closed container execution boundary."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

from PIL import Image

from cad_evoloop.agent.events import GENESIS_HASH, create_event, validate_event
from cad_evoloop.ledger.ledger import file_lock, sha256_file, write_json_atomic
from .bundle import contained_file, export_public, validate_bundle


class SandboxUnavailable(RuntimeError):
    pass


class DockerExecutor:
    """One fresh process container per action, persistent episode working files."""

    def __init__(self, image: str):
        if not re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", image):
            raise ValueError("A digest-pinned container image is required")
        self.image = image

    def execute(self, inputs: Path, work: Path, argv: list[str], timeout: float) -> dict:
        if not shutil.which("docker"):
            raise SandboxUnavailable("Docker is unavailable; local untrusted execution is disabled")
        if not argv or any(not isinstance(item, str) or "\x00" in item for item in argv):
            raise ValueError("Action must be an argument vector")
        if not 0 < timeout <= 900:
            raise ValueError("Action timeout must be between 0 and 900 seconds")
        name = "evocad-posttrain-" + uuid.uuid4().hex
        command = [
            "docker", "run", "--rm", "--pull=never", "--name", name,
            "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--user", "1000:1000",
            "--pids-limit", "128", "--memory", "4g", "--cpus", "2",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=512m", "--env", "HOME=/tmp",
            "--mount", f"type=bind,source={inputs.resolve()},target=/input,readonly",
            "--mount", f"type=bind,source={work.resolve()},target=/work",
            "--workdir", "/work", self.image, *argv,
        ]
        started = time.monotonic()
        try:
            result = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
            return {
                "status": "completed" if result.returncode == 0 else "execution_failed",
                "exit_code": result.returncode, "stdout": result.stdout.decode("utf-8", errors="replace"),
                "stderr": result.stderr.decode("utf-8", errors="replace"),
                "elapsed_seconds": time.monotonic() - started, "image": self.image,
            }
        except subprocess.TimeoutExpired as error:
            return {"status": "timeout", "exit_code": None,
                    "stdout": (error.stdout or b"").decode("utf-8", errors="replace"),
                    "stderr": (error.stderr or b"").decode("utf-8", errors="replace"),
                    "elapsed_seconds": time.monotonic() - started, "image": self.image}
        finally:
            # The generated name belongs exclusively to this action, never user CAD processes.
            subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=30, check=False)


class Episode:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.state = json.loads((self.root / "episode.json").read_text(encoding="utf-8"))

    @classmethod
    def reset(cls, task: Path, root: Path) -> "Episode":
        manifest = validate_bundle(task)
        if root.exists():
            raise FileExistsError("Episode IDs are immutable; reset creates a new directory")
        root.mkdir(parents=True)
        inventory = export_public(task, root / "input")
        (root / "work").mkdir()
        (root / "receipts").mkdir()
        write_json_atomic(root / "episode.json", {
            "episode_id": uuid.uuid4().hex, "task_id": manifest["task_id"],
            "task_manifest_sha256": sha256_file(task / "manifest.json"),
            "status": "active", "public_inventory": inventory,
        })
        episode = cls(root)
        episode.record("reset", {"public_inventory": inventory, "security": "file_export_only_until_sandbox_execute"})
        return episode

    def record(self, event_type: str, payload: dict, *, actor: str = "environment") -> dict:
        path = self.root / "events.jsonl"
        with file_lock(self.root / "events.lock"):
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
            previous = GENESIS_HASH
            for index, event in enumerate(events, 1):
                validate_event(event, project_id=self.state["episode_id"], expected_sequence=index, expected_previous_hash=previous)
                previous = event["event_hash"]
            event = create_event(project_id=self.state["episode_id"], sequence=len(events) + 1,
                                 previous_hash=previous, event_type=event_type, payload=payload, actor=actor)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        return event

    def _active(self) -> None:
        self.state = json.loads((self.root / "episode.json").read_text(encoding="utf-8"))
        if self.state["status"] != "active":
            raise ValueError("Episode already submitted")

    def observe(self, name: str, *, intent: str, crop: tuple[int, int, int, int] | None = None) -> dict:
        self._active()
        if not intent.strip():
            raise ValueError("Observation requires a public intent")
        path = contained_file(self.root / "input", name)
        with Image.open(path) as image:
            image.load()
            if crop and not (0 <= crop[0] < crop[2] <= image.width and 0 <= crop[1] < crop[3] <= image.height):
                raise ValueError("Crop lies outside image")
            observation_id = uuid.uuid4().hex
            target = self.root / "receipts" / f"{observation_id}.png"
            (image.crop(crop) if crop else image).save(target)
            dimensions = [crop[2]-crop[0], crop[3]-crop[1]] if crop else list(image.size)
            result = {"observation_id": observation_id, "intent": intent, "source": name,
                      "source_sha256": sha256_file(path), "crop": list(crop) if crop else None,
                      "image": target.relative_to(self.root).as_posix(), "sha256": sha256_file(target),
                      "dimensions": dimensions}
        self.record("observation_returned", result)
        return result

    def conclude_observation(self, observation_id: str, conclusion: str) -> None:
        self._active()
        events = [json.loads(line) for line in (self.root / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        known = {e["payload"].get("observation_id") for e in events if e["event_type"] == "observation_returned"}
        if observation_id not in known or not conclusion.strip():
            raise ValueError("Conclusion must refer to an actual observation")
        self.record("observation_conclusion", {"observation_id": observation_id, "public_conclusion": conclusion}, actor="agent")

    def execute(self, executor: DockerExecutor, argv: list[str], *, intent: str, timeout: float = 120) -> dict:
        self._active()
        self.record("action_started", {"argv": argv, "intent": intent, "timeout_seconds": timeout})
        try:
            receipt = executor.execute(self.root / "input", self.root / "work", argv, timeout)
        except SandboxUnavailable as error:
            self.record("infrastructure_unavailable", {"error": str(error), "model_penalty": False})
            raise
        self.record("action_returned", receipt)
        return receipt

    def checkpoint(self, names: list[str]) -> dict:
        self._active()
        checkpoint_id = uuid.uuid4().hex
        destination = self.root / "receipts" / checkpoint_id
        paths = [contained_file(self.root / "work", name) for name in names]
        destination.mkdir()
        files = []
        for index, path in enumerate(paths):
            target = destination / f"{index:03d}{path.suffix}"
            shutil.copyfile(path, target)
            files.append({"source": names[index], "snapshot": target.relative_to(self.root).as_posix(), "sha256": sha256_file(target)})
        result = {"checkpoint_id": checkpoint_id, "files": files}
        self.record("checkpoint", result)
        return result

    def submit(self, names: list[str]) -> dict:
        self._active()
        if not names or len(names) != len(set(names)):
            raise ValueError("Submission must contain unique artifact paths")
        snapshot = self.checkpoint(names)
        self.record("submitted", snapshot, actor="agent")
        self.state.update({"status": "submitted", "submission": snapshot})
        write_json_atomic(self.root / "episode.json", self.state)
        return snapshot
