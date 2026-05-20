from typing import Any, Protocol

from golem.core import ToolSpec


class Skill(Protocol):
    """MCP-shaped capability: declares tools and handles calls.

    `config_schema` declares per-golem configuration fields the forge UI
    should render — each entry is `{"key", "label", "secret"?, "description"?}`.
    Empty for skills with no per-golem config.
    """
    name: str
    config_schema: list[dict[str, Any]]

    @property
    def tools(self) -> list[ToolSpec]: ...

    def call(self, name: str, arguments: dict[str, Any]) -> Any: ...
