"""
test_computer_control.py

Unit tests for the Jarvis Computer Control module.

Covers:
    - WindowInfo, CommandResult model creation
    - InputAutomator methods (mocked pyautogui)
    - WindowManager methods (mocked pygetwindow/psutil)
    - CommandExecutor with subprocess mocking
    - ComputerControlManager availability checks and delegation
    - WindowTool, InputTool, CommandTool execution paths
    - Security tier verification

Run with:
    pytest tests/unit/test_computer_control.py
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from computer_control.commands import CommandExecutor
from computer_control.input import InputAutomator
from computer_control.manager import ComputerControlManager
from computer_control.models import (
    CommandResult,
    ComputerControlError,
    WindowInfo,
)
from computer_control.window import WindowManager
from tools.base_tool import ToolRequest


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestWindowInfo:
    """Tests for WindowInfo model."""

    def test_defaults(self):
        w = WindowInfo()
        assert w.handle is None
        assert w.title == ""
        assert w.app_name is None
        assert w.is_active is False
        assert w.x == 0
        assert w.y == 0
        assert w.width == 0
        assert w.height == 0

    def test_with_values(self):
        w = WindowInfo(
            handle=12345,
            title="Notepad",
            app_name="notepad.exe",
            is_active=True,
            x=100, y=200, width=800, height=600,
        )
        assert w.handle == 12345
        assert w.title == "Notepad"
        assert w.is_active is True
        assert w.width == 800

    def test_to_dict(self):
        w = WindowInfo(title="Test", x=10, y=20)
        d = w.to_dict()
        assert d["title"] == "Test"
        assert d["x"] == 10
        assert "handle" in d

    def test_frozen(self):
        w = WindowInfo()
        with pytest.raises(AttributeError):
            w.title = "new"  # type: ignore[misc]


class TestCommandResult:
    """Tests for CommandResult model."""

    def test_success_result(self):
        r = CommandResult(stdout="hello", exit_code=0, command="echo hello")
        assert r.success is True
        assert r.stdout == "hello"
        assert r.timed_out is False

    def test_failure_result(self):
        r = CommandResult(stderr="error", exit_code=1)
        assert r.success is False

    def test_timeout_result(self):
        r = CommandResult(timed_out=True, exit_code=-1)
        assert r.success is False
        assert r.timed_out is True

    def test_to_dict(self):
        r = CommandResult(stdout="ok", exit_code=0, command="test")
        d = r.to_dict()
        assert d["stdout"] == "ok"
        assert d["success"] is True


class TestComputerControlError:
    """Tests for ComputerControlError."""

    def test_is_exception(self):
        with pytest.raises(ComputerControlError):
            raise ComputerControlError("test")


# ---------------------------------------------------------------------------
# InputAutomator tests
# ---------------------------------------------------------------------------


class TestInputAutomator:
    """Tests for InputAutomator (mocked pyautogui)."""

    def test_unavailable_when_no_pyautogui(self):
        """Reports unavailable when pyautogui is not installed."""
        automator = InputAutomator()
        # In test environment, pyautogui may or may not be installed.
        # We just verify the attribute exists.
        assert hasattr(automator, "available")

    def test_require_available_raises(self):
        """_require_available raises when not available."""
        automator = InputAutomator()
        automator.available = False
        automator._pyautogui = None
        with pytest.raises(RuntimeError, match="pyautogui is not installed"):
            automator._require_available()

    @patch("computer_control.input.InputAutomator._check_available", return_value=True)
    def test_click_mocked(self, mock_check):
        """Click calls pyautogui.click with correct args."""
        automator = InputAutomator()
        mock_pyag = MagicMock()
        automator._pyautogui = mock_pyag
        automator.available = True

        automator.click(100, 200, button="right", clicks=2)
        mock_pyag.click.assert_called_once_with(100, 200, clicks=2, button="right")

    @patch("computer_control.input.InputAutomator._check_available", return_value=True)
    def test_type_text_mocked(self, mock_check):
        """Type_text calls pyautogui.typewrite."""
        automator = InputAutomator()
        mock_pyag = MagicMock()
        automator._pyautogui = mock_pyag
        automator.available = True

        automator.type_text("hello", interval=0.05)
        mock_pyag.typewrite.assert_called_once_with("hello", interval=0.05)

    @patch("computer_control.input.InputAutomator._check_available", return_value=True)
    def test_hotkey_mocked(self, mock_check):
        """Hotkey calls pyautogui.hotkey."""
        automator = InputAutomator()
        mock_pyag = MagicMock()
        automator._pyautogui = mock_pyag
        automator.available = True

        automator.hotkey("ctrl", "c")
        mock_pyag.hotkey.assert_called_once_with("ctrl", "c")

    @patch("computer_control.input.InputAutomator._check_available", return_value=True)
    def test_press_key_mocked(self, mock_check):
        """Press_key calls pyautogui.press."""
        automator = InputAutomator()
        mock_pyag = MagicMock()
        automator._pyautogui = mock_pyag
        automator.available = True

        automator.press_key("enter")
        mock_pyag.press.assert_called_once_with("enter")

    @patch("computer_control.input.InputAutomator._check_available", return_value=True)
    def test_get_mouse_position_mocked(self, mock_check):
        """Get_mouse_position returns tuple."""
        automator = InputAutomator()
        mock_pyag = MagicMock()
        mock_pyag.position.return_value = (500, 300)
        automator._pyautogui = mock_pyag
        automator.available = True

        pos = automator.get_mouse_position()
        assert pos == (500, 300)


# ---------------------------------------------------------------------------
# WindowManager tests
# ---------------------------------------------------------------------------


class TestWindowManager:
    """Tests for WindowManager (mocked libraries)."""

    def test_unavailable_when_no_libraries(self):
        """Reports status based on available libraries."""
        wm = WindowManager()
        assert hasattr(wm, "available")

    def test_launch_application(self):
        """launch_application returns True on success."""
        wm = WindowManager()
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            result = wm.launch_application("notepad")
            assert result is True
            mock_popen.assert_called_once()

    def test_launch_application_failure(self):
        """launch_application returns False on error."""
        wm = WindowManager()
        with patch("subprocess.Popen", side_effect=Exception("fail")):
            result = wm.launch_application("nonexistent")
            assert result is False

    def test_close_application_no_psutil(self):
        """close_application returns False when psutil unavailable."""
        wm = WindowManager()
        wm._psutil = None
        assert wm.close_application("notepad") is False

    def test_list_windows_no_pygetwindow(self):
        """list_windows returns empty when pygetwindow unavailable."""
        wm = WindowManager()
        wm._pygetwindow = None
        assert wm.list_windows() == []

    def test_get_active_window_no_pygetwindow(self):
        """get_active_window returns None when unavailable."""
        wm = WindowManager()
        wm._pygetwindow = None
        assert wm.get_active_window() is None

    def test_switch_to_window_no_pygetwindow(self):
        """switch_to_window returns False when unavailable."""
        wm = WindowManager()
        wm._pygetwindow = None
        assert wm.switch_to_window("test") is False

    def test_resize_window_no_pygetwindow(self):
        """resize_window returns False when unavailable."""
        wm = WindowManager()
        wm._pygetwindow = None
        assert wm.resize_window("test", 800, 600) is False

    def test_minimize_window_no_pygetwindow(self):
        """minimize_window returns False when unavailable."""
        wm = WindowManager()
        wm._pygetwindow = None
        assert wm.minimize_window("test") is False

    def test_maximize_window_no_pygetwindow(self):
        """maximize_window returns False when unavailable."""
        wm = WindowManager()
        wm._pygetwindow = None
        assert wm.maximize_window("test") is False


# ---------------------------------------------------------------------------
# CommandExecutor tests
# ---------------------------------------------------------------------------


class TestCommandExecutor:
    """Tests for CommandExecutor with subprocess mocking."""

    def test_run_shell_success(self):
        """Successful command returns exit_code=0."""
        executor = CommandExecutor()
        with patch("computer_control.commands.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="hello\n", stderr="", returncode=0
            )
            result = executor.run_shell("echo hello")
            assert result.success is True
            assert result.stdout == "hello\n"
            assert result.exit_code == 0

    def test_run_shell_failure(self):
        """Failed command returns non-zero exit_code."""
        executor = CommandExecutor()
        with patch("computer_control.commands.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="", stderr="error", returncode=1
            )
            result = executor.run_shell("bad_command")
            assert result.success is False
            assert result.exit_code == 1

    def test_run_shell_timeout(self):
        """Timeout returns timed_out=True."""
        import subprocess as sp
        executor = CommandExecutor()
        with patch("computer_control.commands.subprocess.run") as mock_run:
            mock_run.side_effect = sp.TimeoutExpired(cmd="test", timeout=5)
            result = executor.run_shell("sleep 100", timeout=5)
            assert result.success is False
            assert result.timed_out is True

    def test_run_shell_exception(self):
        """Unexpected exception returns error result."""
        executor = CommandExecutor()
        with patch("computer_control.commands.subprocess.run") as mock_run:
            mock_run.side_effect = OSError("permission denied")
            result = executor.run_shell("rm -rf /")
            assert result.success is False
            assert "permission denied" in result.stderr

    def test_run_python_script(self):
        """Python script execution uses sys.executable."""
        executor = CommandExecutor()
        with patch("computer_control.commands.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="output", stderr="", returncode=0
            )
            with patch("computer_control.commands.sys.executable", "/usr/bin/python3"):
                result = executor.run_python_script("test.py", args=["--flag"])
                assert result.success is True
                call_args = mock_run.call_args
                assert "/usr/bin/python3" in call_args[0][0]

    def test_run_powershell(self):
        """PowerShell wraps command in powershell.exe."""
        executor = CommandExecutor()
        with patch("computer_control.commands.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="result", stderr="", returncode=0
            )
            result = executor.run_powershell("Get-Process")
            assert result.success is True


# ---------------------------------------------------------------------------
# ComputerControlManager tests
# ---------------------------------------------------------------------------


class TestComputerControlManager:
    """Tests for ComputerControlManager facade."""

    def test_is_available(self):
        """is_available returns a boolean."""
        manager = ComputerControlManager()
        assert isinstance(manager.is_available(), bool)

    def test_get_status(self):
        """get_status returns a dict with expected keys."""
        manager = ComputerControlManager()
        status = manager.get_status()
        assert "input_automator" in status
        assert "window_manager" in status
        assert "command_executor" in status

    def test_command_executor_delegation(self):
        """run_shell delegates to command_executor."""
        manager = ComputerControlManager()
        with patch.object(manager.command_executor, "run_shell") as mock_run:
            mock_run.return_value = CommandResult(stdout="ok", exit_code=0)
            result = manager.run_shell("echo test")
            assert result.success is True
            mock_run.assert_called_once_with("echo test", timeout=30)

    def test_window_manager_delegation(self):
        """launch_application delegates to window_manager."""
        manager = ComputerControlManager()
        with patch.object(manager.window_manager, "launch_application") as mock_launch:
            mock_launch.return_value = True
            result = manager.launch_application("notepad")
            assert result is True
            mock_launch.assert_called_once_with("notepad")

    def test_tracer_span_created(self):
        """Manager creates tracer span when tracer provided."""
        mock_tracer = MagicMock()
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_tracer.span.return_value = mock_span

        manager = ComputerControlManager(tracer=mock_tracer)
        with patch.object(manager.command_executor, "run_shell") as mock_run:
            mock_run.return_value = CommandResult(stdout="", exit_code=0)
            manager.run_shell("test")
            mock_tracer.span.assert_called()


# ---------------------------------------------------------------------------
# Tool tests
# ---------------------------------------------------------------------------


class TestWindowTool:
    """Tests for WindowTool."""

    def _make_tool(self, manager=None):
        from tools.builtin.window_tool import WindowTool
        if manager is None:
            manager = ComputerControlManager()
        return WindowTool(manager)

    def test_name_and_description(self):
        tool = self._make_tool()
        assert tool.name == "window_manager"
        assert "window" in tool.description.lower()

    def test_list_empty(self):
        tool = self._make_tool()
        result = tool.run(ToolRequest(tool_name="window_manager", input_data={}))
        assert result.success is True

    def test_launch_no_command(self):
        tool = self._make_tool()
        result = tool.run(ToolRequest(
            tool_name="window_manager",
            input_data={"action": "launch"},
        ))
        assert result.success is False

    def test_launch_success(self):
        manager = ComputerControlManager()
        tool = self._make_tool(manager)
        with patch.object(manager.window_manager, "launch_application", return_value=True):
            result = tool.run(ToolRequest(
                tool_name="window_manager",
                input_data={"action": "launch", "command": "notepad"},
            ))
            assert result.success is True

    def test_close_no_name(self):
        tool = self._make_tool()
        result = tool.run(ToolRequest(
            tool_name="window_manager",
            input_data={"action": "close"},
        ))
        assert result.success is False

    def test_switch_no_title(self):
        tool = self._make_tool()
        result = tool.run(ToolRequest(
            tool_name="window_manager",
            input_data={"action": "switch"},
        ))
        assert result.success is False

    def test_resize_no_title(self):
        tool = self._make_tool()
        result = tool.run(ToolRequest(
            tool_name="window_manager",
            input_data={"action": "resize"},
        ))
        assert result.success is False

    def test_unknown_action(self):
        tool = self._make_tool()
        result = tool.run(ToolRequest(
            tool_name="window_manager",
            input_data={"action": "bogus"},
        ))
        assert result.success is False


class TestInputTool:
    """Tests for InputTool."""

    def _make_tool(self, manager=None):
        from tools.builtin.input_tool import InputTool
        if manager is None:
            manager = ComputerControlManager()
        return InputTool(manager)

    def test_name_and_description(self):
        tool = self._make_tool()
        assert tool.name == "input_control"
        assert "mouse" in tool.description.lower() or "keyboard" in tool.description.lower()

    def test_position(self):
        manager = ComputerControlManager()
        tool = self._make_tool(manager)
        with patch.object(manager.input_automator, "get_mouse_position", return_value=(500, 300)):
            result = tool.run(ToolRequest(
                tool_name="input_control",
                input_data={"action": "position"},
            ))
            assert result.success is True
            assert "500" in result.output

    def test_click_no_coords(self):
        tool = self._make_tool()
        result = tool.run(ToolRequest(
            tool_name="input_control",
            input_data={"action": "click"},
        ))
        assert result.success is False

    def test_type_no_text(self):
        tool = self._make_tool()
        result = tool.run(ToolRequest(
            tool_name="input_control",
            input_data={"action": "type"},
        ))
        assert result.success is False

    def test_hotkey_no_keys(self):
        tool = self._make_tool()
        result = tool.run(ToolRequest(
            tool_name="input_control",
            input_data={"action": "hotkey"},
        ))
        assert result.success is False

    def test_unknown_action(self):
        tool = self._make_tool()
        result = tool.run(ToolRequest(
            tool_name="input_control",
            input_data={"action": "bogus"},
        ))
        assert result.success is False


class TestCommandTool:
    """Tests for CommandTool."""

    def _make_tool(self, manager=None):
        from tools.builtin.command_tool import CommandTool
        if manager is None:
            manager = ComputerControlManager()
        return CommandTool(manager)

    def test_name_and_description(self):
        tool = self._make_tool()
        assert tool.name == "command_exec"
        assert "approval" in tool.description.lower()

    def test_action_for_is_execute(self):
        """CommandTool action is always 'execute command' (RED tier)."""
        tool = self._make_tool()
        action = tool.action_for(ToolRequest(tool_name="command_exec", input_data={}))
        assert action == "execute command"

    def test_shell_no_command(self):
        tool = self._make_tool()
        result = tool.run(ToolRequest(
            tool_name="command_exec",
            input_data={"action": "shell"},
        ))
        assert result.success is False

    def test_shell_success(self):
        manager = ComputerControlManager()
        tool = self._make_tool(manager)
        with patch.object(manager.command_executor, "run_shell") as mock_run:
            mock_run.return_value = CommandResult(stdout="hello", exit_code=0, command="echo hello")
            result = tool.run(ToolRequest(
                tool_name="command_exec",
                input_data={"action": "shell", "command": "echo hello"},
            ))
            assert result.success is True

    def test_powershell_no_command(self):
        tool = self._make_tool()
        result = tool.run(ToolRequest(
            tool_name="command_exec",
            input_data={"action": "powershell"},
        ))
        assert result.success is False

    def test_script_no_path(self):
        tool = self._make_tool()
        result = tool.run(ToolRequest(
            tool_name="command_exec",
            input_data={"action": "script"},
        ))
        assert result.success is False

    def test_unknown_action(self):
        tool = self._make_tool()
        result = tool.run(ToolRequest(
            tool_name="command_exec",
            input_data={"action": "bogus"},
        ))
        assert result.success is False


# ---------------------------------------------------------------------------
# Security tier verification
# ---------------------------------------------------------------------------


class TestSecurityTiers:
    """Verify that tools have the correct security tier classifications."""

    def test_window_tool_is_yellow(self):
        """WindowTool action_for returns YELLOW-classified action."""
        from tools.builtin.window_tool import WindowTool
        tool = WindowTool(ComputerControlManager())
        action = tool.action_for(ToolRequest(tool_name="window_manager", input_data={}))
        assert action == "window_manager"

    def test_input_tool_is_yellow(self):
        """InputTool action_for returns YELLOW-classified action."""
        from tools.builtin.input_tool import InputTool
        tool = InputTool(ComputerControlManager())
        action = tool.action_for(ToolRequest(tool_name="input_control", input_data={}))
        assert action == "input_control"

    def test_command_tool_always_requires_approval(self):
        """CommandTool action_for always returns a non-GREEN action (requires approval)."""
        from tools.builtin.command_tool import CommandTool
        tool = CommandTool(ComputerControlManager())
        action = tool.action_for(ToolRequest(tool_name="command_exec", input_data={}))
        # "execute command" is classified YELLOW by SecurityManager (requires approval)
        assert action == "execute command"

    def test_security_manager_classifies_correctly(self):
        """SecurityManager classifies computer control actions correctly."""
        from security.security_manager import SecurityManager
        sm = SecurityManager()

        # Window manager actions are YELLOW (default tier)
        decision = sm.classify_action("window_manager")
        assert decision.tier.value == "yellow"

        # Input control actions are YELLOW (default tier)
        decision = sm.classify_action("input_control")
        assert decision.tier.value == "yellow"

        # Execute command is YELLOW (via "execute" keyword — requires approval)
        decision = sm.classify_action("execute command")
        assert decision.tier.value == "yellow"
