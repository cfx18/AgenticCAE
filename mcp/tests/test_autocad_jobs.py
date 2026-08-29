from __future__ import annotations

import threading
import time

import pytest

from mcp.autocad_jobs import CommandJobManager


def wait_for_terminal(manager: CommandJobManager, job_id: str) -> dict:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        job = manager.status(job_id)
        if job["status"] in {"succeeded", "failed", "cancelled", "timed_out"}:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_job_returns_immediately_and_records_success() -> None:
    release = threading.Event()

    def runner(command, timeout, cancel_event, progress):
        progress("LINE")
        assert release.wait(1)
        progress("")
        return {"command": command}

    manager = CommandJobManager(runner)
    job = manager.start("LINE", 10)
    assert job["status"] in {"queued", "running"}
    assert job["command_length"] == 4
    release.set()

    finished = wait_for_terminal(manager, job["job_id"])
    assert finished["status"] == "succeeded"
    assert finished["result"] == {"command": "LINE"}
    assert finished["finished_at"]


def test_only_one_job_can_run_at_a_time() -> None:
    release = threading.Event()

    def runner(command, timeout, cancel_event, progress):
        release.wait(1)
        return {}

    manager = CommandJobManager(runner)
    first = manager.start("first")
    with pytest.raises(RuntimeError, match="still active"):
        manager.start("second")
    release.set()
    wait_for_terminal(manager, first["job_id"])


def test_cancel_request_is_visible_to_worker() -> None:
    entered = threading.Event()

    def runner(command, timeout, cancel_event, progress):
        entered.set()
        assert cancel_event.wait(1)
        return {}

    manager = CommandJobManager(runner)
    job = manager.start("long command")
    assert entered.wait(1)
    requested = manager.cancel(job["job_id"])
    assert requested["status"] == "cancel_requested"

    finished = wait_for_terminal(manager, job["job_id"])
    assert finished["status"] == "cancelled"


def test_cancel_targets_only_the_recorded_window() -> None:
    entered = threading.Event()
    cancelled_windows = []

    def runner(command, timeout, cancel_event, progress):
        progress("LINE", 12345)
        entered.set()
        assert cancel_event.wait(1)
        return {}

    manager = CommandJobManager(runner, canceller=cancelled_windows.append)
    job = manager.start("_.LINE")
    assert entered.wait(1)
    manager.cancel(job["job_id"])

    assert cancelled_windows == [12345]
    assert wait_for_terminal(manager, job["job_id"])["status"] == "cancelled"


def test_command_error_after_delivered_cancel_is_cancelled() -> None:
    entered = threading.Event()

    def runner(command, timeout, cancel_event, progress):
        progress("LINE", 12345)
        entered.set()
        assert cancel_event.wait(1)
        raise RuntimeError("AutoCAD rejected interrupted input")

    manager = CommandJobManager(runner, canceller=lambda window: None)
    job = manager.start("_.LINE")
    assert entered.wait(1)
    manager.cancel(job["job_id"])

    finished = wait_for_terminal(manager, job["job_id"])
    assert finished["status"] == "cancelled"
    assert finished["error"] is None
    assert "interrupted input" in finished["cancel_detail"]


def test_unknown_job_and_invalid_arguments_are_rejected() -> None:
    manager = CommandJobManager(lambda *args: {})
    with pytest.raises(ValueError):
        manager.start("")
    with pytest.raises(ValueError):
        manager.start("LINE", 1801)
    with pytest.raises(KeyError):
        manager.status("missing")
