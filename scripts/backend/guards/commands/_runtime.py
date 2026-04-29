"""Çalışma ortamı tespiti — systemd | docker | pm2 | unknown."""
import os
import shutil
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def detect_runtime() -> str:
    """Servisin hangi ortamda çalıştığını döner."""
    if Path("/.dockerenv").exists():
        return "docker"
    if os.environ.get("PM2_HOME") or os.environ.get("pm_id"):
        return "pm2"
    if os.environ.get("INVOCATION_ID") or shutil.which("systemctl"):
        return "systemd"
    return "unknown"
