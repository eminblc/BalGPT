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


# ── Aktif effort seviyesi ────────────────────────────────────────────────────
# Claude Code CLI `--effort <low|medium|high|max>` flag'i için aktif seviye.
# None = CLI varsayılanı kullan; /effort komutuyla değiştirilir, restart sonrası
# DB'den (user_settings) geri yüklenir.
_VALID_EFFORTS: frozenset[str] = frozenset({"low", "medium", "high", "max"})
_active_effort: str | None = None


def get_active_effort() -> str | None:
    """Çalışma zamanında seçilen effort seviyesini döndürür; ayarlanmamışsa None."""
    with _state_lock:
        return _active_effort


def set_active_effort(effort: str | None) -> None:
    """Çalışma zamanı effort seviyesini global olarak değiştirir.

    Geçersiz değer (low/medium/high/max dışı) sessizce yok sayılır; None ile
    sıfırlanabilir (CLI varsayılanına dön).
    """
    global _active_effort
    with _state_lock:
        if effort is None or effort in _VALID_EFFORTS:
            _active_effort = effort


# ── Aktif Extended Thinking toggle ───────────────────────────────────────────
# VS Code'daki "Thinking" toggle'ının Telegram karşılığı (effort'tan bağımsız).
# False (varsayılan) → effort seviyesi seçili olsa bile thinking payload/flag gönderilmez.
# True               → effort seviyesi seçili ise thinking + budget_tokens ile gönderilir.
# DB'de "thinking" key'i altında "1"/"0" olarak kalıcı.
_active_thinking: bool = False


def get_active_thinking() -> bool:
    """Extended Thinking şu an aktif mi?"""
    with _state_lock:
        return _active_thinking


def set_active_thinking(enabled: bool) -> None:
    """Extended Thinking toggle'ını global olarak değiştirir."""
    global _active_thinking
    with _state_lock:
        _active_thinking = bool(enabled)

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


# ── Aktif scan run_id takibi ─────────────────────────────────────────────────
# AllScansRunner ve dış komutların (pause/resume) aktif run_id'yi bilmesi için.
_active_scan_run_id: str | None = None


def set_active_scan_run_id(run_id: str | None) -> None:
    """Aktif scan run_id'sini kaydet (scan başlarken set, bitince None)."""
    global _active_scan_run_id
    with _state_lock:
        _active_scan_run_id = run_id


def get_active_scan_run_id() -> str | None:
    """Şu an çalışan scan'in run_id'sini döndürür; yoksa None."""
    with _state_lock:
        return _active_scan_run_id


# ── Global scan duraklatma ───────────────────────────────────────────────────
# AllScansRunner scan_type döngüsü başında kontrol eder.
# ScannerAgent/ReviewerAgent için per-run_id pause: ScanPauseStore kullanır.
_scan_pause_requested: bool = False


def request_scan_pause() -> None:
    """Aktif scan'i durdur (global flag + aktif run_id'nin dosya state'i)."""
    global _scan_pause_requested
    from ..features.scan_pipeline.scan_pause_store import ScanPauseStore  # noqa: PLC0415
    with _state_lock:
        _scan_pause_requested = True
        run_id = _active_scan_run_id
    if run_id:
        ScanPauseStore.request_pause(run_id)


def request_scan_resume() -> None:
    """Duraklatılmış scan'i devam ettir (global flag + aktif run_id'nin dosya state'i)."""
    global _scan_pause_requested
    from ..features.scan_pipeline.scan_pause_store import ScanPauseStore  # noqa: PLC0415
    with _state_lock:
        _scan_pause_requested = False
        run_id = _active_scan_run_id
    if run_id:
        ScanPauseStore.request_resume(run_id)


def clear_scan_pause() -> None:
    """Global pause flag'ini sıfırla; yeni bir scan başlamadan önce çağrılmalı."""
    global _scan_pause_requested
    with _state_lock:
        _scan_pause_requested = False


def is_scan_pause_requested() -> bool:
    """Global pause flag'i set edilmişse True döner."""
    with _state_lock:
        return _scan_pause_requested


# ── Backlog executor iptali ──────────────────────────────────────────────────
# True → devam eden backlog executor her yeni item öncesinde durmalı.
# BacklogExecutorAgent.run() başlangıcında clear_backlog_cancel() çağırır.
_backlog_cancel_requested: bool = False


def request_backlog_cancel() -> None:
    """Aktif backlog executor'ın iptalini iste."""
    global _backlog_cancel_requested
    with _state_lock:
        _backlog_cancel_requested = True


def clear_backlog_cancel() -> None:
    """İptal flag'ini sıfırla; yeni bir executor başlamadan önce çağrılmalı."""
    global _backlog_cancel_requested
    with _state_lock:
        _backlog_cancel_requested = False


def is_backlog_cancel_requested() -> bool:
    """Backlog executor iptal flag'i set edilmişse True döner."""
    with _state_lock:
        return _backlog_cancel_requested


# ── Backlog executor kuyruk sayacı ─────────────────────────────────────────
# Aktif + kuyrukta bekleyen run sayısı. "Tümü" akışında 3 ayrı POST geldiğinde
# 3 olur; her run() exit'inde 1 azalır. is_first kararı, ilk run'ın cancel
# flag'ini temizleme yetkisi olduğunu söyler — sonradan gelen kuyruklananlar
# (counter > 1 iken enter olanlar) cancel state'ini paylaşır.
_active_backlog_runs: int = 0


def enter_backlog_run() -> bool:
    """Kuyruğa yeni bir backlog run kaydet; bu run, kuyruğa giren ilk mi?

    Returns:
        True → kuyruk şu ana kadar boştu; bu run ``clear_backlog_cancel()``
        çağırma yetkisine sahiptir (taze başlangıç).
        False → bu run kuyruğa bağlı; önceki cancel state'i miras alır.
    """
    global _active_backlog_runs
    with _state_lock:
        was_empty = (_active_backlog_runs == 0)
        _active_backlog_runs += 1
        return was_empty


def exit_backlog_run() -> None:
    """run() exit'inde kuyruk sayacını azalt."""
    global _active_backlog_runs
    with _state_lock:
        if _active_backlog_runs > 0:
            _active_backlog_runs -= 1


def get_backlog_queue_size() -> int:
    """Aktif + bekleyen backlog run sayısı (0 → idle)."""
    with _state_lock:
        return _active_backlog_runs
