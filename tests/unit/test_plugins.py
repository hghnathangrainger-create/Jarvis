"""
test_plugins.py

Unit tests for the Jarvis plugin system.

Covers:
    - PluginManifest validation (from_dict, to_dict, required fields, permissions)
    - PluginRegistry (SQLite-backed CRUD: register, unregister, list, enable, disable)
    - PluginLoader (discovery, manifest loading, plugin loading, register() call)
    - PluginSandbox (permission checking, high-risk detection)
    - PluginManagerTool (list, info, enable, disable)

Run with:
    pytest tests/unit/test_plugins.py
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine

from plugins.loader import PluginLoadError, PluginLoader, LoadedPlugin
from plugins.models import (
    HIGH_RISK_PERMISSIONS,
    Permission,
    PluginConfig,
    PluginContext,
    PluginManifest,
)
from plugins.registry import PluginRegistry
from plugins.sandbox import PluginPermissionError, PluginSandbox
from storage.database import create_session_factory, initialize_database
from tools.base_tool import BaseTool, ToolRequest, ToolResult


_SENTINEL = object()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_factory():
    """Build a session factory backed by an in-memory SQLite database."""
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


@pytest.fixture()
def plugin_registry(session_factory):
    """Build a PluginRegistry backed by a fresh in-memory database."""
    return PluginRegistry(session_factory)


@pytest.fixture()
def sandbox():
    """Build a fresh PluginSandbox."""
    return PluginSandbox()


@pytest.fixture()
def tmp_plugins_dir(tmp_path):
    """Create a temporary plugins/installed directory."""
    installed = tmp_path / "plugins" / "installed"
    installed.mkdir(parents=True)
    return installed


def _make_manifest(
    name: str = "test_plugin",
    version: str = "1.0.0",
    author: str = "Test Author",
    description: str = "A test plugin",
    entry_point: str = "plugin",
    permissions: list[str] | None = None,
    min_jarvis_version: str = "0.1.0",
) -> dict[str, Any]:
    """Build a manifest dict for testing."""
    return {
        "name": name,
        "version": version,
        "author": author,
        "description": description,
        "entry_point": entry_point,
        "permissions": permissions or [],
        "min_jarvis_version": min_jarvis_version,
    }


def _install_plugin(
    tmp_path: Path,
    name: str = "test_plugin",
    permissions: list[str] | None = None,
    register_return: object = _SENTINEL,
    register_error: bool = False,
    missing_register: bool = False,
    bad_return: bool = False,
) -> Path:
    """Helper to install a test plugin into tmp_path/plugins/installed/.

    Returns the plugin directory path.
    """
    plugin_dir = tmp_path / "plugins" / "installed" / name
    plugin_dir.mkdir(parents=True, exist_ok=True)

    manifest = _make_manifest(name=name, permissions=permissions or [])
    (plugin_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    if not missing_register:
        lines = []
        if register_error:
            lines.append("def register(context=None):")
            lines.append('    raise RuntimeError("Plugin init failed")')
        elif bad_return:
            lines.append("def register(context=None):")
            lines.append('    return "not a list"')
        else:
            lines.append("from tools.base_tool import BaseTool, ToolRequest, ToolResult")
            lines.append("")
            lines.append("")
            lines.append("class FakeTool(BaseTool):")
            lines.append("    @property")
            lines.append("    def name(self):")
            lines.append(f'        return "{name}_tool"')
            lines.append("    @property")
            lines.append("    def description(self):")
            lines.append('        return "Fake tool for testing"')
            lines.append("    def run(self, request):")
            lines.append('        return ToolResult(tool_name=self.name, success=True, output="ok")')
            lines.append("")
            lines.append("def register(context=None):")
            if register_return is not _SENTINEL:
                lines.append(f"    return {register_return!r}")
            else:
                lines.append("    return [FakeTool()]")

        (plugin_dir / "plugin.py").write_text(
            "\n".join(lines), encoding="utf-8"
        )

    return plugin_dir


# ---------------------------------------------------------------------------
# PluginManifest tests
# ---------------------------------------------------------------------------


class TestPluginManifest:
    """Tests for PluginManifest validation and serialisation."""

    def test_from_dict_valid(self):
        """Valid manifest dict produces a PluginManifest."""
        data = _make_manifest()
        manifest = PluginManifest.from_dict(data)
        assert manifest.name == "test_plugin"
        assert manifest.version == "1.0.0"
        assert manifest.author == "Test Author"
        assert manifest.description == "A test plugin"
        assert manifest.entry_point == "plugin"
        assert manifest.permissions == ()
        assert manifest.min_jarvis_version == "0.1.0"

    def test_from_dict_with_permissions(self):
        """Manifest with permissions parses correctly."""
        data = _make_manifest(permissions=["read_memory", "access_network"])
        manifest = PluginManifest.from_dict(data)
        assert len(manifest.permissions) == 2
        assert Permission.READ_MEMORY in manifest.permissions
        assert Permission.ACCESS_NETWORK in manifest.permissions

    def test_from_dict_missing_name(self):
        """Manifest missing 'name' raises ValueError."""
        data = _make_manifest()
        del data["name"]
        with pytest.raises(ValueError, match="missing required field: name"):
            PluginManifest.from_dict(data)

    def test_from_dict_missing_version(self):
        """Manifest missing 'version' raises ValueError."""
        data = _make_manifest()
        del data["version"]
        with pytest.raises(ValueError, match="missing required field: version"):
            PluginManifest.from_dict(data)

    def test_from_dict_missing_entry_point(self):
        """Manifest missing 'entry_point' raises ValueError."""
        data = _make_manifest()
        del data["entry_point"]
        with pytest.raises(ValueError, match="missing required field: entry_point"):
            PluginManifest.from_dict(data)

    def test_from_dict_empty_name(self):
        """Manifest with empty name raises ValueError."""
        data = _make_manifest(name="  ")
        with pytest.raises(ValueError, match="missing required field: name"):
            PluginManifest.from_dict(data)

    def test_from_dict_unknown_permission(self):
        """Manifest with unknown permission raises ValueError."""
        data = _make_manifest(permissions=["read_memory", "invalid_perm"])
        with pytest.raises(ValueError, match="Unknown permission"):
            PluginManifest.from_dict(data)

    def test_to_dict_roundtrip(self):
        """to_dict -> from_dict roundtrip preserves all fields."""
        data = _make_manifest(
            permissions=["read_memory", "call_ai"],
            min_jarvis_version="0.2.0",
        )
        manifest = PluginManifest.from_dict(data)
        serialised = manifest.to_dict()
        restored = PluginManifest.from_dict(serialised)
        assert restored == manifest

    def test_all_permissions_valid(self):
        """All Permission enum values are valid manifest permissions."""
        all_perms = [p.value for p in Permission]
        data = _make_manifest(permissions=all_perms)
        manifest = PluginManifest.from_dict(data)
        assert len(manifest.permissions) == len(Permission)


# ---------------------------------------------------------------------------
# PluginRegistry tests
# ---------------------------------------------------------------------------


class TestPluginRegistry:
    """Tests for SQLite-backed plugin registry CRUD."""

    def test_register_new_plugin(self, plugin_registry):
        """Registering a new plugin creates a registry entry."""
        manifest = PluginManifest.from_dict(_make_manifest())
        entry = plugin_registry.register(manifest)
        assert entry.plugin_id == "test_plugin"
        assert entry.name == "test_plugin"
        assert entry.version == "1.0.0"
        assert entry.enabled is True

    def test_register_updates_existing(self, plugin_registry):
        """Registering the same plugin id updates the existing entry."""
        manifest = PluginManifest.from_dict(_make_manifest(version="1.0.0"))
        plugin_registry.register(manifest)

        manifest2 = PluginManifest.from_dict(_make_manifest(version="2.0.0"))
        entry = plugin_registry.register(manifest2)
        assert entry.version == "2.0.0"
        # Only one plugin should exist.
        assert len(plugin_registry.list_plugins()) == 1

    def test_unregister(self, plugin_registry):
        """Unregistering removes the plugin."""
        manifest = PluginManifest.from_dict(_make_manifest())
        plugin_registry.register(manifest)
        assert plugin_registry.unregister("test_plugin") is True
        assert plugin_registry.get_plugin("test_plugin") is None

    def test_unregister_nonexistent(self, plugin_registry):
        """Unregistering a nonexistent plugin returns False."""
        assert plugin_registry.unregister("nope") is False

    def test_list_plugins_sorted(self, plugin_registry):
        """list_plugins returns plugins sorted by name."""
        plugin_registry.register(
            PluginManifest.from_dict(_make_manifest(name="beta"))
        )
        plugin_registry.register(
            PluginManifest.from_dict(_make_manifest(name="alpha"))
        )
        plugin_registry.register(
            PluginManifest.from_dict(_make_manifest(name="gamma"))
        )
        plugins = plugin_registry.list_plugins()
        assert len(plugins) == 3
        assert [p.name for p in plugins] == ["alpha", "beta", "gamma"]

    def test_get_plugin(self, plugin_registry):
        """get_plugin returns the correct entry."""
        manifest = PluginManifest.from_dict(_make_manifest())
        plugin_registry.register(manifest)
        entry = plugin_registry.get_plugin("test_plugin")
        assert entry is not None
        assert entry.manifest.name == "test_plugin"

    def test_get_plugin_nonexistent(self, plugin_registry):
        """get_plugin returns None for unknown id."""
        assert plugin_registry.get_plugin("nope") is None

    def test_enable_disable(self, plugin_registry):
        """enable and disable toggle the enabled state."""
        manifest = PluginManifest.from_dict(_make_manifest())
        plugin_registry.register(manifest)

        assert plugin_registry.disable("test_plugin") is True
        entry = plugin_registry.get_plugin("test_plugin")
        assert entry.enabled is False

        assert plugin_registry.enable("test_plugin") is True
        entry = plugin_registry.get_plugin("test_plugin")
        assert entry.enabled is True

    def test_enable_nonexistent(self, plugin_registry):
        """Enabling a nonexistent plugin returns False."""
        assert plugin_registry.enable("nope") is False

    def test_disable_nonexistent(self, plugin_registry):
        """Disabling a nonexistent plugin returns False."""
        assert plugin_registry.disable("nope") is False

    def test_mark_used(self, plugin_registry):
        """mark_used updates the last_used timestamp."""
        manifest = PluginManifest.from_dict(_make_manifest())
        plugin_registry.register(manifest)

        entry = plugin_registry.get_plugin("test_plugin")
        assert entry.last_used is None

        plugin_registry.mark_used("test_plugin")
        entry = plugin_registry.get_plugin("test_plugin")
        assert entry.last_used is not None

    def test_to_dict_serialisation(self, plugin_registry):
        """Registry entry to_dict produces expected keys."""
        manifest = PluginManifest.from_dict(
            _make_manifest(permissions=["read_memory"])
        )
        entry = plugin_registry.register(manifest)
        d = entry.to_dict()
        assert d["plugin_id"] == "test_plugin"
        assert d["enabled"] is True
        assert "read_memory" in d["permissions"]
        assert "installed_at" in d


# ---------------------------------------------------------------------------
# PluginSandbox tests
# ---------------------------------------------------------------------------


class TestPluginSandbox:
    """Tests for permission enforcement."""

    def test_register_and_check(self, sandbox):
        """Registered plugin with correct permission passes check."""
        manifest = PluginManifest.from_dict(
            _make_manifest(permissions=["read_memory"])
        )
        sandbox.register_plugin(manifest)
        sandbox.check_permission("test_plugin", "read_memory")  # no error

    def test_denied_permission(self, sandbox):
        """Plugin without required permission gets denied."""
        manifest = PluginManifest.from_dict(
            _make_manifest(permissions=["read_memory"])
        )
        sandbox.register_plugin(manifest)
        with pytest.raises(PluginPermissionError, match="does not have"):
            sandbox.check_permission("test_plugin", "call_ai")

    def test_denied_unknown_action(self, sandbox):
        """Unknown action is denied by default."""
        manifest = PluginManifest.from_dict(
            _make_manifest(permissions=["read_memory"])
        )
        sandbox.register_plugin(manifest)
        with pytest.raises(PluginPermissionError, match="unknown action"):
            sandbox.check_permission("test_plugin", "totally_unknown_action")

    def test_unregistered_plugin_denied(self, sandbox):
        """Unregistered plugin is denied all actions."""
        with pytest.raises(PluginPermissionError, match="not registered"):
            sandbox.check_permission("unknown_plugin", "read_memory")

    def test_has_permission_true(self, sandbox):
        """has_permission returns True when permitted."""
        manifest = PluginManifest.from_dict(
            _make_manifest(permissions=["read_memory", "access_network"])
        )
        sandbox.register_plugin(manifest)
        assert sandbox.has_permission("test_plugin", "read_memory") is True
        assert sandbox.has_permission("test_plugin", "access_network") is True

    def test_has_permission_false(self, sandbox):
        """has_permission returns False when not permitted."""
        manifest = PluginManifest.from_dict(
            _make_manifest(permissions=["read_memory"])
        )
        sandbox.register_plugin(manifest)
        assert sandbox.has_permission("test_plugin", "call_ai") is False

    def test_unregister_plugin(self, sandbox):
        """Unregistering a plugin removes its permissions."""
        manifest = PluginManifest.from_dict(
            _make_manifest(permissions=["read_memory"])
        )
        sandbox.register_plugin(manifest)
        sandbox.unregister_plugin("test_plugin")
        assert sandbox.get_permissions("test_plugin") == frozenset()

    def test_high_risk_approval_needed(self, sandbox):
        """Plugins with EXECUTE_TOOLS or MODIFY_FILES are high-risk."""
        manifest = PluginManifest.from_dict(
            _make_manifest(permissions=["execute_tools"])
        )
        assert sandbox.requires_high_risk_approval(manifest) is True

        manifest2 = PluginManifest.from_dict(
            _make_manifest(permissions=["modify_files"])
        )
        assert sandbox.requires_high_risk_approval(manifest2) is True

    def test_low_risk_no_approval(self, sandbox):
        """Plugins with only low-risk permissions don't need approval."""
        manifest = PluginManifest.from_dict(
            _make_manifest(permissions=["read_memory", "access_network"])
        )
        assert sandbox.requires_high_risk_approval(manifest) is False

    def test_get_permissions_empty(self, sandbox):
        """get_permissions returns empty frozenset for unknown plugin."""
        assert sandbox.get_permissions("unknown") == frozenset()


