"""Loglama konfigürasyonu — her katman için ayrı log dosyası (SRP).

Dosyalar:
  app.log      — genel uygulama logları (INFO+)
  webhook.log  — WhatsApp webhook gelen/giden (DEBUG+)
  bridge.log   — Bridge çağrıları, promptlar, yanıtlar (DEBUG+)
  media.log    — medya indirme/yükleme (DEBUG+)
  history.log  — session açılış/kapanış, özet kayıtları (INFO+)
  error.log    — sadece ERROR+ (tüm modüllerden)
  security.log — güvenlik olayları WARNING+ (TOTP başarısızlıkları, kilitlenmeler,
                 yetkisiz erişim denemeleri; guards + auth katmanından)
  desktop.log  — desktop/terminal endpoint işlemleri DEBUG+ (internal router çağrıları)

webhook.log ayrıca şunları içerir:
  _dispatcher    — platform-agnostik mesaj yönlendirme (DEBUG+)
  _auth_flows    — TOTP/math challenge akışları (DEBUG+; security.log WARNING+ ile örtüşür)

Her dosya: JSON Lines, 10 MB rotate, 10 backup (100 MB toplam).

Güvenlik:
  SensitiveHeaderFilter — x-api-key ve authorization header değerlerini loglardan gizler.
  Filtre tüm handler'lara (root dahil) uygulanır.
"""
from __future__ import annotations

import logging
import logging.config
import re
from pathlib import Path

# Logda değeri gizlenecek header adları (küçük harf)
SENSITIVE_HEADERS: frozenset[str] = frozenset({"x-api-key", "authorization"})

# Eşleşme kalıpları:
#   "x-api-key: abc123"                    → HTTP header satırı / unquoted
#   "'x-api-key': 'abc123'"                → Python repr (tek tırnak)
#   '"x-api-key": "abc123"'                → JSON (çift tırnak)
#   '"authorization": "Bearer tok123"'     → Bearer token (boşluklu değer, çift tırnak içinde)
#   "authorization: Bearer tok123"         → Bearer token, düz metin
_HEADER_PATTERN = re.compile(
    r"(?i)(" + "|".join(re.escape(h) for h in SENSITIVE_HEADERS) + r")"
    r"""(["']?\s*[:=]\s*)"""
    r"""("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|[^,}\]\n"']+)""",
    re.IGNORECASE,
)


def _redact(text: str) -> str:
    """Log mesajındaki hassas header değerlerini <redacted> ile değiştirir."""

    def _replace(m: re.Match) -> str:
        header, sep, val = m.group(1), m.group(2), m.group(3)
        # Alıntılı değer ise aynı tırnak türünü koru
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            return f'{header}{sep}{val[0]}<redacted>{val[-1]}'
        return f'{header}{sep}<redacted>'

    return _HEADER_PATTERN.sub(_replace, text)


