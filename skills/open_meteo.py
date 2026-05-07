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
                    "Weather forecast for the given coordinates. Returns current "
                    "conditions plus a daily forecast for the next N days (1-16, "
                    "default 14): min/max temperature in °C, dominant sky condition "
                    "(clear, partly cloudy, rain, snow, ...), total precipitation in "
                    "mm, max precipitation probability in percent, and max UV index."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "latitude": {"type": "number", "description": "Latitude in degrees."},
                        "longitude": {"type": "number", "description": "Longitude in degrees."},
                        "days": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 16,
                            "default": 14,
                            "description": "How many days of daily forecast to return (1-16). Defaults to 14.",
                        },
                    },
                    "required": ["latitude", "longitude"],
                },
            ),
        ]

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name != "get_forecast":
            raise ValueError(f"unknown tool: {name}")
        return self._get_forecast(
            arguments["latitude"],
            arguments["longitude"],
            int(arguments.get("days", 14)),
        )

    def _get_forecast(self, latitude: float, longitude: float, days: int = 14) -> dict[str, Any]:
        days = max(1, min(16, days))
        response = self._http.get(
            _API_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current_weather": "true",
                "daily": ",".join([
                    "weathercode",
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "precipitation_sum",
                    "precipitation_probability_max",
                    "uv_index_max",
                ]),
                "forecast_days": days,
                "timezone": "auto",
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        current = payload.get("current_weather") or {}
        daily = payload.get("daily") or {}
        times = daily.get("time") or []

        return {
            "current": {
                "temp_c": float(current.get("temperature", 0) or 0),
                "condition": _WMO_CONDITIONS.get(
                    int(current.get("weathercode", -1) or -1), "unknown"
                ),
            },
            "daily": [
                {
                    "date": times[i],
                    "temp_min_c": _f(daily.get("temperature_2m_min"), i),
                    "temp_max_c": _f(daily.get("temperature_2m_max"), i),
                    "condition": _WMO_CONDITIONS.get(
                        int((daily.get("weathercode") or [-1])[i] or -1), "unknown"
                    ),
                    "precipitation_mm": _f(daily.get("precipitation_sum"), i),
                    "precipitation_probability_pct": _i(daily.get("precipitation_probability_max"), i),
                    "uv_index_max": _f(daily.get("uv_index_max"), i),
                }
                for i in range(len(times))
            ],
        }


def _f(values: list | None, i: int) -> float:
    if not values or i >= len(values):
        return 0.0
    return float(values[i] or 0)


def _i(values: list | None, i: int) -> int:
    if not values or i >= len(values):
        return 0
    return int(values[i] or 0)
