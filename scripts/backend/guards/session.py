"""Session yönetimi — kullanıcı başına in-memory oturum durumu (SRP).

SessionState: app_types.py'de tanımlı. Bu modül yalnızca CRUD yapar.

Session sıfırlanırken (reset / TTL süresi) session_summaries tablosuna özet
kaydedilir — hiçbir oturum kaybedilmez.
"""
from __future__ import annotations

import asyncio
import logging
import time

from ..app_types import SessionState

logger = logging.getLogger(__name__)

_SESSION_TTL_HOURS = 24  # config yüklenmeden önce default; başlatmada settings'ten alınır


class SessionManager:
    """Her WhatsApp numarası için oturum durumu tutar."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def lock(self, number: str) -> asyncio.Lock:
        """Gönderici başına asyncio kilidi — eş zamanlı mesajlarda race condition'ı önler."""
        return self._locks.setdefault(number, asyncio.Lock())

    def get(self, number: str) -> SessionState:
        self._maybe_expire(number)
        if number not in self._sessions:
            session = SessionState(
                active_context="main",
                beta_project_id=None,
                awaiting_totp=False,
                pending_command="",
                menu_page=0,
                last_activity=time.time(),
                started_at=time.time(),
            )
            self._apply_persisted_settings(number, session)
            self._sessions[number] = session
        self._sessions[number]["last_activity"] = time.time()
        return self._sessions[number]

    def reset(self, number: str) -> None:
        """Özet kaydederek session'ı sıfırla."""
        session = self._sessions.get(number)
        if session:
            self._save_summary(number, session)
        self._sessions.pop(number, None)

    def reset_silent(self, number: str) -> None:
        """Özet kaydetmeden sıfırla (başlatma / test için)."""
        self._sessions.pop(number, None)

    def set_beta(self, number: str, project_id: str) -> None:
        session = self.get(number)
        session["active_context"] = f"project:{project_id}"
        session["beta_project_id"] = project_id
        session["active_project_id"] = project_id

    def set_active_project(self, number: str, project_id: str | None) -> None:
        """Ana modda odaklanılan projeyi set et."""
        session = self.get(number)
        session["active_project_id"] = project_id

    def exit_beta(self, number: str) -> None:
        session = self.get(number)
        # Beta context için özet kaydet
        self._save_summary(number, session)
        session["active_context"] = "main"
        session["beta_project_id"] = None
        session["started_at"] = time.time()  # Yeni "main" session başlat

    async def cleanup_expired(self) -> int:
        """Süresi dolmuş tüm session'ları temizle. Temizlenen sayısını döndürür.

        Her session için per-session lock alınır; check ve pop atomik olarak
        yapılır. Bu sayede lock ile korunan mesaj işleme arasında TOCTOU
        (Time-of-Check to Time-of-Use) race condition oluşmaz: mesaj handler
        lock'u tutarken last_activity'yi güncelleyebilir, cleanup bu durumda
        lock'u bekler ve tekrar kontrol eder.
        """
        candidates = list(self._sessions)
        cleaned = 0
        for number in candidates:
            lock = self.lock(number)
            async with lock:
                if not self._is_expired(number):
                    continue
                session = self._sessions.pop(number, None)
                if session:
                    logger.info("Session TTL doldu (cleanup): %s", number)
                    self._save_summary(number, session)
                    # Lock'u dict'ten çıkar — lock nesnesi async with çıkışında
                    # release edilir; yeni mesaj gelirse lock() yeni bir lock oluşturur.
                    self._locks.pop(number, None)
                    cleaned += 1
        return cleaned

    # ── Dahili ───────────────────────────────────────────────────

    def _is_expired(self, number: str) -> bool:
        session = self._sessions.get(number)
        if not session:
            return False
        try:
            from ..config import settings
            ttl_seconds = settings.session_ttl_hours * 3600
        except Exception:
            ttl_seconds = _SESSION_TTL_HOURS * 3600
        return time.time() - session.get("last_activity", 0) > ttl_seconds

    def _maybe_expire(self, number: str) -> None:
        """Uzun süre inaktif session'ı TTL'e göre sonlandır."""
        if self._is_expired(number):
            session = self._sessions.pop(number, None)
            if session:
                logger.info("Session TTL doldu: %s", number)
                self._save_summary(number, session)

    def _apply_persisted_settings(self, number: str, session: SessionState) -> None:
        """DB'deki kullanıcı ayarlarını yeni session'a uygula (FEAT-6)."""
        try:
            from ..store.repositories.settings_repo import _sync_user_settings_get_all
            stored = _sync_user_settings_get_all(number)
            if "lang" in stored:
                session["lang"] = stored["lang"]
        except Exception as exc:
            logger.warning("Kullanıcı ayarları yüklenemedi (%s): %s", number, exc)

    def _save_summary(self, number: str, session: SessionState) -> None:
        try:
            from ..store.message_logger import save_session_summary
            save_session_summary(
                sender=number,
                context_id=session.get("active_context", "main"),
                started_at=session.get("started_at", time.time()),
                ended_at=time.time(),
            )
        except Exception as exc:
            logger.warning("Session özet kaydedilemedi: %s", exc)