class SensitiveHeaderFilter(logging.Filter):
    """Tüm log kayıtlarındaki hassas header değerlerini gizler (SEC-L1).

    Hem ``record.getMessage()`` çıktısını hem de ``record.args`` ve
    ``record.msg`` alanlarını temizler; bu sayede JSON formatter gibi
    farklı formatter'lar da korunur.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        # msg string ise doğrudan temizle
        if isinstance(record.msg, str):
            record.msg = _redact(record.msg)

        # args tuple/dict ise her elemanı temizle
        if isinstance(record.args, tuple):
            record.args = tuple(
                _redact(a) if isinstance(a, str) else a for a in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                k: (_redact(v) if isinstance(v, str) else v)
                for k, v in record.args.items()
            }

        return True

LOG_DIR = Path(__file__).parent.parent.parent / "outputs" / "logs"


def configure_logging(level: str = "INFO") -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    def _rotating(filename: str, log_level: str = level) -> dict:
        return {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / filename),
            "maxBytes": 10_000_000,   # 10 MB
            "backupCount": 10,
            "formatter": "json",
            "encoding": "utf-8",
            "level": log_level,
        }

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,

        "filters": {
            "sensitive_headers": {
                "()": SensitiveHeaderFilter,
            },
        },

        "formatters": {
            "json": {
                "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
                "format": (
                    "%(asctime)s %(name)s %(levelname)s %(message)s "
                    "%(funcName)s %(lineno)d"
                ),
            },
            "console": {
                "format": "%(levelname)-8s %(name)s: %(message)s",
            },
        },

        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "console",
                "level": level,
                "filters": ["sensitive_headers"],
            },
            "app_file":      {**_rotating("app.log"),             "filters": ["sensitive_headers"]},
            "webhook_file":  {**_rotating("webhook.log",  "DEBUG"), "filters": ["sensitive_headers"]},
            "bridge_file":   {**_rotating("bridge.log",   "DEBUG"), "filters": ["sensitive_headers"]},
            "media_file":    {**_rotating("media.log",    "DEBUG"), "filters": ["sensitive_headers"]},
            "history_file":  {**_rotating("history.log",  "INFO"),  "filters": ["sensitive_headers"]},
            "error_file":    {**_rotating("error.log",    "ERROR"), "filters": ["sensitive_headers"]},
            "security_file": {**_rotating("security.log", "WARNING"), "filters": ["sensitive_headers"]},
            "desktop_file":  {**_rotating("desktop.log",  "DEBUG"), "filters": ["sensitive_headers"]},
        },

        "loggers": {
            # WhatsApp webhook — tüm gelen/giden mesajlar
            "backend.routers.whatsapp_router": {
                "handlers": ["webhook_file"],
                "level": "DEBUG",
                "propagate": True,
            },
            # Telegram webhook — tüm gelen/giden mesajlar
            "backend.routers.telegram_router": {
                "handlers": ["webhook_file"],
                "level": "DEBUG",
                "propagate": True,
            },
            # Bridge çağrıları
            "backend.features.chat": {
                "handlers": ["bridge_file"],
                "level": "DEBUG",
                "propagate": True,
            },
            # Medya
            "backend.whatsapp.cloud_api": {
                "handlers": ["media_file"],
                "level": "DEBUG",
                "propagate": True,
            },
            # Medya handler
            "backend.features.media_handler": {
                "handlers": ["media_file"],
                "level": "DEBUG",
                "propagate": True,
            },
            # History / session özet
            "backend.store.message_logger": {
                "handlers": ["history_file"],
                "level": "INFO",
                "propagate": True,
            },
            "backend.features.history": {
                "handlers": ["history_file"],
                "level": "INFO",
                "propagate": True,
            },
            # Guard katmanı — security.log'a da yazılır (WARNING+)
            "backend.guards": {
                "handlers": ["app_file", "security_file"],
                "level": "DEBUG",
                "propagate": True,
            },
            # Mesaj yönlendirme — platform-agnostik dispatch
            "backend.routers._dispatcher": {
                "handlers": ["webhook_file"],
                "level": "DEBUG",
                "propagate": True,
            },
            # Auth akışları (TOTP, math challenge, brute-force kilidi)
            # security_file: WARNING+ güvenlik olayları; webhook_file: tüm akış DEBUG+
            "backend.routers._auth_flows": {
                "handlers": ["security_file", "webhook_file"],
                "level": "DEBUG",
                "propagate": True,
            },
            # Auth dispatcher (registry tabanlı akış yönlendirme)
            "backend.routers._auth_dispatcher": {
                "handlers": ["security_file"],
                "level": "WARNING",
                "propagate": True,
            },
            # Desktop endpoint (screenshot, type, click, vision_query vb.)
            "backend.routers.desktop_router": {
                "handlers": ["desktop_file"],
                "level": "DEBUG",
                "propagate": True,
            },
            # Terminal endpoint (shell komut çalıştırma)
            "backend.routers.terminal_router": {
                "handlers": ["desktop_file"],
                "level": "DEBUG",
                "propagate": True,
            },
        },

        # Root: app.log + error.log + console
        "root": {
            "handlers": ["app_file", "error_file", "console"],
            "level": level,
        },
    })
