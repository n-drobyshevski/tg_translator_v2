"""Atomic, secret-preserving upsert of single keys in the root ``.env``.

The bot lets an admin change a handful of operational settings (model, prompt,
channel pairs) live from a Telegram DM. To make those changes survive a restart
they must be written back to the shared ``.env`` that both the bot and the Flask
admin app read at startup.

``.env`` holds **real secrets**. So this module is deliberately surgical: it
rewrites only the one target line, preserving every other line — comments,
blanks, ordering, and secret values — byte-for-byte, and writes atomically
(temp file on the same volume + ``os.replace``) so a crash mid-write can never
truncate the file. ``dotenv.set_key`` was rejected because it reorders and
re-quotes the whole file.

Both helpers also mutate ``os.environ`` so the running process matches the file
immediately (``CONFIG.reload()`` then re-reads ``os.environ``).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

try:
    from dotenv import find_dotenv
except ImportError:  # pragma: no cover - dotenv is a hard dep, but stay safe
    def find_dotenv(*_a, **_k):  # type: ignore
        return ""


def _root_env_path() -> Path:
    """Locate the project-root ``.env`` (the one ``config.load_dotenv`` reads)."""
    found = find_dotenv(usecwd=True)
    if found:
        return Path(found)
    # Fallback: repo root is two levels up from this file
    # (translator/services/env_store.py -> repo root).
    return Path(__file__).resolve().parents[2] / ".env"


def _key_of(line: str) -> str | None:
    """Return the env key a line defines, or None for blanks/comments.

    Handles an optional leading ``export `` (some .env files use it).
    """
    s = line.lstrip()
    if not s or s.startswith("#") or "=" not in s:
        return None
    if s.startswith("export "):
        s = s[len("export "):]
    return s.split("=", 1)[0].strip() or None


def _format_value(value: str) -> str:
    """Quote a value only when it needs it; escape what double-quotes require."""
    if value == "" or any(c in value for c in ' \t#"\'\n\r'):
        esc = value.replace("\\", "\\\\").replace('"', '\\"')
        esc = esc.replace("\n", "\\n").replace("\r", "\\r")
        return f'"{esc}"'
    return value


def _atomic_write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically via a same-dir temp file."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        os.replace(tmp, path)  # atomic on the same filesystem (incl. Windows)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def set_env_var(key: str, value: str) -> Path:
    """Set ``key=value`` in the root ``.env`` and in ``os.environ``.

    Replaces the first existing definition in place (dropping any later
    duplicate definitions of the same key) or appends at EOF. Returns the .env
    path that was written.
    """
    path = _root_env_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = (
        path.read_text(encoding="utf-8").splitlines(keepends=True)
        if path.exists()
        else []
    )
    newline = f"{key}={_format_value(value)}\n"
    out: list[str] = []
    replaced = False
    for ln in lines:
        if _key_of(ln) == key:
            if not replaced:
                out.append(newline)
                replaced = True
            # else: drop later duplicate definitions
        else:
            out.append(ln)
    if not replaced:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.append(newline)
    _atomic_write(path, "".join(out))
    os.environ[key] = value
    return path


def unset_env_var(key: str) -> Path:
    """Remove every definition of ``key`` from the root ``.env`` and os.environ."""
    path = _root_env_path()
    if path.exists():
        kept = [
            ln
            for ln in path.read_text(encoding="utf-8").splitlines(keepends=True)
            if _key_of(ln) != key
        ]
        _atomic_write(path, "".join(kept))
    os.environ.pop(key, None)
    return path
