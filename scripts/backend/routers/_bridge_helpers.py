"""Bridge yardımcı modülü — REFAC-9 (SRP).

Bu modül _bridge_client.py'den ayrıştırılan iki ayrı sorumluluğu barındırır:

1. Dosya adı sanitizasyonu (güvenlik / PI-FIX-3)
2. CLAUDE.md önbelleği (statik kaynak yükleme — K8)

_bridge_client.py → iletim mantığı (retry, forwarding, hata eşleme)
"""
from __future__ import annotations

import re
from pathlib import Path

# ── Dosya adı sanitizasyonu (PI-FIX-3) ───────────────────────────────────

_SAFE_FILENAME_RE = re.compile(r"[^\w.\-\s]", re.UNICODE)


def sanitize_filename(name: str) -> str:
    """Dosya adından potansiyel injection karakterlerini kaldır, uzunluğu sınırla."""
    safe = _SAFE_FILENAME_RE.sub("_", name or "")
    return safe[:200] or "(isimsiz)"


# ── CLAUDE.md önbelleği (K8) ──────────────────────────────────────────────
# Modül yüklenirken bir kez okunur; her /query çağrısında disk I/O önlenir.

_ROOT = Path(__file__).parent.parent.parent.parent
CLAUDE_MD_CACHE: str = ""

_claude_md_path = _ROOT / "CLAUDE.md"
if _claude_md_path.exists() and not _claude_md_path.is_symlink():
    try:
        CLAUDE_MD_CACHE = _claude_md_path.read_text(encoding="utf-8")
    except Exception:
        pass
