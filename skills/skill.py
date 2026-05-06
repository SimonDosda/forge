from dataclasses import dataclass
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class SkillAction:
    """One callable capability exposed by a skill (analogous to an MCP tool)."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema describing handler args
    handler: Callable[..., Any]


class Skill(Protocol):
    name: str
    description: str
    actions: list[SkillAction]
