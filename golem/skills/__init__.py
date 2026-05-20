"""Skill registry — every Skill class the project knows how to instantiate.

Each registered entry is a name + builder that takes the per-golem Memory and
a per-golem config dict, returning a Skill. The forge stores
`skills: list[str]` (allowlist) and `skill_configs: dict[str, dict[str, str]]`
per golem; each Golem consults this registry on awake to instantiate its
enabled skills with their configured values.
"""
from typing import Any, Callable

from golem.memory.memory import Memory
from golem.skills.memory_skill import MemorySkill
from golem.skills.notion import NotionSkill
from golem.skills.open_meteo import OpenMeteo
from golem.skills.skill import Skill


SkillBuilder = Callable[[Memory, dict[str, str]], Skill]

REGISTRY: dict[str, SkillBuilder] = {
    "memory": lambda mem, _cfg: MemorySkill(mem),
    "notion": lambda _mem, cfg: NotionSkill(api_key=cfg.get("api_key", "")),
    "open_meteo": lambda _mem, _cfg: OpenMeteo(),
}


def available_skill_names() -> list[str]:
    return sorted(REGISTRY.keys())


def build_skills(
    memory: Memory,
    names: list[str],
    configs: dict[str, dict[str, str]] | None = None,
) -> list[Skill]:
    configs = configs or {}
    out: list[Skill] = []
    for n in names:
        builder = REGISTRY.get(n)
        if builder is None:
            continue
        out.append(builder(memory, configs.get(n, {})))
    return out


def describe_skills(memory: Memory) -> list[dict[str, Any]]:
    """Render every registered skill with its tools and config schema —
    read-only metadata for the UI."""
    out: list[dict[str, Any]] = []
    for name in available_skill_names():
        skill = REGISTRY[name](memory, {})
        out.append({
            "name": skill.name,
            "config_schema": list(getattr(skill, "config_schema", []) or []),
            "tools": [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in skill.tools
            ],
        })
    return out


__all__ = [
    "Skill",
    "MemorySkill",
    "NotionSkill",
    "OpenMeteo",
    "REGISTRY",
    "available_skill_names",
    "build_skills",
    "describe_skills",
]
