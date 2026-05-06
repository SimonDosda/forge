from pathlib import Path


def read_env(path: str | Path) -> dict[str, str]:
    """Parse a .env file into a dict. Missing files yield {}."""
    file = Path(path)
    if not file.exists():
        return {}
    out: dict[str, str] = {}
    for raw in file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = _unquote(value.split("#", 1)[0].strip())
    return out


def write_env(path: str | Path, values: dict[str, str]) -> None:
    """Update keys in-place, preserving comments and ordering. Unknown keys are appended."""
    file = Path(path)
    existing_lines = file.read_text().splitlines() if file.exists() else []
    remaining = dict(values)
    new_lines: list[str] = []
    for raw in existing_lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(raw)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}")
        else:
            new_lines.append(raw)
    for key, value in remaining.items():
        new_lines.append(f"{key}={value}")
    file.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value
