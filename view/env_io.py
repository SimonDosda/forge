"""Read/write .env preserving comments and unrelated keys."""
from pathlib import Path


def read(path: str | Path) -> dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        out[key.strip()] = _strip_quotes(value.strip())
    return out


def write(path: str | Path, updates: dict[str, str]) -> None:
    """Update keys in-place; append unknown keys at the end. Preserves comments."""
    p = Path(path)
    existing_lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []

    seen: set[str] = set()
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, _, _rest = stripped.partition("=")
            key = key.strip()
            if key in updates:
                new_lines.append(f"{key}={_format(updates[key])}")
                seen.add(key)
                continue
        new_lines.append(line)

    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={_format(value)}")

    p.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _format(value: str) -> str:
    # Quote if value has spaces or characters that would confuse simple parsers.
    if any(c in value for c in (" ", "#", "$")):
        return f'"{value}"'
    return value
