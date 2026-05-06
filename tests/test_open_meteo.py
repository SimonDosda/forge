from dataclasses import dataclass

from skills.open_meteo import OpenMeteo


@dataclass
class _StubResponse:
    payload: dict
    status_code: int = 200

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class _StubSession:
    def __init__(self, payload: dict):
        self.payload = payload
        self.last_params: dict | None = None

    def get(self, url, params=None, timeout=None):
        self.last_params = params
        return _StubResponse(self.payload)


_SAMPLE = {
    "current_weather": {"temperature": 21.5, "weathercode": 0},
    "daily": {
        "precipitation_sum": [0.0, 1.2, 0.5],
        "uv_index_max": [6.3, 5.0, 4.1],
    },
}


def test_skill_exposes_name_description_and_actions():
    skill = OpenMeteo(http=_StubSession(_SAMPLE))

    assert skill.name == "open_meteo"
    assert skill.description
    assert len(skill.actions) == 1
    action = skill.actions[0]
    assert action.name == "get_forecast"
    assert action.description
    assert action.parameters["required"] == ["latitude", "longitude"]
    assert "latitude" in action.parameters["properties"]


def test_action_handler_invokes_underlying_get_forecast():
    skill = OpenMeteo(http=_StubSession(_SAMPLE))
    handler = skill.actions[0].handler

    forecast = handler(latitude=48.85, longitude=2.35)

    assert forecast.temp_c == 21.5
    assert forecast.condition == "clear"


def test_get_forecast_maps_payload_to_domain():
    session = _StubSession(_SAMPLE)
    skill = OpenMeteo(http=session)

    forecast = skill.get_forecast(48.85, 2.35)

    assert forecast.temp_c == 21.5
    assert forecast.condition == "clear"
    assert forecast.rain_mm_next_3d == 1.7
    assert forecast.uv_index == 6.3


def test_get_forecast_passes_lat_lon_to_session():
    session = _StubSession(_SAMPLE)
    skill = OpenMeteo(http=session)

    skill.get_forecast(48.85, 2.35)

    assert session.last_params["latitude"] == 48.85
    assert session.last_params["longitude"] == 2.35


def test_unknown_weathercode_falls_back_to_unknown():
    payload = {
        "current_weather": {"temperature": 10.0, "weathercode": 999},
        "daily": {"precipitation_sum": [0], "uv_index_max": [0]},
    }
    skill = OpenMeteo(http=_StubSession(payload))

    assert skill.get_forecast(0, 0).condition == "unknown"
