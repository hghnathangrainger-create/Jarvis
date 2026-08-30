"""
models.py

Data models for the Jarvis plugin system.

Responsibilities:
    - Define the Permission enum controlling what plugins can access.
    - Define PluginManifest describing a plugin's metadata and capabilities.
    - Define PluginConfig for per-plugin enabled/settings state.

Does NOT:
    - Load, discover, or execute plugins (see loader.py).
    - Enforce permissions (see sandbox.py).
    - Persist plugin state (see registry.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Permission(str, Enum):
    """Permissions a plugin can request.

    Each permission controls access to a specific Jarvis subsystem.
    Plugins declare which permissions they need in their manifest;
    the sandbox enforces these at runtime.

    Values are strings so they serialise cleanly to JSON and manifest files.
    """

    READ_MEMORY = "read_memory"
    WRITE_MEMORY = "write_memory"
    CALL_AI = "call_ai"
    EXECUTE_TOOLS = "execute_tools"
    ACCESS_NETWORK = "access_network"
    MODIFY_FILES = "modify_files"


# Permissions that are considered high-risk (RED-tier equivalent).
# Plugins requesting these need explicit approval during loading.
HIGH_RISK_PERMISSIONS: frozenset[Permission] = frozenset(
    {Permission.EXECUTE_TOOLS, Permission.MODIFY_FILES}
)


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """Metadata describing a Jarvis plugin.

    Every plugin must have a manifest.json at its root containing these
    fields. The loader validates manifests before importing any plugin code.

    Attributes:
        name: Unique plugin identifier (lowercase, no spaces).
        version: Semver-style version string.
        author: Plugin author name.
        description: Short human-readable description.
        entry_point: Python module path relative to the plugin directory
            (e.g. "plugin"). The module must implement a register() function.
        permissions: List of Permission values this plugin requires.
        min_jarvis_version: Minimum Jarvis version required (e.g. "0.2.0").
    """

    name: str
    version: str
    author: str
    description: str
    entry_point: str
    permissions: tuple[Permission, ...] = ()
    min_jarvis_version: str = "0.1.0"

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for JSON persistence."""
        return {
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "entry_point": self.entry_point,
            "permissions": [p.value for p in self.permissions],
            "min_jarvis_version": self.min_jarvis_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PluginManifest:
        """Deserialise from a plain dict (e.g. parsed manifest.json).

        Args:
            data: A dict with keys matching the manifest fields.

        Returns:
            A PluginManifest instance.

        Raises:
            ValueError: If required fields are missing or permissions are invalid.
        """
        required = ("name", "version", "author", "description", "entry_point")
        for field_name in required:
            if field_name not in data or not str(data[field_name]).strip():
                raise ValueError(f"Manifest missing required field: {field_name}")

        raw_permissions = data.get("permissions", [])
        permissions = []
        for p in raw_permissions:
            try:
                permissions.append(Permission(p))
            except ValueError:
                raise ValueError(
                    f"Unknown permission '{p}'. "
                    f"Valid permissions: {[ep.value for ep in Permission]}"
                )

        return cls(
            name=str(data["name"]).strip(),
            version=str(data["version"]).strip(),
            author=str(data["author"]).strip(),
            description=str(data["description"]).strip(),
            entry_point=str(data["entry_point"]).strip(),
            permissions=tuple(permissions),
            min_jarvis_version=str(data.get("min_jarvis_version", "0.1.0")).strip(),
        )


@dataclass
class PluginConfig:
    """Runtime configuration for an installed plugin.

    Attributes:
        enabled: Whether the plugin is active and should be loaded on startup.
        settings: Plugin-specific key-value settings.
    """

    enabled: bool = True
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PluginContext:
    """Context passed to a plugin's register() function.

    Provides read-only access to Jarvis subsystems the plugin needs,
    scoped to its declared permissions.

    Attributes:
        memory: The MemoryManager instance (if READ_MEMORY/WRITE_MEMORY granted).
        metrics: The MetricsCollector instance (always available, read-only).
    """

    memory: Any = None
    metrics: Any = None
