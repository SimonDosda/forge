# Golem

Modular personal assistant skeleton. Five small components, swappable backends. Personality is configuration — point it at any domain via `data/spirit.json`.

```
┌─────────┐     ┌──────────┐
│  Voice  │ ←→ │   Body   │
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
- **View** — Browser-based config UI. Read/write `.env`, edit Spirit (prompt + schedules), browse and edit Memory entries.

## Layout

```
core.py             # shared dataclasses (Message, ToolCall, ToolSpec, ...)
config.py           # .env → Settings
body.py             # the loop: history → brain → tools → reply
awake.py            # entry point — wakes the body up
brain/              # protocol + mistral / anthropic / openai / ollama
memory/             # protocol + json_store
skills/             # protocol + memory_skill + open_meteo
spirit/             # protocol + JSON-backed config
voice/              # protocol + telegram
view/               # browser config UI (FastAPI + static HTML)
data/               # runtime state (gitignored)
```

## Setup

```bash
uv sync
cp .env.example .env   # then edit
uv run python awake.py          # run the bot
uv run python -m view.server    # config UI on http://127.0.0.1:8765
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

Register it in `awake.py` alongside `MemorySkill` and `OpenMeteo`.

## Adding a new brain provider

Create `brain/<provider>.py` exposing a class with `chat(messages, tools) → BrainResponse`, then add a branch in `brain.brain.build_brain`.

## Adding a new voice

Implement `voice.voice.Voice` (`send`, `run`, `stop`). Swap the constructor in `awake.py`.
