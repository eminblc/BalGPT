"""
Bağımlılık import testleri.

Her capability için gereken Python paketlerinin kurulu ve import edilebilir
olduğunu doğrular. Capability devre dışıysa ilgili testler atlanır.

Paket türleri:
  HARD  — kurulu olmazsa uygulama çalışmaz (test başarısız olur)
  SOFT  — kurulu olmazsa fallback devreye girer (test uyarı verir, başarısız olmaz)

Çalıştırma:
    cd scripts && backend/venv/bin/python -m pytest tests/test_imports.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# ── .env okuyucu ────────────────────────────────────────────────────────────

_ENV_FILE = Path(__file__).parent.parent / "backend" / ".env"


def _read_env(key: str, default: str = "") -> str:
    """Basit .env okuyucu — dotenv veya os.environ'a bağımlı olmadan çalışır."""
    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line[len(key) + 1 :].strip().strip('"').strip("'")
    return os.environ.get(key, default)


def _cap_enabled(restrict_var: str) -> bool:
    """RESTRICT_* flag: 'false' veya eksik → etkin."""
    return _read_env(restrict_var, "false").lower() != "true"


def _feat_enabled(enabled_var: str) -> bool:
    """*_ENABLED flag: 'true' → etkin."""
    return _read_env(enabled_var, "false").lower() == "true"


# ── Core importlar (her zaman çalışmalı — HARD) ─────────────────────────────

class TestCoreImports:
    """Core paketler kurulu değilse uygulama hiç başlamaz."""

    def test_fastapi(self):
        import fastapi  # noqa: F401

    def test_uvicorn(self):
        import uvicorn  # noqa: F401

    def test_pydantic(self):
        from pydantic import BaseModel, SecretStr  # noqa: F401

    def test_pydantic_settings(self):
        from pydantic_settings import BaseSettings  # noqa: F401

    def test_httpx(self):
        import httpx  # noqa: F401

    def test_tenacity(self):
        from tenacity import retry  # noqa: F401

    def test_pyotp(self):
        import pyotp  # noqa: F401

    def test_cryptography(self):
        import cryptography  # noqa: F401

    def test_python_json_logger(self):
        import pythonjsonlogger  # noqa: F401

    def test_starlette(self):
        # FastAPI'nin transitive dep'i; _localhost_guard.py'de doğrudan kullanılır.
        from starlette.requests import Request  # noqa: F401

    def test_dotenv(self):
        # pydantic-settings'in transitive dep'i; .env yüklemesi için gerekli.
        import dotenv  # noqa: F401


# ── Capability-conditional importlar ────────────────────────────────────────

class TestSchedulerImports:
    """scheduler.txt — RESTRICT_SCHEDULER=false olduğunda gerekli. (HARD)"""

    @pytest.fixture(autouse=True)
    def skip_if_disabled(self):
        if not _cap_enabled("RESTRICT_SCHEDULER"):
            pytest.skip(".env: RESTRICT_SCHEDULER=true — paket kurulu olmayabilir")

    def test_apscheduler_asyncio(self):
        from apscheduler.schedulers.asyncio import AsyncIOScheduler  # noqa: F401

    def test_apscheduler_sqlalchemy_jobstore(self):
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore  # noqa: F401

    def test_apscheduler_base(self):
        from apscheduler.jobstores.base import JobLookupError  # noqa: F401

    def test_sqlalchemy(self):
        import sqlalchemy  # noqa: F401


class TestPdfImportImports:
    """pdf_import.txt — RESTRICT_PDF_IMPORT=false olduğunda gerekli. (HARD)"""

    @pytest.fixture(autouse=True)
    def skip_if_disabled(self):
        if not _cap_enabled("RESTRICT_PDF_IMPORT"):
            pytest.skip(".env: RESTRICT_PDF_IMPORT=true — paket kurulu olmayabilir")

    def test_pymupdf(self):
        import fitz  # noqa: F401  (pymupdf)


class TestCalendarImports:
    """calendar.txt — RESTRICT_CALENDAR=false olduğunda gerekli. (HARD)"""

    @pytest.fixture(autouse=True)
    def skip_if_disabled(self):
        if not _cap_enabled("RESTRICT_CALENDAR"):
            pytest.skip(".env: RESTRICT_CALENDAR=true — paket kurulu olmayabilir")

    def test_dateparser(self):
        import dateparser  # noqa: F401


