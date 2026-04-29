"""SQLite bağlantı yönetimi — paylaşılan altyapı (SRP).

Tüm repository'lerin import ettiği tek bağlantı noktası.
Başka modüllere bağımlılığı yoktur (circular import riski sıfır).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator


def _resolve_db_path() -> Path:
    """DB dosyasının mutlak yolunu döndür (99-root/data/personal_agent.db)."""
    base = Path(__file__).parent.parent.parent.parent  # 99-root/
    return base / "data" / "personal_agent.db"


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    """Thread-safe SQLite bağlantı context manager'ı."""
    path = _resolve_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")  # PERF-OPT-7: WAL+NORMAL — fsync yalnızca checkpoint'te
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
