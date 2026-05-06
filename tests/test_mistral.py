import json
from dataclasses import dataclass, field
from types import SimpleNamespace

from advisor.mistral import MistralAdvisor
from models import ActionType
from skills.skill import SkillAction


@dataclass
class _ScriptedChat:
    """Returns one queued response per `complete()` call. Records every call."""

    responses: list = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _final_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))]
    )


def _tool_call_response(name: str, arguments: dict, call_id: str = "call_1"):
    tool_call = SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="", tool_calls=[tool_call])
            )
        ]
    )


def _client(*responses):
    chat = _ScriptedChat(responses=list(responses))
    return SimpleNamespace(chat=chat), chat


@dataclass
class _RecordingSkill:
    name: str = "open_meteo"
    description: str = "Weather"
    actions: list[SkillAction] = field(default_factory=list)


def _make_weather_skill(handler):
    skill = _RecordingSkill()
    skill.actions = [
        SkillAction(
            name="get_forecast",
            description="Get forecast",
            parameters={
                "type": "object",
                "properties": {
                    "latitude": {"type": "number"},
                    "longitude": {"type": "number"},
                },
                "required": ["latitude", "longitude"],
            },
            handler=handler,
        )
    ]
    return skill


def test_briefing_parses_final_json_when_no_tools_called():
    client, _ = _client(
        _final_response(
            json.dumps({"weather_summary": "21C clear", "tasks": ["Water tomatoes"]})
        )
    )
    advisor = MistralAdvisor("k", client=client)

    briefing = advisor.briefing(
        skills=[],
        history=[],
        plants=["tomatoes"],
        location={"latitude": 48.85, "longitude": 2.35},
    )

    assert briefing.weather_summary == "21C clear"
    assert briefing.tasks == ("Water tomatoes",)


def test_briefing_handles_malformed_json_in_final_response():
    client, _ = _client(_final_response("not json at all"))
    advisor = MistralAdvisor("k", client=client)

    briefing = advisor.briefing(
        skills=[], history=[], plants=[], location={"latitude": 0, "longitude": 0}
    )

    assert briefing.weather_summary == ""
    assert briefing.tasks == ()


def test_briefing_invokes_skill_handler_when_model_calls_tool():
    handler_calls: list[dict] = []

    def handler(latitude, longitude):
        handler_calls.append({"latitude": latitude, "longitude": longitude})
        return {"temp_c": 21.0, "condition": "clear"}

    skill = _make_weather_skill(handler)
    client, chat = _client(
        _tool_call_response(
            "open_meteo__get_forecast", {"latitude": 48.85, "longitude": 2.35}
        ),
        _final_response(
            json.dumps({"weather_summary": "21C clear", "tasks": ["Water tomatoes"]})
        ),
    )
    advisor = MistralAdvisor("k", client=client)

    briefing = advisor.briefing(
        skills=[skill],
        history=[],
        plants=[],
        location={"latitude": 48.85, "longitude": 2.35},
    )

    # Tool was actually invoked with the model's arguments
    assert handler_calls == [{"latitude": 48.85, "longitude": 2.35}]
    # Briefing parsed from the second (final) response
    assert briefing.tasks == ("Water tomatoes",)

    # First request advertised the skill as a tool with qualified name
    first_call_tools = chat.calls[0]["tools"]
    assert first_call_tools[0]["function"]["name"] == "open_meteo__get_forecast"
    # Second request had a tool result message
    second_call_messages = chat.calls[1]["messages"]
    tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["name"] == "open_meteo__get_forecast"


def test_briefing_with_no_skills_passes_no_tools():
    client, chat = _client(_final_response(json.dumps({"weather_summary": "", "tasks": []})))
    advisor = MistralAdvisor("k", client=client)

    advisor.briefing(skills=[], history=[], plants=[], location={"latitude": 0, "longitude": 0})

    assert chat.calls[0]["tools"] is None


def test_parse_message_returns_garden_actions():
    payload = {
        "actions": [
            {"name": "Watered tomatoes", "type": "watering", "plants": ["tomatoes"], "notes": ""},
            {"name": "Planted basil", "type": "planting", "plants": ["basil"]},
        ]
    }
    client, _ = _client(_final_response(json.dumps(payload)))
    advisor = MistralAdvisor("k", client=client)

    actions = advisor.parse_message("I watered tomatoes and planted basil")

    assert len(actions) == 2
    assert actions[0].type == ActionType.WATERING
    assert actions[0].plants == ("tomatoes",)
    assert actions[1].type == ActionType.PLANTING


def test_parse_message_unknown_type_falls_back_to_other():
    client, _ = _client(
        _final_response(json.dumps({"actions": [{"name": "Weeded", "type": "weeding"}]}))
    )
    advisor = MistralAdvisor("k", client=client)

    assert advisor.parse_message("...")[0].type == ActionType.OTHER


def test_parse_message_empty_when_no_actions():
    client, _ = _client(_final_response(json.dumps({"actions": []})))
    advisor = MistralAdvisor("k", client=client)

    assert advisor.parse_message("hello") == []
