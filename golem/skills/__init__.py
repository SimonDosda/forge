"""Skill registry — every Skill class the project knows how to instantiate.

Each registered entry is a name + builder that takes the per-golem Memory and
returns a Skill. The forge stores a `skills: list[str]` allowlist per golem;
each Golem consults this registry on awake to instantiate its enabled skills.
"""
from typing import Callable

from golem.memory.memory import Memory
from golem.skills.memory_skill import MemorySkill
from golem.skills.notion import NotionSkill
from golem.skills.open_meteo import OpenMeteo
from golem.skills.skill import Skill


SkillBuilder = Callable[[Memory], Skill]

REGISTRY: dict[str, SkillBuilder] = {
    "memory": lambda mem: MemorySkill(mem),
    "notion": lambda _mem: NotionSkill(),
    "open_meteo": lambda _mem: OpenMeteo(),
}


def available_skill_names() -> list[str]:
    return sorted(REGISTRY.keys())


def build_skills(memory: Memory, names: list[str]) -> list[Skill]:
    out: list[Skill] = []
    for n in names:
        builder = REGISTRY.get(n)
        if builder is None:
            continue
        out.append(builder(memory))
    return out


def describe_skills(memory: Memory) -> list[dict]:
    """Render every registered skill with its tools — read-only metadata for the UI."""
    out: list[dict] = []
    for name in available_skill_names():
        skill = REGISTRY[name](memory)
        out.append({
            "name": skill.name,
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
