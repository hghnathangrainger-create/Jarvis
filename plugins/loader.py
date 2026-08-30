"""
loader.py

Plugin loading system for the Jarvis AI Operating System.

Responsibilities:
    - Discover plugins from a plugins/installed/ directory.
    - Read and validate each plugin's manifest.json.
    - Validate permissions against the sandbox.
    - Import the plugin's entry point module.
    - Call the plugin's register() function and collect tool definitions.
    - Expose loaded plugins and their registered tools.

Does NOT:
    - Persist plugin state (see registry.py).
    - Enforce permissions at runtime (see sandbox.py).
    - Define plugin data models (see models.py).

Plugins are loaded as Python modules in the current process.
Subprocess isolation is explicitly deferred to a future phase.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from plugins.models import PluginContext, PluginManifest
from plugins.sandbox import PluginPermissionError, PluginSandbox
from tools.base_tool import BaseTool

logger = logging.getLogger(__name__)


class PluginLoadError(Exception):
    """Raised when a plugin fails to load."""


class LoadedPlugin:
    """A successfully loaded plugin with its manifest and tools.

    Attributes:
        manifest: The validated plugin manifest.
        module: The imported plugin module.
        tools: Tools registered by the plugin's register() function.
        directory: The plugin's directory on disk.
    """

    __slots__ = ("manifest", "module", "tools", "directory")

    def __init__(
        self,
        manifest: PluginManifest,
        module: ModuleType,
        tools: list[BaseTool],
        directory: Path,
    ) -> None:
        self.manifest = manifest
        self.module = module
        self.tools = tools
        self.directory = directory


class PluginLoader:
    """Discovers, validates, and loads plugins from disk.

    Attributes:
        _installed_dir: The directory to scan for plugins.
        _sandbox: The sandbox for permission validation.
    """

    def __init__(
        self,
        installed_dir: Path | str,
        sandbox: PluginSandbox,
    ) -> None:
        """Initialise the loader.

        Args:
            installed_dir: Path to the plugins/installed/ directory.
            sandbox: The sandbox for permission checking.
        """
        self._installed_dir = Path(installed_dir)
        self._sandbox = sandbox

    @property
    def installed_dir(self) -> Path:
        """Return the installed plugins directory."""
        return self._installed_dir

    def discover(self) -> list[Path]:
        """Discover plugin directories under the installed directory.

        A valid plugin directory must contain a manifest.json file.

        Returns:
            A sorted list of plugin directory paths.
        """
        if not self._installed_dir.is_dir():
            logger.debug(
                "Plugin directory does not exist: %s", self._installed_dir
            )
            return []

        plugins = []
        for child in sorted(self._installed_dir.iterdir()):
            if child.is_dir() and (child / "manifest.json").is_file():
                plugins.append(child)

        return plugins

    def load_manifest(self, plugin_dir: Path) -> PluginManifest:
        """Read and validate a plugin's manifest.json.

        Args:
            plugin_dir: The plugin's directory containing manifest.json.

        Returns:
            A validated PluginManifest.

        Raises:
            PluginLoadError: If the manifest is missing, invalid, or
                contains unknown permissions.
        """
        manifest_path = plugin_dir / "manifest.json"
        if not manifest_path.is_file():
            raise PluginLoadError(
                f"No manifest.json found in {plugin_dir}"
            )

        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PluginLoadError(
                f"Invalid JSON in {manifest_path}: {exc}"
            ) from exc

        try:
            manifest = PluginManifest.from_dict(raw)
        except ValueError as exc:
            raise PluginLoadError(
                f"Invalid manifest in {manifest_path}: {exc}"
            ) from exc

        return manifest

    def load_plugin(
        self,
        plugin_dir: Path,
        context: PluginContext | None = None,
    ) -> LoadedPlugin:
        """Load a single plugin: validate manifest, import, register.

        Args:
            plugin_dir: The plugin's directory.
            context: Optional context to pass to the plugin's register().

        Returns:
            A LoadedPlugin with the manifest, module, and registered tools.

        Raises:
            PluginLoadError: If any step of loading fails.
        """
        # 1. Validate manifest.
        manifest = self.load_manifest(plugin_dir)

        # 2. Check permissions with sandbox.
        self._sandbox.register_plugin(manifest)
        if self._sandbox.requires_high_risk_approval(manifest):
            logger.warning(
                "Plugin '%s' requests high-risk permissions: %s",
                manifest.name,
                [p.value for p in manifest.permissions if p in self._sandbox._plugin_permissions.get(manifest.name, frozenset())],
            )

        # 3. Import the entry point module.
        module = self._import_module(manifest, plugin_dir)

        # 4. Call register() to get tools.
        tools = self._call_register(module, manifest, context)

        logger.info(
            "Loaded plugin '%s' v%s with %d tool(s)",
            manifest.name,
            manifest.version,
            len(tools),
        )

        return LoadedPlugin(
            manifest=manifest,
            module=module,
            tools=tools,
            directory=plugin_dir,
        )

    def load_all(
        self,
        context: PluginContext | None = None,
    ) -> list[LoadedPlugin]:
        """Discover and load all enabled plugins.

        Args:
            context: Optional context to pass to each plugin's register().

        Returns:
            A list of successfully loaded plugins. Failed plugins are
            logged and skipped.
        """
        plugin_dirs = self.discover()
        loaded = []

        for plugin_dir in plugin_dirs:
            try:
                plugin = self.load_plugin(plugin_dir, context)
                loaded.append(plugin)
            except PluginLoadError as exc:
                logger.error(
                    "Failed to load plugin from %s: %s", plugin_dir, exc
                )
            except Exception as exc:
                logger.error(
                    "Unexpected error loading plugin from %s: %s",
                    plugin_dir,
                    exc,
                )

        return loaded

    def _import_module(
        self, manifest: PluginManifest, plugin_dir: Path
    ) -> ModuleType:
        """Import a plugin's entry point module.

        Args:
            manifest: The validated manifest.
            plugin_dir: The plugin's directory.

        Returns:
            The imported module.

        Raises:
            PluginLoadError: If the module cannot be imported.
        """
        entry_file = plugin_dir / f"{manifest.entry_point}.py"
        if not entry_file.is_file():
            raise PluginLoadError(
                f"Entry point '{manifest.entry_point}.py' not found "
                f"in {plugin_dir}"
            )

        module_name = f"jarvis_plugin_{manifest.name}"
        try:
            spec = importlib.util.spec_from_file_location(
                module_name, str(entry_file)
            )
            if spec is None or spec.loader is None:
                raise PluginLoadError(
                    f"Cannot create module spec for {entry_file}"
                )
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except PluginLoadError:
            raise
        except Exception as exc:
            raise PluginLoadError(
                f"Failed to import {entry_file}: {exc}"
            ) from exc

        return module

    def _call_register(
        self,
        module: ModuleType,
        manifest: PluginManifest,
        context: PluginContext | None,
    ) -> list[BaseTool]:
        """Call the plugin's register() function and collect tools.

        Args:
            module: The imported plugin module.
            manifest: The plugin's manifest.
            context: Optional context to pass.

        Returns:
            A list of BaseTool instances registered by the plugin.

        Raises:
            PluginLoadError: If register() is missing or returns invalid tools.
        """
        register_fn = getattr(module, "register", None)
        if register_fn is None:
            raise PluginLoadError(
                f"Plugin '{manifest.name}' has no register() function "
                f"in {manifest.entry_point}"
            )

        try:
            result = register_fn(context)
        except Exception as exc:
            raise PluginLoadError(
                f"Plugin '{manifest.name}' register() failed: {exc}"
            ) from exc

        if result is None:
            return []

        if not isinstance(result, list):
            raise PluginLoadError(
                f"Plugin '{manifest.name}' register() must return a list "
                f"of BaseTool instances, got {type(result).__name__}"
            )

        tools = []
        for tool in result:
            if not isinstance(tool, BaseTool):
                logger.warning(
                    "Plugin '%s' returned non-BaseTool item: %s",
                    manifest.name,
                    type(tool).__name__,
                )
                continue
            tools.append(tool)

        return tools
