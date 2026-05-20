"""Shared logging setup for the forge and golem subprocesses.

Each process (uvicorn server, runner subprocess) calls `configure_logging()`
once at startup. Module code uses `logger = logging.getLogger(__name__)`.
"""
import logging
import os
import sys


_DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
_DEFAULT_DATEFMT = "%H:%M:%S"


def configure_logging() -> None:
    """Idempotent root-logger setup.

    Level is read from `GOLEM_LOG_LEVEL` (default INFO).
    Output goes to stderr so it lands in the forge's terminal alongside
    uvicorn's own logs.
    """
    root = logging.getLogger()
    if any(getattr(h, "_golem_configured", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT, _DEFAULT_DATEFMT))
    handler._golem_configured = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(os.getenv("GOLEM_LOG_LEVEL", "INFO").upper())
    # Quieten noisy libraries.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
