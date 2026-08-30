"""
plugin.py

Example weather plugin for the Jarvis plugin system.

Registers a weather_check tool that queries a weather API
and optionally saves results to memory.

This is a demonstration plugin showing how the plugin architecture works.
The actual weather API call is simulated for safety.
"""

from __future__ import annotations

from typing import Any

from tools.base_tool import BaseTool, ToolRequest, ToolResult


class WeatherCheckTool(BaseTool):
    """A GREEN tool that checks weather for a given location.

    Simulates a weather API call for demonstration purposes.
    In a real implementation, this would call an actual weather API.
    """

    @property
    def name(self) -> str:
        return "weather_check"

    @property
    def description(self) -> str:
        return "Check current weather conditions for a location. Read-only and safe."

    def run(self, request: ToolRequest) -> ToolResult:
        """Handle a weather check request.

        Args:
            request: The request with input_data containing:
                - location (str): The location to check weather for.

        Returns:
            A ToolResult with simulated weather data.
        """
        location = str(request.input_data.get("location", "")).strip()
        if not location:
            return self.fail("No location provided. Usage: location='London'")

        # Simulated weather response (no real API call).
        weather_data = {
            "location": location,
            "condition": "Partly Cloudy",
            "temperature_c": 18,
            "humidity_pct": 65,
            "wind_kph": 12,
            "note": "Simulated data (weather API not connected)",
        }

        lines = [f"Weather for {location}:"]
        lines.append(f"  Condition: {weather_data['condition']}")
        lines.append(f"  Temperature: {weather_data['temperature_c']}°C")
        lines.append(f"  Humidity: {weather_data['humidity_pct']}%")
        lines.append(f"  Wind: {weather_data['wind_kph']} km/h")
        lines.append(f"  Note: {weather_data['note']}")

        return self.ok("\n".join(lines))


def register(context: Any = None) -> list[BaseTool]:
    """Register the weather plugin's tools.

    This function is called by the plugin loader when the plugin
    is loaded on startup.

    Args:
        context: PluginContext (unused by this simple plugin).

    Returns:
        A list of tools this plugin provides.
    """
    return [WeatherCheckTool()]
