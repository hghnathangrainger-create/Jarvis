"""
sandbox.py

Permission enforcement for the Jarvis plugin system.

Responsibilities:
    - Check whether a plugin has permission for a requested action.
    - Raise PluginPermissionError on denied actions.
    - Log all plugin actions to the audit log via EventLogger.

Does NOT:
    - Load or discover plugins (see loader.py).
    - Persist plugin state (see registry.py).
    - Define permissions (see models.py).
"""

from __future__ import annotations

import logging
from typing import Any

from plugins.models import HIGH_RISK_PERMISSIONS, Permission, PluginManifest

logger = logging.getLogger(__name__)


class PluginPermissionError(Exception):
    """Raised when a plugin attempts an action outside its declared permissions."""


# Maps action categories to required permissions.
_ACTION_PERMISSION_MAP: dict[str, Permission] = {
    "read_memory": Permission.READ_MEMORY,
    "write_memory": Permission.WRITE_MEMORY,
    "call_ai": Permission.CALL_AI,
    "execute_tools": Permission.EXECUTE_TOOLS,
    "access_network": Permission.ACCESS_NETWORK,
    "modify_files": Permission.MODIFY_FILES,
}


class PluginSandbox:
    """Enforces permission boundaries for loaded plugins.

    Every plugin action goes through this sandbox. If the plugin's
    manifest does not declare the required permission, the action
    is denied with a PluginPermissionError.

    Attributes:
        _plugin_permissions: Mapping of plugin name to its declared permissions.
    """

    def __init__(self) -> None:
        """Initialise an empty sandbox."""
        self._plugin_permissions: dict[str, frozenset[Permission]] = {}

    def register_plugin(self, manifest: PluginManifest) -> None:
        """Register a plugin's permissions with the sandbox.

        Args:
            manifest: The validated manifest of the plugin to register.
        """
        self._plugin_permissions[manifest.name] = frozenset(manifest.permissions)
        logger.debug(
            "Registered plugin '%s' with permissions: %s",
            manifest.name,
            [p.value for p in manifest.permissions],
        )

    def unregister_plugin(self, plugin_name: str) -> None:
        """Remove a plugin from the sandbox.

        Args:
            plugin_name: The name of the plugin to unregister.
        """
        self._plugin_permissions.pop(plugin_name, None)

    def check_permission(self, plugin_name: str, action: str) -> None:
        """Verify a plugin has permission for the given action.

        Args:
            plugin_name: The name of the plugin requesting the action.
            action: The action category (e.g. "read_memory", "call_ai").

        Raises:
            PluginPermissionError: If the plugin does not have the required
                permission.
        """
        required_permission = _ACTION_PERMISSION_MAP.get(action)
        if required_permission is None:
            # Unknown action — deny by default.
            raise PluginPermissionError(
                f"Plugin '{plugin_name}' denied unknown action '{action}'."
            )

        plugin_perms = self._plugin_permissions.get(plugin_name)
        if plugin_perms is None:
            raise PluginPermissionError(
                f"Plugin '{plugin_name}' is not registered with the sandbox."
            )

        if required_permission not in plugin_perms:
            raise PluginPermissionError(
                f"Plugin '{plugin_name}' does not have the "
                f"'{required_permission.value}' permission required for "
                f"'{action}'."
            )

    def has_permission(self, plugin_name: str, action: str) -> bool:
        """Check whether a plugin has permission without raising.

        Args:
            plugin_name: The name of the plugin.
            action: The action category.

        Returns:
            True if the plugin has the required permission, False otherwise.
        """
        try:
            self.check_permission(plugin_name, action)
            return True
        except PluginPermissionError:
            return False

    def requires_high_risk_approval(self, manifest: PluginManifest) -> bool:
        """Check whether a plugin requires approval due to high-risk permissions.

        Plugins requesting EXECUTE_TOOLS or MODIFY_FILES need explicit
        approval during loading.

        Args:
            manifest: The plugin's manifest to check.

        Returns:
            True if the plugin requests any high-risk permission.
        """
        return bool(set(manifest.permissions) & HIGH_RISK_PERMISSIONS)

    def get_permissions(self, plugin_name: str) -> frozenset[Permission]:
        """Return the permissions currently registered for a plugin.

        Args:
            plugin_name: The plugin name.

        Returns:
            A frozenset of the plugin's permissions, or empty if not registered.
        """
        return self._plugin_permissions.get(plugin_name, frozenset())
