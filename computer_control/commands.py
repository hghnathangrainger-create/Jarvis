"""
commands.py

Command execution for the Jarvis Computer Control module.

Responsibilities:
    - Run shell commands, PowerShell commands, and Python scripts.
    - Enforce timeouts and capture stdout/stderr.
    - Log every command to the audit log BEFORE execution.
    - Handle subprocess.TimeoutExpired gracefully.

Does NOT:
    - Control mouse/keyboard input (see input.py).
    - Manage windows (see window.py).

This is RED-tier functionality — every command requires explicit
user approval before execution.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from typing import Any

from computer_control.models import CommandResult, ComputerControlError

logger = logging.getLogger(__name__)


class CommandExecutor:
    """Executes shell commands, PowerShell commands, and Python scripts.

    Every command is logged to the audit log before execution.
    Timeouts are enforced to prevent hanging processes.

    Attributes:
        available: Whether subprocess is usable (always True in
            standard Python).
    """

    def __init__(self, audit_logger: Any = None) -> None:
        """Initialise the command executor.

        Args:
            audit_logger: Optional EventLogger for audit trail. When
                provided, every command is logged before execution.
        """
        self._audit_logger = audit_logger
        self.available = True

    def _log_command(self, command: str, shell_type: str) -> None:
        """Log a command to the audit log before execution.

        Args:
            command: The command string.
            shell_type: The type of shell ("shell", "powershell", "script").
        """
        logger.warning(
            "EXECUTING %s COMMAND: %s",
            shell_type.upper(),
            command[:200],
        )
        if self._audit_logger is not None:
            try:
                self._audit_logger.emit(
                    source="command_executor",
                    action_type="command_executing",
                    outcome=__import__("config.constants", fromlist=["EventOutcome"]).EventOutcome.SUCCESS,
                    detail=f"type={shell_type} command={command[:500]}",
                )
            except Exception:
                pass

    def run_shell(
        self, command: str, timeout: int = 30
    ) -> CommandResult:
        """Run a shell command.

        Args:
            command: The shell command to execute.
            timeout: Maximum seconds to wait (default 30).

        Returns:
            A CommandResult with stdout, stderr, exit_code, and timed_out.
        """
        self._log_command(command, "shell")
        return self._run(command, timeout=timeout, shell=True)

    def run_powershell(
        self, command: str, timeout: int = 30
    ) -> CommandResult:
        """Run a PowerShell command.

        Args:
            command: The PowerShell command to execute.
            timeout: Maximum seconds to wait (default 30).

        Returns:
            A CommandResult with stdout, stderr, exit_code, and timed_out.
        """
        self._log_command(command, "powershell")
        ps_command = f'powershell.exe -NoProfile -Command "{command}"'
        return self._run(ps_command, timeout=timeout, shell=True)

    def run_python_script(
        self,
        script_path: str,
        args: list[str] | None = None,
        timeout: int = 60,
    ) -> CommandResult:
        """Run a Python script.

        Args:
            script_path: Path to the Python script.
            args: Optional list of arguments to pass to the script.
            timeout: Maximum seconds to wait (default 60).

        Returns:
            A CommandResult with stdout, stderr, exit_code, and timed_out.
        """
        cmd_parts = [sys.executable, script_path]
        if args:
            cmd_parts.extend(args)

        cmd_str = " ".join(cmd_parts)
        self._log_command(cmd_str, "script")

        return self._run(cmd_parts, timeout=timeout, shell=False)

    def _run(
        self,
        command: str | list[str],
        timeout: int = 30,
        shell: bool = True,
    ) -> CommandResult:
        """Execute a subprocess with timeout.

        Args:
            command: Command string or list of arguments.
            timeout: Maximum seconds to wait.
            shell: Whether to run via shell.

        Returns:
            A CommandResult with the outcome.
        """
        cmd_display = command if isinstance(command, str) else " ".join(command)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=shell,
            )
            return CommandResult(
                stdout=result.stdout or "",
                stderr=result.stderr or "",
                exit_code=result.returncode,
                timed_out=False,
                command=cmd_display,
            )

        except subprocess.TimeoutExpired:
            logger.error("Command timed out after %ds: %s", timeout, cmd_display)
            return CommandResult(
                stdout="",
                stderr=f"Command timed out after {timeout} seconds.",
                exit_code=-1,
                timed_out=True,
                command=cmd_display,
            )

        except Exception as exc:
            logger.error("Command failed: %s", exc)
            return CommandResult(
                stdout="",
                stderr=f"Command failed: {exc}",
                exit_code=-1,
                timed_out=False,
                command=cmd_display,
            )
