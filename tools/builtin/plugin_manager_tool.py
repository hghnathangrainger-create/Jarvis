"""
plugin_manager_tool.py

A YELLOW tool that manages installed Jarvis plugins.

Lists, enables, disables, and shows info about installed plugins.
YELLOW because it modifies plugin state (enable/disable).

Supported operations (via the 'action' input):
    - "list": List all installed plugins (default).
    - "info": Show details for a specific plugin.
    - "enable": Enable a plugin by id.
    - "disable": Disable a plugin by id.
"""

from __future__ import annotations

from plugins.registry import PluginRegistry
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class PluginManagerTool(BaseTool):
    """Manages installed plugins: list, enable, disable, info.

    Attributes:
        _registry: The plugin registry for persistence.
    """

    def __init__(self, registry: PluginRegistry) -> None:
        """Initialise the tool with a plugin registry.

        Args:
            registry: The PluginRegistry for reading/writing plugin state.
        """
        self._registry = registry

    @property
    def name(self) -> str:
        return "plugin_manager"

    @property
    def description(self) -> str:
        return "Manage installed Jarvis plugins: list, enable, disable, info."

    def action_for(self, request: ToolRequest) -> str:
        """Return action string based on the operation.

        'enable' and 'disable' modify state, so they stay YELLOW.
        'list' and 'info' are read-only but this tool is YELLOW overall.
        """
        return "plugin_manager"

    def run(self, request: ToolRequest) -> ToolResult:
        """Handle a plugin management request.

        Args:
            request: The request with input_data containing:
                - action (str): "list", "info", "enable", or "disable".
                - plugin_id (str): Required for info/enable/disable.

        Returns:
            A ToolResult with formatted plugin data or status.
        """
        action = str(request.input_data.get("action", "list")).strip().lower()

        if action == "list":
            return self._list_plugins()
        elif action == "info":
            return self._info_plugin(request)
        elif action == "enable":
            return self._enable_plugin(request)
        elif action == "disable":
            return self._disable_plugin(request)
        else:
            return self.fail(
                f"Unknown action '{action}'. Use 'list', 'info', 'enable', or 'disable'."
            )

    def _list_plugins(self) -> ToolResult:
        """List all installed plugins."""
        plugins = self._registry.list_plugins()
        if not plugins:
            return self.ok("No plugins installed.")

        lines = [f"Installed Plugins ({len(plugins)}):", ""]
        for p in plugins:
            status = "enabled" if p.enabled else "disabled"
            perms = ", ".join(
                perm.value for perm in p.manifest.permissions
            ) or "none"
            lines.append(f"  {p.plugin_id} v{p.version} [{status}]")
            lines.append(f"    {p.manifest.description}")
            lines.append(f"    Author: {p.manifest.author}")
            lines.append(f"    Permissions: {perms}")
            lines.append("")

        return self.ok("\n".join(lines))

    def _info_plugin(self, request: ToolRequest) -> ToolResult:
        """Show detailed info for a specific plugin."""
        plugin_id = str(request.input_data.get("plugin_id", "")).strip()
        if not plugin_id:
            return self.fail("No plugin_id provided. Usage: plugin_id='weather'")

        entry = self._registry.get_plugin(plugin_id)
        if entry is None:
            return self.fail(f"Plugin '{plugin_id}' not found.")

        status = "enabled" if entry.enabled else "disabled"
        perms = ", ".join(
            perm.value for perm in entry.manifest.permissions
        ) or "none"
        last_used = (
            entry.last_used.isoformat() if entry.last_used else "never"
        )

        lines = [
            f"Plugin: {entry.name}",
            f"  Version: {entry.version}",
            f"  Status: {status}",
            f"  Author: {entry.manifest.author}",
            f"  Description: {entry.manifest.description}",
            f"  Permissions: {perms}",
            f"  Entry point: {entry.manifest.entry_point}",
            f"  Min Jarvis version: {entry.manifest.min_jarvis_version}",
            f"  Installed: {entry.installed_at.isoformat()}",
            f"  Last used: {last_used}",
            f"  Tools registered: {len(entry.manifest.to_dict())}",
        ]

        return self.ok("\n".join(lines))

    def _enable_plugin(self, request: ToolRequest) -> ToolResult:
        """Enable a plugin by id."""
        plugin_id = str(request.input_data.get("plugin_id", "")).strip()
        if not plugin_id:
            return self.fail("No plugin_id provided. Usage: plugin_id='weather'")

        found = self._registry.enable(plugin_id)
        if not found:
            return self.fail(f"Plugin '{plugin_id}' not found.")

        return self.ok(f"Plugin '{plugin_id}' enabled.")

    def _disable_plugin(self, request: ToolRequest) -> ToolResult:
        """Disable a plugin by id."""
        plugin_id = str(request.input_data.get("plugin_id", "")).strip()
        if not plugin_id:
            return self.fail("No plugin_id provided. Usage: plugin_id='weather'")

        found = self._registry.disable(plugin_id)
        if not found:
            return self.fail(f"Plugin '{plugin_id}' not found.")

        return self.ok(f"Plugin '{plugin_id}' disabled.")
