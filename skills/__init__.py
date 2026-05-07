from skills.skill import Skill
from skills.memory_skill import MemorySkill
from skills.open_meteo import OpenMeteo
from memory.memory import Memory

__all__ = ["Skill", "MemorySkill", "OpenMeteo", "default_skills"]


def default_skills(memory: Memory) -> list[Skill]:
    """Single source of truth for the skill set used by the running bot and the view."""
    return [MemorySkill(memory), OpenMeteo()]
