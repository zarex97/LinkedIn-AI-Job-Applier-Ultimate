"""
File-based handshake that lets the headless apply agent pause for the user.

The agent runs `python verification_gate.py wait <gate_dir>` when a site asks
for email verification. That writes a `request` file and blocks. The bot process
sees the request, asks the user in its own console, and writes `done`.

Standard library only, so the script runs from any working directory.
"""

import argparse
import sys
import time
from pathlib import Path


class VerificationGate:
    def __init__(self, gate_dir: Path):
        self.gate_dir = Path(gate_dir)
        self._request_file = self.gate_dir / "request"
        self._done_file = self.gate_dir / "done"

    def request(self) -> None:
        """Ask the user to verify; clears any earlier confirmation"""
        self.gate_dir.mkdir(parents=True, exist_ok=True)
        self._done_file.unlink(missing_ok=True)
        self._request_file.write_text("pending", encoding="utf-8")

    def pending(self) -> bool:
        return self._request_file.exists()

    def confirm(self) -> None:
        """Mark the request as handled by the user"""
        self.gate_dir.mkdir(parents=True, exist_ok=True)
        self._done_file.write_text("done", encoding="utf-8")
        self._request_file.unlink(missing_ok=True)

    def wait_for_confirmation(self, poll_seconds: float = 1.0, timeout: float = 1800) -> bool:
        """Block until the user confirms; False on timeout"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._done_file.exists():
                return True
            time.sleep(poll_seconds)
        return self._done_file.exists()

    def reset(self) -> None:
        self._request_file.unlink(missing_ok=True)
        self._done_file.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pause the apply agent until the user confirms")
    subparsers = parser.add_subparsers(dest="command", required=True)
    wait_parser = subparsers.add_parser("wait", help="request verification and wait for the user")
    wait_parser.add_argument("gate_dir")
    wait_parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args(argv)

    gate = VerificationGate(Path(args.gate_dir))
    gate.request()
    if gate.wait_for_confirmation(timeout=args.timeout):
        print("User confirmed email verification.")
        return 0
    gate.reset()
    print("Timed out waiting for the user.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
