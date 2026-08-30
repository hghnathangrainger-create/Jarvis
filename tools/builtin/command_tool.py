"""
command_tool.py

A RED tool for command execution in the Jarvis Computer Control system.

Actions: shell, powershell, script.
ALWAYS requires explicit user approval before execution.
Returns full stdout, stderr, exit code.
Enforces timeout (default 30s).

RED because command execution can modify the system, run arbitrary
code, and access sensitive data.
"""

from __future__ import annotations

from typing import Any

from tools.base_tool import BaseTool, ToolRequest, ToolResult


class CommandTool(BaseTool):
    """Executes shell commands, PowerShell, and Python scripts.

    RED-tier tool — always requires explicit user approval.

    Attributes:
        _manager: The ComputerControlManager providing command execution.
    """

    def __init__(self, manager: Any) -> None:
        """Initialise the tool.

        Args:
            manager: A ComputerControlManager instance.
        """
        self._manager = manager

    @property
    def name(self) -> str:
        return "command_exec"

    @property
    def description(self) -> str:
        return "Execute shell commands, PowerShell, and Python scripts. Always requires user approval."

    def action_for(self, request: ToolRequest) -> str:
        """Command execution always requires user approval."""
        return "execute command"

    def run(self, request: ToolRequest) -> ToolResult:
        """Handle a command execution request.

        Args:
            request: The request with input_data containing:
                - action (str): "shell", "powershell", or "script".
                - command (str): The command to execute (shell/powershell).
                - script_path (str): Path to script (for script action).
                - args (list): Script arguments (optional).
                - timeout (int): Timeout in seconds (default 30/60).

        Returns:
            A ToolResult with stdout, stderr, exit_code.
        """
        action = str(request.input_data.get("action", "shell")).strip().lower()

        if action == "shell":
            return self._run_shell(request)
        elif action == "powershell":
            return self._run_powershell(request)
        elif action == "script":
            return self._run_script(request)
        else:
            return self.fail(
                f"Unknown action '{action}'. Use 'shell', 'powershell', or 'script'."
            )

    def _run_shell(self, request: ToolRequest) -> ToolResult:
        """Execute a shell command."""
        command = str(request.input_data.get("command", "")).strip()
        if not command:
            return self.fail("No command provided. Usage: command='echo hello'")
        timeout = int(request.input_data.get("timeout", 30) or 30)
        result = self._manager.run_shell(command, timeout=timeout)
        return self._format_result(result)

    def _run_powershell(self, request: ToolRequest) -> ToolResult:
        """Execute a PowerShell command."""
        command = str(request.input_data.get("command", "")).strip()
        if not command:
            return self.fail("No command provided. Usage: command='Get-Process'")
        timeout = int(request.input_data.get("timeout", 30) or 30)
        result = self._manager.run_powershell(command, timeout=timeout)
        return self._format_result(result)

    def _run_script(self, request: ToolRequest) -> ToolResult:
        """Execute a Python script."""
        script_path = str(request.input_data.get("script_path", "")).strip()
        if not script_path:
            return self.fail("No script_path provided. Usage: script_path='script.py'")
        args = request.input_data.get("args")
        if args is not None and not isinstance(args, list):
            args = [str(args)]
        timeout = int(request.input_data.get("timeout", 60) or 60)
        result = self._manager.run_python_script(
            script_path, args=args, timeout=timeout
        )
        return self._format_result(result)

    @staticmethod
    def _format_result(result: Any) -> ToolResult:
        """Format a CommandResult as a ToolResult.

        Args:
            result: A CommandResult from the manager.

        Returns:
            A formatted ToolResult.
        """
        lines = []
        lines.append(f"Exit code: {result.exit_code}")
        if result.timed_out:
            lines.append("STATUS: TIMED OUT")
        elif result.success:
            lines.append("STATUS: SUCCESS")
        else:
            lines.append("STATUS: FAILED")

        if result.stdout:
            lines.append("")
            lines.append("STDOUT:")
            lines.append(result.stdout[:5000])
            if len(result.stdout) > 5000:
                lines.append(f"... ({len(result.stdout) - 5000} chars truncated)")

        if result.stderr:
            lines.append("")
            lines.append("STDERR:")
            lines.append(result.stderr[:5000])
            if len(result.stderr) > 5000:
                lines.append(f"... ({len(result.stderr) - 5000} chars truncated)")

        output = "\n".join(lines)

        return ToolResult(
            tool_name="command_exec",
            success=result.success,
            output=output if result.success else "",
            error=output if not result.success else None,
            metadata={
                "exit_code": str(result.exit_code),
                "timed_out": str(result.timed_out),
                "command": result.command[:500],
            },
        )
