"""Test suite for src/llm/verification_gate.py"""

import subprocess
import sys
import threading
import time
from pathlib import Path

from src.llm.verification_gate import VerificationGate

GATE_SCRIPT = Path(__file__).resolve().parent.parent / "src" / "llm" / "verification_gate.py"


def _confirm_when_requested(gate: VerificationGate, delay: float = 0.2) -> threading.Thread:
    def worker():
        deadline = time.monotonic() + 10
        while not gate.pending() and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(delay)
        gate.confirm()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


def test_request_then_pending(tmp_path):
    gate = VerificationGate(tmp_path)
    assert gate.pending() is False
    gate.request()
    assert gate.pending() is True


def test_confirm_releases_waiter(tmp_path):
    gate = VerificationGate(tmp_path)
    gate.request()
    _confirm_when_requested(gate)
    assert gate.wait_for_confirmation(poll_seconds=0.05, timeout=10) is True
    assert gate.pending() is False


def test_wait_times_out(tmp_path):
    gate = VerificationGate(tmp_path)
    gate.request()
    assert gate.wait_for_confirmation(poll_seconds=0.05, timeout=0.2) is False


def test_reset_clears_files(tmp_path):
    gate = VerificationGate(tmp_path)
    gate.request()
    gate.confirm()
    gate.reset()
    assert list(tmp_path.iterdir()) == []


def test_creates_missing_gate_dir(tmp_path):
    gate = VerificationGate(tmp_path / "nested" / "gate")
    gate.request()
    assert gate.pending() is True


def test_script_wait_exit_codes(tmp_path):
    gate = VerificationGate(tmp_path)
    _confirm_when_requested(gate)
    completed = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "wait", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0
    assert "User confirmed email verification." in completed.stdout


def test_script_wait_times_out(tmp_path):
    completed = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "wait", str(tmp_path), "--timeout", "0.3"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 1
    assert "Timed out waiting for the user." in completed.stdout


def test_confirm_removes_request_before_marking_done(tmp_path, monkeypatch):
    """A waiter that sees `done` must never still see the request as pending"""
    gate = VerificationGate(tmp_path)
    gate.request()
    request_seen_when_done_written = []
    original_write_text = Path.write_text

    def recording_write_text(self, *args, **kwargs):
        if self.name == "done":
            request_seen_when_done_written.append((tmp_path / "request").exists())
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", recording_write_text)
    gate.confirm()
    assert request_seen_when_done_written == [False]
