"""
registry.py

SQLite-backed plugin registry for the Jarvis AI Operating System.

Responsibilities:
    - Persist installed plugin records (register, unregister, list, get).
    - Track enabled/disabled state per plugin.
    - Record installed_at and last_used timestamps.

Does NOT:
    - Discover or load plugin code (see loader.py).
    - Enforce permissions (see sandbox.py).
    - Execute plugin tools (see tools/executor.py).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from plugins.models import PluginManifest
from storage.models import PluginEntry

logger = logging.getLogger(__name__)


class PluginRegistryEntry:
    """A serialisable view of a plugin registry row."""

    __slots__ = (
        "plugin_id",
        "name",
        "version",
        "manifest",
        "enabled",
        "installed_at",
        "last_used",
    )

    def __init__(
        self,
        *,
        plugin_id: str,
        name: str,
        version: str,
        manifest: PluginManifest,
        enabled: bool,
        installed_at: datetime,
        last_used: datetime | None,
    ) -> None:
        self.plugin_id = plugin_id
        self.name = name
        self.version = version
        self.manifest = manifest
        self.enabled = enabled
        self.installed_at = installed_at
        self.last_used = last_used

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "enabled": self.enabled,
            "installed_at": self.installed_at.isoformat(),
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "permissions": [p.value for p in self.manifest.permissions],
            "author": self.manifest.author,
            "description": self.manifest.description,
        }


class PluginRegistry:
    """SQLite-backed registry for installed plugins.

    Attributes:
        _session_factory: Factory used to open database sessions.
    """

    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        """Initialise with a database session factory.

        Args:
            session_factory: Typically produced by
                storage.database.create_session_factory.
        """
        self._session_factory = session_factory

    def register(self, manifest: PluginManifest) -> PluginRegistryEntry:
        """Register a new plugin or update an existing one.

        If a plugin with the same id already exists, its manifest and
        version are updated. The enabled state is preserved.

        Args:
            manifest: The plugin's validated manifest.

        Returns:
            The registered PluginRegistryEntry.
        """
        with self._session_factory() as session:  # type: ignore[call-arg]
            entry = session.execute(
                select(PluginEntry).where(
                    PluginEntry.plugin_id == manifest.name
                )
            ).scalar_one_or_none()

            if entry is not None:
                # Update existing entry.
                entry.name = manifest.name
                entry.version = manifest.version
                entry.manifest_json = json.dumps(manifest.to_dict())
                entry.last_used = datetime.now(timezone.utc)
                session.commit()
                logger.info("Updated plugin: %s v%s", manifest.name, manifest.version)
            else:
                # Create new entry.
                entry = PluginEntry(
                    plugin_id=manifest.name,
                    name=manifest.name,
                    version=manifest.version,
                    manifest_json=json.dumps(manifest.to_dict()),
                    enabled=True,
                )
                session.add(entry)
                session.commit()
                logger.info("Registered plugin: %s v%s", manifest.name, manifest.version)

            return self._to_registry_entry(entry)

    def unregister(self, plugin_id: str) -> bool:
        """Remove a plugin from the registry.

        Args:
            plugin_id: The unique plugin identifier to remove.

        Returns:
            True if the plugin was found and removed, False otherwise.
        """
        with self._session_factory() as session:  # type: ignore[call-arg]
            entry = session.execute(
                select(PluginEntry).where(PluginEntry.plugin_id == plugin_id)
            ).scalar_one_or_none()

            if entry is None:
                return False

            session.delete(entry)
            session.commit()
            logger.info("Unregistered plugin: %s", plugin_id)
            return True

    def list_plugins(self) -> list[PluginRegistryEntry]:
        """Return all registered plugins, sorted by name.

        Returns:
            A list of PluginRegistryEntry objects.
        """
        with self._session_factory() as session:  # type: ignore[call-arg]
            entries = session.execute(
                select(PluginEntry).order_by(PluginEntry.name)
            ).scalars().all()
            return [self._to_registry_entry(e) for e in entries]

    def get_plugin(self, plugin_id: str) -> PluginRegistryEntry | None:
        """Retrieve a single plugin by id.

        Args:
            plugin_id: The plugin identifier to look up.

        Returns:
            A PluginRegistryEntry, or None if not found.
        """
        with self._session_factory() as session:  # type: ignore[call-arg]
            entry = session.execute(
                select(PluginEntry).where(PluginEntry.plugin_id == plugin_id)
            ).scalar_one_or_none()
            if entry is None:
                return None
            return self._to_registry_entry(entry)

    def enable(self, plugin_id: str) -> bool:
        """Enable a plugin.

        Args:
            plugin_id: The plugin identifier to enable.

        Returns:
            True if the plugin was found and enabled, False otherwise.
        """
        with self._session_factory() as session:  # type: ignore[call-arg]
            entry = session.execute(
                select(PluginEntry).where(PluginEntry.plugin_id == plugin_id)
            ).scalar_one_or_none()

            if entry is None:
                return False

            entry.enabled = True
            session.commit()
            logger.info("Enabled plugin: %s", plugin_id)
            return True

    def disable(self, plugin_id: str) -> bool:
        """Disable a plugin.

        Args:
            plugin_id: The plugin identifier to disable.

        Returns:
            True if the plugin was found and disabled, False otherwise.
        """
        with self._session_factory() as session:  # type: ignore[call-arg]
            entry = session.execute(
                select(PluginEntry).where(PluginEntry.plugin_id == plugin_id)
            ).scalar_one_or_none()

            if entry is None:
                return False

            entry.enabled = False
            session.commit()
            logger.info("Disabled plugin: %s", plugin_id)
            return True

    def mark_used(self, plugin_id: str) -> None:
        """Update the last_used timestamp for a plugin.

        Args:
            plugin_id: The plugin identifier to mark as used.
        """
        with self._session_factory() as session:  # type: ignore[call-arg]
            entry = session.execute(
                select(PluginEntry).where(PluginEntry.plugin_id == plugin_id)
            ).scalar_one_or_none()

            if entry is not None:
                entry.last_used = datetime.now(timezone.utc)
                session.commit()

    @staticmethod
    def _to_registry_entry(entry: PluginEntry) -> PluginRegistryEntry:
        """Convert a DB row to a PluginRegistryEntry view.

        Args:
            entry: The SQLAlchemy PluginEntry model instance.

        Returns:
            A PluginRegistryEntry view object.
        """
        manifest_dict = json.loads(entry.manifest_json)
        manifest = PluginManifest.from_dict(manifest_dict)
        return PluginRegistryEntry(
            plugin_id=entry.plugin_id,
            name=entry.name,
            version=entry.version,
            manifest=manifest,
            enabled=entry.enabled,
            installed_at=entry.installed_at,
            last_used=entry.last_used,
        )
