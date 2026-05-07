from dataclasses import dataclass
from typing import Protocol

from golem.core import BrainResponse, Message, ToolSpec


@dataclass(frozen=True)
class BrainConfig:
    provider: str           # "mistral" | "anthropic" | "openai" | "ollama"
    model: str
    api_key: str = ""       # not required for ollama
    base_url: str = ""      # optional override (ollama, custom endpoints)


class Brain(Protocol):
    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] = (),
    ) -> BrainResponse: ...


def build_brain(config: BrainConfig) -> Brain:
    """Factory: pick the provider implementation from config."""
    provider = config.provider.lower()
    if provider == "mistral":
        from golem.brain.mistral import MistralBrain
        return MistralBrain(config)
    if provider == "anthropic":
        from golem.brain.anthropic import AnthropicBrain
        return AnthropicBrain(config)
    if provider == "openai":
        from golem.brain.openai import OpenAIBrain
        return OpenAIBrain(config)
    if provider == "ollama":
        from golem.brain.ollama import OllamaBrain
        return OllamaBrain(config)
    raise ValueError(f"unknown brain provider: {config.provider}")
