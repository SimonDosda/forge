from typing import Awaitable, Callable, Protocol


IncomingHandler = Callable[[str], Awaitable[str]]


class Dialog(Protocol):
    """Bidirectional channel: receives user messages, can push outgoing messages."""

    async def send(self, text: str) -> None: ...

    async def run(self, on_message: IncomingHandler) -> None:
        """Start receiving incoming messages and dispatch them to `on_message`.
        Each returned string is sent back as a reply."""
        ...

    async def stop(self) -> None: ...
