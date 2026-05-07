from typing import Any

from golem.core import ToolSpec
from golem.memory.memory import Entry, Memory


class MemorySkill:
    """Exposes Memory CRUD as MCP-shaped tools so the Brain can read/write."""

    name = "memory"

    def __init__(self, memory: Memory):
        self._memory = memory

    @property
    def tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="memory_get",
                description=(
                    "Read entries from a memory topic. Returns all entries for the topic, "
                    "or a single entry if entry_id is provided. Topics are user-defined "
                    "categories (e.g. 'tasks', 'journal', 'preferences')."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "Topic name."},
                        "entry_id": {
                            "type": "string",
                            "description": "Optional entry id to fetch a single entry.",
                        },
                    },
                    "required": ["topic"],
                },
            ),
            ToolSpec(
                name="memory_add",
                description="Append a new entry to a topic. Returns the created entry id.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "entry": {"type": "object", "description": "Arbitrary JSON payload."},
                    },
                    "required": ["topic", "entry"],
                },
            ),
            ToolSpec(
                name="memory_update",
                description="Replace the data of an existing entry by id.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "entry_id": {"type": "string"},
                        "entry": {"type": "object"},
                    },
                    "required": ["topic", "entry_id", "entry"],
                },
            ),
            ToolSpec(
                name="memory_delete",
                description="Remove an entry by id from a topic.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "entry_id": {"type": "string"},
                    },
                    "required": ["topic", "entry_id"],
                },
            ),
            ToolSpec(
                name="memory_topics",
                description="List all known topic names.",
                input_schema={"type": "object", "properties": {}},
            ),
        ]

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "memory_get":
            return [_entry_to_dict(e) for e in self._memory.get(
                arguments["topic"], arguments.get("entry_id"),
            )]
        if name == "memory_add":
            return _entry_to_dict(self._memory.add(arguments["topic"], arguments["entry"]))
        if name == "memory_update":
            return _entry_to_dict(self._memory.update(
                arguments["topic"], arguments["entry_id"], arguments["entry"],
            ))
        if name == "memory_delete":
            self._memory.delete(arguments["topic"], arguments["entry_id"])
            return {"deleted": True}
        if name == "memory_topics":
            return self._memory.topics()
        raise ValueError(f"unknown tool: {name}")


def _entry_to_dict(e: Entry) -> dict[str, Any]:
    return {
        "id": e.id,
        "topic": e.topic,
        "data": e.data,
        "created_at": e.created_at,
        "updated_at": e.updated_at,
    }
