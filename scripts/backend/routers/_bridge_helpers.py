"""Bridge yardımcı modülü — REFAC-9 (SRP).

Sorumluluk:
  - Dosya adı sanitizasyonu (güvenlik / PI-FIX-3)

CLAUDE.md önbelleği (K8) CTX-LOSS-1 ile kaldırıldı: Claude Code CLI cwd'deki
CLAUDE.md'yi otomatik yüklüyor; init_prompt'a tekrar koymak çift bağlam yaratıyordu.

_bridge_client.py → iletim mantığı (retry, forwarding, hata eşleme)
"""
from __future__ import annotations

import re

# ── Dosya adı sanitizasyonu (PI-FIX-3) ───────────────────────────────────

_SAFE_FILENAME_RE = re.compile(r"[^\w.\-\s]", re.UNICODE)


def sanitize_filename(name: str) -> str:
    """Dosya adından potansiyel injection karakterlerini kaldır, uzunluğu sınırla."""
    safe = _SAFE_FILENAME_RE.sub("_", name or "")
    return safe[:200] or "(isimsiz)"
