"""Run project quality gates with the repository virtual environment."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

COMMANDS = {
    "ruff": ["-m", "ruff", "check", "."],
    "mypy": ["-m", "mypy", "src/bili_support"],
    "pytest": ["-m", "pytest", "-q"],
}


def project_python() -> Path:
    """Prefer the conventional repository venv on Windows or POSIX."""
    candidates = (
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",
        PROJECT_ROOT / ".venv" / "bin" / "python",
    )
    return next((candidate for candidate in candidates if candidate.exists()), Path(sys.executable))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("gate", choices=COMMANDS)
    args = parser.parse_args()
    command = [str(project_python()), *COMMANDS[args.gate]]
    return subprocess.run(command, cwd=PROJECT_ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