# ---------------------------------------------------------------------------
# PluginLoader tests
# ---------------------------------------------------------------------------


class TestPluginLoader:
    """Tests for plugin discovery, validation, and loading."""

    def test_discover_empty_dir(self, tmp_plugins_dir):
        """Empty installed dir discovers no plugins."""
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_plugins_dir, sandbox)
        assert loader.discover() == []

    def test_discover_with_manifest(self, tmp_plugins_dir, tmp_path):
        """Directories with manifest.json are discovered."""
        _install_plugin(tmp_path, name="alpha")
        _install_plugin(tmp_path, name="beta")
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_plugins_dir, sandbox)
        discovered = loader.discover()
        assert len(discovered) == 2
        names = {d.name for d in discovered}
        assert names == {"alpha", "beta"}

    def test_discover_skips_dirs_without_manifest(self, tmp_plugins_dir):
        """Directories without manifest.json are skipped."""
        (tmp_plugins_dir / "not_a_plugin").mkdir()
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_plugins_dir, sandbox)
        assert loader.discover() == []

    def test_discover_nonexistent_dir(self, tmp_path):
        """Non-existent installed dir returns empty list."""
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_path / "nonexistent", sandbox)
        assert loader.discover() == []

    def test_load_manifest_valid(self, tmp_plugins_dir, tmp_path):
        """load_manifest reads a valid manifest.json."""
        plugin_dir = _install_plugin(tmp_path, name="test")
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_plugins_dir, sandbox)
        manifest = loader.load_manifest(plugin_dir)
        assert manifest.name == "test"

    def test_load_manifest_missing_file(self, tmp_plugins_dir, tmp_path):
        """load_manifest raises on missing manifest.json."""
        plugin_dir = tmp_plugins_dir / "empty_plugin"
        plugin_dir.mkdir()
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_plugins_dir, sandbox)
        with pytest.raises(PluginLoadError, match="No manifest.json"):
            loader.load_manifest(plugin_dir)

    def test_load_manifest_invalid_json(self, tmp_plugins_dir, tmp_path):
        """load_manifest raises on invalid JSON."""
        plugin_dir = tmp_plugins_dir / "bad_json"
        plugin_dir.mkdir()
        (plugin_dir / "manifest.json").write_text("{bad json", encoding="utf-8")
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_plugins_dir, sandbox)
        with pytest.raises(PluginLoadError, match="Invalid JSON"):
            loader.load_manifest(plugin_dir)

    def test_load_plugin_success(self, tmp_plugins_dir, tmp_path):
        """load_plugin successfully loads a valid plugin."""
        _install_plugin(tmp_path, name="good_plugin")
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_plugins_dir, sandbox)
        plugin_dir = tmp_plugins_dir / "good_plugin"
        loaded = loader.load_plugin(plugin_dir)
        assert loaded.manifest.name == "good_plugin"
        assert len(loaded.tools) == 1
        assert loaded.tools[0].name == "good_plugin_tool"

    def test_load_plugin_missing_entry_point(self, tmp_plugins_dir, tmp_path):
        """load_plugin raises when entry_point module is missing."""
        plugin_dir = tmp_plugins_dir / "no_entry"
        plugin_dir.mkdir()
        manifest = _make_manifest(name="no_entry")
        (plugin_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        # No plugin.py file.
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_plugins_dir, sandbox)
        with pytest.raises(PluginLoadError, match="Entry point"):
            loader.load_plugin(plugin_dir)

    def test_load_plugin_no_register_fn(self, tmp_plugins_dir, tmp_path):
        """load_plugin raises when plugin has no register() function."""
        plugin_dir = tmp_plugins_dir / "no_register"
        plugin_dir.mkdir()
        manifest = _make_manifest(name="no_register")
        (plugin_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (plugin_dir / "plugin.py").write_text(
            "# No register function here\nx = 1\n", encoding="utf-8"
        )
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_plugins_dir, sandbox)
        with pytest.raises(PluginLoadError, match="no register\\(\\) function"):
            loader.load_plugin(plugin_dir)

    def test_load_plugin_register_raises(self, tmp_plugins_dir, tmp_path):
        """load_plugin raises when register() throws an exception."""
        _install_plugin(tmp_path, name="bad_register", register_error=True)
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_plugins_dir, sandbox)
        with pytest.raises(PluginLoadError, match="register\\(\\) failed"):
            loader.load_plugin(tmp_plugins_dir / "bad_register")

    def test_load_plugin_bad_return(self, tmp_plugins_dir, tmp_path):
        """load_plugin raises when register() returns wrong type."""
        _install_plugin(tmp_path, name="bad_return", bad_return=True)
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_plugins_dir, sandbox)
        with pytest.raises(PluginLoadError, match="must return a list"):
            loader.load_plugin(tmp_plugins_dir / "bad_return")

    def test_load_plugin_empty_register(self, tmp_plugins_dir, tmp_path):
        """load_plugin handles register() returning None (no tools)."""
        _install_plugin(tmp_path, name="empty_register", register_return=None)
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_plugins_dir, sandbox)
        loaded = loader.load_plugin(tmp_plugins_dir / "empty_register")
        assert loaded.tools == []

    def test_load_all_skips_bad_plugins(self, tmp_plugins_dir, tmp_path):
        """load_all loads good plugins and skips bad ones."""
        _install_plugin(tmp_path, name="good_plugin")
        _install_plugin(tmp_path, name="bad_plugin", register_error=True)
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_plugins_dir, sandbox)
        loaded = loader.load_all()
        assert len(loaded) == 1
        assert loaded[0].manifest.name == "good_plugin"

    def test_load_plugin_registers_sandbox(self, tmp_plugins_dir, tmp_path):
        """load_plugin registers the plugin with the sandbox."""
        _install_plugin(
            tmp_path,
            name="sandboxed",
            permissions=["read_memory", "access_network"],
        )
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_plugins_dir, sandbox)
        loader.load_plugin(tmp_plugins_dir / "sandboxed")
        perms = sandbox.get_permissions("sandboxed")
        assert Permission.READ_MEMORY in perms
        assert Permission.ACCESS_NETWORK in perms


