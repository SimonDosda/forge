"""Shared dataclasses used across Brain, Skills, Spirit, Voice, and the orchestrator."""
from dataclasses import dataclass, field
from typing import Any, Literal


Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    """MCP-shaped tool description: name, prose, JSON Schema for arguments."""
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class BrainResponse:
    content: str
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)
