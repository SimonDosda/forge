from typing import Any

import requests

from core import ToolSpec


_API_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather code → human-friendly condition (subset).
_WMO_CONDITIONS: dict[int, str] = {
    0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow",
    80: "rain showers", 81: "rain showers", 82: "violent rain showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


class OpenMeteo:
    name = "open_meteo"

    def __init__(self, http: requests.Session | None = None, timeout_s: float = 10.0):
        self._http = http or requests.Session()
        self._timeout = timeout_s

    @property
    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="get_forecast",
                description=(
                    "Today's temperature (°C), sky condition, total rain expected over "
                    "the next 3 days (mm), and today's UV index for the given coordinates."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "latitude": {"type": "number", "description": "Latitude in degrees."},
                        "longitude": {"type": "number", "description": "Longitude in degrees."},
                    },
                    "required": ["latitude", "longitude"],
                },
            ),
        ]

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name != "get_forecast":
            raise ValueError(f"unknown tool: {name}")
        return self._get_forecast(arguments["latitude"], arguments["longitude"])

    def _get_forecast(self, latitude: float, longitude: float) -> dict[str, Any]:
        response = self._http.get(
            _API_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current_weather": "true",
                "daily": "precipitation_sum,uv_index_max",
                "forecast_days": 3,
                "timezone": "auto",
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        current = payload["current_weather"]
        daily = payload["daily"]
        code = int(current.get("weathercode", -1))
        return {
            "temp_c": float(current["temperature"]),
            "condition": _WMO_CONDITIONS.get(code, "unknown"),
            "rain_mm_next_3d": sum(float(x or 0) for x in daily.get("precipitation_sum", [])),
            "uv_index_today": float((daily.get("uv_index_max") or [0])[0] or 0),
        }