class TestScreenshotImports:
    """screenshot.txt — RESTRICT_SCREENSHOT=false olduğunda ilgili.

    mss: SOFT — scrot subprocess fallback'i var; eksikse uyarı verilir.
    Pillow: HARD — resize işlemi için zorunlu.
    """

    @pytest.fixture(autouse=True)
    def skip_if_disabled(self):
        if not _cap_enabled("RESTRICT_SCREENSHOT"):
            pytest.skip(".env: RESTRICT_SCREENSHOT=true — paket kurulu olmayabilir")

    def test_pillow(self):
        from PIL import Image  # noqa: F401

    def test_mss_soft(self):
        """mss opsiyonel; eksikse fallback=scrot. Başarısızlık uyarıdır, blokaj değil."""
        try:
            import mss  # noqa: F401
        except ImportError:
            pytest.skip(
                "mss kurulu değil — scrot fallback kullanılacak. "
                "Hız için: pip install mss"
            )


class TestMediaImports:
    """media.txt — RESTRICT_MEDIA=false olduğunda gerekli. (HARD)"""

    @pytest.fixture(autouse=True)
    def skip_if_disabled(self):
        if not _cap_enabled("RESTRICT_MEDIA"):
            pytest.skip(".env: RESTRICT_MEDIA=true — paket kurulu olmayabilir")

    def test_pillow(self):
        from PIL import Image  # noqa: F401


class TestDesktopImports:
    """desktop.txt — DESKTOP_ENABLED=true olduğunda ilgili.

    python-xlib / mss: SOFT — subprocess fallback'leri var.
    Pillow: HARD — resize için zorunlu.
    """

    @pytest.fixture(autouse=True)
    def skip_if_disabled(self):
        if not _feat_enabled("DESKTOP_ENABLED"):
            pytest.skip(".env: DESKTOP_ENABLED=false — paket kurulu olmayabilir")

    def test_pillow(self):
        from PIL import Image  # noqa: F401

    def test_xlib_soft(self):
        """python-xlib opsiyonel; eksikse xdotool subprocess fallback."""
        try:
            from Xlib import display  # noqa: F401
        except ImportError:
            pytest.skip(
                "python-xlib kurulu değil — xdotool fallback kullanılacak. "
                "Hız için: pip install python-xlib"
            )

    def test_mss_soft(self):
        """mss opsiyonel; eksikse scrot subprocess fallback."""
        try:
            import mss  # noqa: F401
        except ImportError:
            pytest.skip(
                "mss kurulu değil — scrot fallback kullanılacak. "
                "Hız için: pip install mss"
            )


class TestBrowserImports:
    """browser.txt — BROWSER_ENABLED=true olduğunda gerekli. (HARD)"""

    @pytest.fixture(autouse=True)
    def skip_if_disabled(self):
        if not _feat_enabled("BROWSER_ENABLED"):
            pytest.skip(".env: BROWSER_ENABLED=false — paket kurulu olmayabilir")

    def test_playwright(self):
        if not _feat_enabled("BROWSER_ENABLED"):
            pytest.skip(".env: BROWSER_ENABLED=false — paket kurulu olmayabilir")
        from playwright.async_api import async_playwright  # noqa: F401


# ── Kritik uygulama başlangıç testleri ──────────────────────────────────────

class TestAppStartup:
    """Uygulamanın import zinciri kırılmadan yüklendiğini doğrular."""

    def test_app_import(self):
        """'from backend.main import app' hatasız çalışmalı."""
        scripts_dir = str(Path(__file__).parent.parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)

        # settings'in .env'siz de çalışması için minimum env ayarla
        _required = {
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "API_KEY": "test-key",
            "TOTP_SECRET": "JBSWY3DPEHPK3PXP",
            "TOTP_SECRET_ADMIN": "JBSWY3DPEHPK3PXP",
            "WHATSAPP_OWNER": "+905000000000",
        }
        for k, v in _required.items():
            os.environ.setdefault(k, v)

        from backend.main import app  # noqa: F401
        assert app is not None

    def test_scheduler_importable_without_apscheduler(self, monkeypatch):
        """scheduler.py, apscheduler kurulu olmasa bile import edilebilmeli."""
        # Tüm apscheduler modüllerini sys.modules'dan geçici gizle
        aps_keys = [k for k in sys.modules if k.startswith("apscheduler")]
        for k in aps_keys:
            monkeypatch.delitem(sys.modules, k)

        # scheduler modülünü cache'ten temizle — yeniden import zorla
        sched_key = "backend.features.scheduler"
        monkeypatch.delitem(sys.modules, sched_key, raising=False)

        # apscheduler importlarını blokla
        import builtins
        real_import = builtins.__import__

        def _blocking_import(name, *args, **kwargs):
            if name.startswith("apscheduler"):
                raise ImportError(f"[test] apscheduler engellendi: {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _blocking_import)

        import importlib
        mod = importlib.import_module("backend.features.scheduler")
        assert mod._APSCHEDULER_AVAILABLE is False, \
            "apscheduler yokken _APSCHEDULER_AVAILABLE True olmamalı"
        assert mod._scheduler is None, \
            "apscheduler yokken _scheduler None olmalı"
