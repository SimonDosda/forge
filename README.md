# Golem

Forge as many golems as you want. Each one is a self-contained personal assistant with its own brain, memory, spirit, dialog, and skill set. The forge is both the configurator and the supervisor — running golems live inside the same process; you wake/sleep/reshape them from the UI.

```
                   ┌──────────────────────┐
                   │        Forge         │   data/forge.json (registry)
                   │  UI + Supervisor     │
                   └──────────┬───────────┘
                              │ defines + runs
                              ▼
                   ┌──────────────────────┐
                   │       Golem N        │  ← one per row in forge.json
                   │  ┌─────────┐         │
                   │  │ Dialog  │ ←→ Body │
                   │  └─────────┘         │
                   │   Brain · Memory ·   │  data/<name>/memory.json
                   │   Spirit · Skills    │
                   └──────────────────────┘
```

## Lifecycle

A golem has three operations:

- **`awake`** — start running. Builds the brain client, opens the dialog channel, registers schedules.
- **`sleep`** — stop running. Tears down everything.
- **`reshape`** — re-read the current spec from the forge and rebuild. Triggered automatically when you save changes to a running golem; can also be invoked explicitly via the API.

The `enabled` flag on a golem means "autowake when the forge starts".

## Layout

```
cli.py
golem/                   # everything one golem is made of
  golem.py               # class Golem with awake/sleep/reshape
  core.py                # shared dataclasses (Message, ToolCall, ToolSpec, ...)
  brain/                 # provider implementations (mistral / anthropic / openai / ollama)
  memory/                # protocol + tinydb_store
  skills/                # registry + memory_skill + open_meteo
  spirit/                # Schedule + Spirit view backed by forge store
  dialog/                # protocol + telegram
forge/                   # multi-golem registry, supervisor, and browser UI
  store.py               # GolemSpec + TinyDB CRUD
  supervisor.py          # name → running Golem, shared scheduler
  server.py              # FastAPI app
  migration.py           # legacy single-bot migration
data/                    # runtime state (gitignored)
  forge.json             # registry
  <name>/memory.json
```

## Setup

```bash
uv sync
uv run golem forge     # http://127.0.0.1:8765 — forge UI + supervisor
```

The forge auto-migrates a legacy single-bot setup (`.env` + `data/spirit.json` + `data/memory.json`) into a `default` golem on first launch.

## Adding a new skill

```python
# golem/skills/my_skill.py
class MySkill:
    name = "my_skill"
    @property
    def tools(self) -> list[ToolSpec]:
        return [ToolSpec(name="do_thing", description="...", input_schema={...})]
    def call(self, name, arguments):
        if name == "do_thing":
            return ...
```

Register it in `golem/skills/__init__.py`:

```python
REGISTRY["my_skill"] = lambda mem: MySkill()
```

It then shows up in the forge as a checkbox each golem can opt into.

## Adding a new brain provider

Create `golem/brain/<provider>.py` exposing a class with `chat(messages, tools) → BrainResponse`, then add a branch in `golem.brain.brain.build_brain`.

## Adding a new dialog

Implement `golem.dialog.dialog.Dialog` (`send`, `run`, `stop`). Extend `Golem._build_dialog` and the dialog tab in the forge UI to expose the new transport.

## Running as a service

A systemd template lives in `golem.service`. Replace `__USER__` and `__PATH__` and install it; it runs `golem forge` under the project's venv.
