"""Paylaşılan çalışma zamanı state'i (SRP).

Router dosyalarında modül düzeyinde dict tanımlanmaz.
Tüm paylaşılan state buradadır.
"""
from __future__ import annotations

import threading
import time

# Tüm state mutasyonlarını korumak için tek bir threading.Lock.
# asyncio.Lock kullanılmıyor: bu fonksiyonlar hem sync hem async çağrı
# noktalarından erişilebilir; threading.Lock asyncio event-loop içinde
# de güvenlidir (GIL sayesinde atomik okuma/yazma zaten sağlanmıştı;
# lock ile explicit kritik bölge tanımlanmış olur).
_state_lock = threading.Lock()

# ── Uygulama kilidi ──────────────────────────────────────────────────────────
# Başlangıçta kilitli; /unlock + TOTP ile açılır, /lock + TOTP ile tekrar kilitlenir.
_locked: bool = True


def is_locked() -> bool:
    """Uygulama kilitli mi?"""
    with _state_lock:
        return _locked


def set_locked(value: bool) -> None:
    """Kilit durumunu değiştir."""
    global _locked
    with _state_lock:
        _locked = value


# ── Aktif LLM modeli ─────────────────────────────────────────────────────────
# None = config.settings.default_model kullan (varsayılan)
# Servis yeniden başlatılana kadar kalıcı; /model komutuyla değiştirilir.
_active_model: str | None = None


def get_active_model() -> str | None:
    """Çalışma zamanında seçilen LLM modelini döndürür; ayarlanmamışsa None."""
    with _state_lock:
        return _active_model


def set_active_model(model: str | None) -> None:
    """Çalışma zamanı LLM modelini global olarak değiştirir."""
    global _active_model
    with _state_lock:
        _active_model = model

# Bridge son durum bildirimleri: { number: {"text": str, "ts": float} }
_last_status: dict[str, dict] = {}

_STATUS_TTL        = 1800.0   # 30 dakika — tamamlanmayan işlemleri temizle
_STATUS_CLEANUP_IV = 300.0    # 5 dakikada bir lazy temizlik
_last_cleanup: float = 0.0


def _maybe_evict(now: float) -> None:
    """TTL süresi geçmiş durum kayıtlarını temizle. _state_lock tutularak çağrılmalı."""
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
    with _state_lock:
        _maybe_evict(now)
        if text.startswith("⚙️"):
            _last_status[number] = {"text": text, "ts": now}
        elif text.startswith(("✅", "❌")):
            _last_status.pop(number, None)


def get_last_status(number: str) -> dict | None:
    with _state_lock:
        return _last_status.get(number)


# ── Scan iptali ──────────────────────────────────────────────────────────────
# True → devam eden scan chunk döngüsü en kısa sürede durmalı.
# AllScansRunner başlarken clear_scan_cancel() çağırır (stale flag temizliği).
_scan_cancel_requested: bool = False


def request_scan_cancel() -> None:
    """Aktif scan'in iptalini iste; bir sonraki chunk kontrolünde durur."""
    global _scan_cancel_requested
    with _state_lock:
        _scan_cancel_requested = True


def clear_scan_cancel() -> None:
    """İptal flag'ini sıfırla; yeni bir scan başlamadan önce çağrılmalı."""
    global _scan_cancel_requested
    with _state_lock:
        _scan_cancel_requested = False


def is_scan_cancel_requested() -> bool:
    """İptal flag'i set edilmişse True döner."""
    with _state_lock:
        return _scan_cancel_requested


# ── Scan çalışma kilidi ──────────────────────────────────────────────────────
# True → bir scan background task'i şu an aktif; yeni scan başlatılamaz.
# Backlog executor bu flag'i okumaz/yazmaz — sadece scan'ler kilitler.
_scan_running: bool = False


def set_scan_running(value: bool) -> None:
    """Scan çalışma bayrağını değiştir (True = aktif, False = boşta)."""
    global _scan_running
    with _state_lock:
        _scan_running = value


def is_scan_running() -> bool:
    """Halihazırda bir scan çalışıyor mu?"""
    with _state_lock:
        return _scan_running