# ---------------------------------------------------------------------------
# PluginManagerTool tests
# ---------------------------------------------------------------------------


class TestPluginManagerTool:
    """Tests for the PluginManagerTool."""

    def _make_tool(self, plugin_registry):
        from tools.builtin.plugin_manager_tool import PluginManagerTool
        return PluginManagerTool(plugin_registry)

    def test_name_and_description(self, plugin_registry):
        tool = self._make_tool(plugin_registry)
        assert tool.name == "plugin_manager"
        assert "plugin" in tool.description.lower()

    def test_list_empty(self, plugin_registry):
        tool = self._make_tool(plugin_registry)
        result = tool.run(ToolRequest(tool_name="plugin_manager", input_data={}))
        assert result.success is True
        assert "No plugins installed" in result.output

    def test_list_with_plugins(self, plugin_registry):
        manifest = PluginManifest.from_dict(
            _make_manifest(name="weather", permissions=["access_network"])
        )
        plugin_registry.register(manifest)
        tool = self._make_tool(plugin_registry)
        result = tool.run(ToolRequest(tool_name="plugin_manager", input_data={}))
        assert result.success is True
        assert "weather" in result.output
        assert "enabled" in result.output

    def test_info_plugin(self, plugin_registry):
        manifest = PluginManifest.from_dict(
            _make_manifest(name="weather", permissions=["access_network"])
        )
        plugin_registry.register(manifest)
        tool = self._make_tool(plugin_registry)
        result = tool.run(ToolRequest(
            tool_name="plugin_manager",
            input_data={"action": "info", "plugin_id": "weather"},
        ))
        assert result.success is True
        assert "weather" in result.output
        assert "1.0.0" in result.output

    def test_info_missing_plugin_id(self, plugin_registry):
        tool = self._make_tool(plugin_registry)
        result = tool.run(ToolRequest(
            tool_name="plugin_manager",
            input_data={"action": "info"},
        ))
        assert result.success is False
        assert "plugin_id" in result.error

    def test_info_nonexistent_plugin(self, plugin_registry):
        tool = self._make_tool(plugin_registry)
        result = tool.run(ToolRequest(
            tool_name="plugin_manager",
            input_data={"action": "info", "plugin_id": "nope"},
        ))
        assert result.success is False
        assert "not found" in result.error

    def test_enable_plugin(self, plugin_registry):
        manifest = PluginManifest.from_dict(_make_manifest(name="weather"))
        plugin_registry.register(manifest)
        plugin_registry.disable("weather")
        tool = self._make_tool(plugin_registry)
        result = tool.run(ToolRequest(
            tool_name="plugin_manager",
            input_data={"action": "enable", "plugin_id": "weather"},
        ))
        assert result.success is True
        assert "enabled" in result.output
        assert plugin_registry.get_plugin("weather").enabled is True

    def test_disable_plugin(self, plugin_registry):
        manifest = PluginManifest.from_dict(_make_manifest(name="weather"))
        plugin_registry.register(manifest)
        tool = self._make_tool(plugin_registry)
        result = tool.run(ToolRequest(
            tool_name="plugin_manager",
            input_data={"action": "disable", "plugin_id": "weather"},
        ))
        assert result.success is True
        assert "disabled" in result.output
        assert plugin_registry.get_plugin("weather").enabled is False

    def test_unknown_action(self, plugin_registry):
        tool = self._make_tool(plugin_registry)
        result = tool.run(ToolRequest(
            tool_name="plugin_manager",
            input_data={"action": "bogus"},
        ))
        assert result.success is False
        assert "Unknown action" in result.error


