from typing import Any, Protocol

from core import ToolSpec


class Skill(Protocol):
    """MCP-shaped capability: declares tools and handles calls."""
    name: str

    @property
    def tools(self) -> list[ToolSpec]: ...

    def call(self, name: str, arguments: dict[str, Any]) -> Any: ...
