"""Small subprocess wrapper used by service classes."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandResult:
    """Captured command result."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        """Return true when the process exited successfully."""
        return self.returncode == 0

    @property
    def combined_output(self) -> str:
        """Return stdout and stderr joined for display."""
        return "\n".join(part for part in (self.stdout.strip(), self.stderr.strip()) if part)


def command_exists(command: str) -> bool:
    """Return true when a command is available on PATH or as an executable path."""
    if "/" in command:
        return Path(command).exists()
    return shutil.which(command) is not None


def run_command(
    args: Sequence[str | Path],
    *,
    timeout: int = 30,
    env: Mapping[str, str] | None = None,
) -> CommandResult:
    """Run a command and capture text output."""
    str_args = tuple(str(arg) for arg in args)
    try:
        completed = subprocess.run(
            str_args,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return CommandResult(
            args=str_args,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except FileNotFoundError as exc:
        return CommandResult(args=str_args, returncode=127, stdout="", stderr=str(exc))
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return CommandResult(
            args=str_args,
            returncode=124,
            stdout=stdout,
            stderr=stderr or f"Command timed out after {timeout}s",
        )