# ---------------------------------------------------------------------------
# Integration: full load + register flow
# ---------------------------------------------------------------------------


class TestPluginIntegration:
    """Integration tests for the full plugin load + register flow."""

    def test_full_flow(self, tmp_plugins_dir, tmp_path, plugin_registry):
        """Discover, load, register, and query a plugin end-to-end."""
        _install_plugin(tmp_path, name="demo", permissions=["read_memory"])
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_plugins_dir, sandbox)
        loaded = loader.load_all()

        assert len(loaded) == 1
        # Register in the registry.
        plugin_registry.register(loaded[0].manifest)
        entry = plugin_registry.get_plugin("demo")
        assert entry is not None
        assert entry.enabled is True

        # Check sandbox permissions.
        assert sandbox.has_permission("demo", "read_memory") is True
        assert sandbox.has_permission("demo", "call_ai") is False

        # The loaded tool can run.
        tool = loaded[0].tools[0]
        result = tool.run(ToolRequest(tool_name=tool.name, input_data={}))
        assert result.success is True

    def test_multiple_plugins(self, tmp_plugins_dir, tmp_path, plugin_registry):
        """Multiple plugins can be loaded and registered."""
        _install_plugin(tmp_path, name="alpha", permissions=["read_memory"])
        _install_plugin(tmp_path, name="beta", permissions=["access_network"])
        sandbox = PluginSandbox()
        loader = PluginLoader(tmp_plugins_dir, sandbox)
        loaded = loader.load_all()

        assert len(loaded) == 2
        for plugin in loaded:
            plugin_registry.register(plugin.manifest)

        plugins = plugin_registry.list_plugins()
        assert len(plugins) == 2
        names = {p.name for p in plugins}
        assert names == {"alpha", "beta"}
