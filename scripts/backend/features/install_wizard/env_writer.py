"""Atomic .env writer — format-compatible with lib/env.sh:_env_set (SRP).

Behavior mirrors the bash _env_set helper:
  - If KEY= line exists, replace its value (preserving line position).
  - Otherwise append `KEY=VAL\\n` to the file.

Atomicity: write to <file>.<rand>, then os.replace() — same approach as bash awk+mv.
"""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from typing import Iterable, Mapping

logger = logging.getLogger(__name__)


def write_env(env_path: Path, updates: Mapping[str, str]) -> None:
    """Apply key→value updates to env_path atomically.

    Existing keys: replaced in place (line position preserved).
    Missing keys: appended at the end in iteration order.
    Empty-string values still write `KEY=` (use delete_keys() to remove).

    Raises OSError on filesystem failure; caller decides whether to surface.
    """
    if not env_path.exists():
        # First-time write — start from empty file
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("", encoding="utf-8")

    original = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    seen: set[str] = set()
    out_lines: list[str] = []

    for line in original:
        # Match `KEY=...` (preserve commented lines as-is)
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            out_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            seen.add(key)
            # Preserve trailing newline if original had one
            nl = "\n" if line.endswith("\n") else ""
            newline = nl if nl else "\n"
            out_lines.append(f"{key}={updates[key]}{newline}")
        else:
            out_lines.append(line)

    # Append any keys not seen
    if out_lines and not out_lines[-1].endswith("\n"):
        out_lines[-1] += "\n"
    for key, val in updates.items():
        if key not in seen:
            out_lines.append(f"{key}={val}\n")

    _atomic_write(env_path, "".join(out_lines))


def delete_keys(env_path: Path, keys: Iterable[str]) -> None:
    """Remove `KEY=...` lines for any KEY in keys. Comments and unrelated lines kept."""
    if not env_path.exists():
        return
    drop = set(keys)
    original = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    out_lines = []
    for line in original:
        stripped = line.lstrip()
        if not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in drop:
                continue
        out_lines.append(line)
    _atomic_write(env_path, "".join(out_lines))


def _atomic_write(path: Path, content: str) -> None:
    """Write to a sibling temp file then os.replace — atomic on POSIX + Windows."""
    suffix = secrets.token_hex(4)
    tmp = path.with_suffix(path.suffix + f".{suffix}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(str(tmp), str(path))
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise
