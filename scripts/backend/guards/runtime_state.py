"""Paylaşılan çalışma zamanı state'i (SRP).

Router dosyalarında modül düzeyinde dict tanımlanmaz.
Tüm paylaşılan state buradadır.
"""
from __future__ import annotations

import time

# ── Uygulama kilidi ──────────────────────────────────────────────────────────
# Başlangıçta kilitli; /unlock + TOTP ile açılır, /lock + TOTP ile tekrar kilitlenir.
_locked: bool = True


def is_locked() -> bool:
    """Uygulama kilitli mi?"""
    return _locked


def set_locked(value: bool) -> None:
    """Kilit durumunu değiştir."""
    global _locked
    _locked = value


# ── Aktif LLM modeli ─────────────────────────────────────────────────────────
# None = config.settings.default_model kullan (varsayılan)
# Servis yeniden başlatılana kadar kalıcı; /model komutuyla değiştirilir.
_active_model: str | None = None


def get_active_model() -> str | None:
    """Çalışma zamanında seçilen LLM modelini döndürür; ayarlanmamışsa None."""
    return _active_model


def set_active_model(model: str | None) -> None:
    """Çalışma zamanı LLM modelini global olarak değiştirir."""
    global _active_model
    _active_model = model

# Bridge son durum bildirimleri: { number: {"text": str, "ts": float} }
_last_status: dict[str, dict] = {}

_STATUS_TTL        = 1800.0   # 30 dakika — tamamlanmayan işlemleri temizle
_STATUS_CLEANUP_IV = 300.0    # 5 dakikada bir lazy temizlik
_last_cleanup: float = 0.0


def _maybe_evict(now: float) -> None:
    """TTL süresi geçmiş durum kayıtlarını temizle."""
    global _last_cleanup
    if now - _last_cleanup < _STATUS_CLEANUP_IV:
        return
    stale = [k for k, v in _last_status.items() if now - v["ts"] > _STATUS_TTL]
    for k in stale:
        del _last_status[k]
    _last_cleanup = now


def record_status(number: str, text: str) -> None:
    """⚙️ ile başlayan bildirimleri kaydet, ✅/❌ ile temizle."""
    now = time.time()
    _maybe_evict(now)
    if text.startswith("⚙️"):
        _last_status[number] = {"text": text, "ts": now}
    elif text.startswith(("✅", "❌")):
        _last_status.pop(number, None)


def get_last_status(number: str) -> dict | None:
    return _last_status.get(number)
