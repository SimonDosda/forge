# Garden Bot

Modular personal assistant. Five small components, swappable backends.

```
┌─────────┐     ┌──────────┐
│  Voice  │ ←→ │ Orchestr.│
└─────────┘     └────┬─────┘
                     │
   ┌──────┬──────────┼──────────┬──────┐
   ▼      ▼          ▼          ▼      ▼
 Brain  Memory     Skills    Spirit
(LLM)  (JSON)   (MCP-shaped) (prompt
                              + cron)
```

## Components

- **Brain** — AI connector. Configurable provider (Mistral, Anthropic, OpenAI, Ollama) and model. Interface: `chat(messages, tools) → response`.
- **Memory** — Pluggable storage; default `JsonMemory` keeps one JSON file per *topic* under `data/memory/`. Operations: `get / add / update / delete`.
- **Skills** — MCP-shaped capabilities. Each skill exposes `tools: list[ToolSpec]` and a `call(name, arguments)` handler. Memory itself is wrapped as a skill so the Brain can read/write it.
- **Spirit** — Static instructions (system prompt) and scheduled actions, persisted to `data/spirit.json`. Editable at runtime.
- **Voice** — I/O channel. `TelegramVoice` for now; the protocol covers any push/pull transport (email, WhatsApp, ...).

## Layout

```
core.py             # shared dataclasses (Message, ToolCall, ToolSpec, ...)
config.py           # .env → Settings
orchestrator.py     # the loop: history → brain → tools → reply
main.py             # entry point
brain/              # protocol + mistral / anthropic / openai / ollama
memory/             # protocol + json_store
skills/             # protocol + memory_skill + open_meteo
spirit/             # protocol + JSON-backed config
voice/              # protocol + telegram
data/               # runtime state (gitignored)
```

## Setup

```bash
uv sync
cp .env.example .env   # then edit
uv run python main.py
```

## Adding a new skill

```python
class MySkill:
    name = "my_skill"
    @property
    def tools(self) -> list[ToolSpec]:
        return [ToolSpec(name="do_thing", description="...", input_schema={...})]
    def call(self, name, arguments):
        if name == "do_thing":
            return ...
```

Register it in `main.py` alongside `MemorySkill` and `OpenMeteo`.

## Adding a new brain provider

Create `brain/<provider>.py` exposing a class with `chat(messages, tools) → BrainResponse`, then add a branch in `brain.brain.build_brain`.

## Adding a new voice

Implement `voice.voice.Voice` (`send`, `run`, `stop`). Swap the constructor in `main.py`.
