import requests

from models import Forecast
from skills.skill import SkillAction


_API_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather code → human-friendly condition (subset).
_WMO_CONDITIONS: dict[int, str] = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "freezing fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    80: "rain showers",
    81: "rain showers",
    82: "violent rain showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with heavy hail",
}


class OpenMeteo:
    name = "open_meteo"
    description = (
        "Weather forecasts via Open-Meteo (free, no API key). "
        "Use to learn current temperature, sky condition, rain forecast, and UV index."
    )

    def __init__(self, http: requests.Session | None = None, timeout_s: float = 10.0):
        self._http = http or requests.Session()
        self._timeout = timeout_s
        self.actions: list[SkillAction] = [
            SkillAction(
                name="get_forecast",
                description=(
                    "Return today's temperature, sky condition, rain expected over "
                    "the next 3 days (mm), and today's UV index for the given coordinates."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "latitude": {"type": "number", "description": "Latitude in degrees."},
                        "longitude": {"type": "number", "description": "Longitude in degrees."},
                    },
                    "required": ["latitude", "longitude"],
                },
                handler=self.get_forecast,
            ),
        ]

    def get_forecast(self, latitude: float, longitude: float) -> Forecast:
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
        return _parse(response.json())


def _parse(payload: dict) -> Forecast:
    current = payload["current_weather"]
    daily = payload["daily"]

    code = int(current.get("weathercode", -1))
    condition = _WMO_CONDITIONS.get(code, "unknown")

    rain_3d = sum(float(x or 0) for x in daily.get("precipitation_sum", []))
    uv_today = float((daily.get("uv_index_max") or [0])[0] or 0)

    return Forecast(
        temp_c=float(current["temperature"]),
        condition=condition,
        rain_mm_next_3d=rain_3d,
        uv_index=uv_today,
    )
