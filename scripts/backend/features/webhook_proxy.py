"""Webhook proxy yöneticisi — ngrok / cloudflared / external / none.

Startup'ta start_proxy() çağrılır; public URL'yi döndürür ve saklar.
Diğer modüller get_public_url() ile okur.

Desteklenen modlar:
  ngrok       — pyngrok kütüphanesi ile tünel açar (ngrok kurulu olmalı)
  cloudflared — cloudflared CLI ile tünel açar (cloudflared kurulu olmalı)
  external    — settings.public_url değerini kullanır
  none        — proxy başlatılmaz; URL None döner

OOP uyumu: Tüm mutable state WebhookProxyManager sınıfında kapsüllenmiştir.
Kod kuralı: os.environ doğrudan okunmaz; settings üzerinden erişilir.
"""
from __future__ import annotations

import logging
import re
import subprocess
import threading
import time

logger = logging.getLogger(__name__)


class WebhookProxyManager:
    """Webhook proxy lifecycle state'ini kapsülleyen yönetici sınıf.

    SRP: Yalnızca proxy başlatma/durdurma sorumluluğunu taşır.
    OOP: Tüm mutable state constructor'da tanımlanan instance değişkenlerindedir.
    """

    def __init__(self) -> None:
        self._public_url: str | None = None
        self._active_mode: str = "none"
        self._cloudflared_proc: subprocess.Popen[bytes] | None = None

    # ── Public API ────────────────────────────────────────────────

    def get_public_url(self) -> str | None:
        """Başlatılan proxy'nin public URL'sini döndür. None = proxy yok."""
        return self._public_url

    def stop(self) -> None:
        """Çalışan proxy'yi durdur; process'leri temizle."""
        if self._active_mode == "ngrok":
            try:
                from pyngrok import ngrok  # type: ignore
                ngrok.kill()
                logger.info("ngrok tünelleri kapatıldı.")
            except Exception as exc:
                logger.warning("ngrok kapatma hatası: %s", exc)

        elif self._active_mode == "cloudflared":
            if self._cloudflared_proc is not None:
                try:
                    self._cloudflared_proc.terminate()
                    self._cloudflared_proc.wait(timeout=5)
                    logger.info("cloudflared process sonlandırıldı.")
                except Exception as exc:
                    logger.warning("cloudflared kapatma hatası: %s", exc)
                finally:
                    self._cloudflared_proc = None

        self._public_url = None
        self._active_mode = "none"

    def start(self, mode: str, port: int) -> str | None:
        """Belirtilen modda proxy başlat; public URL'yi döndür.

        Args:
            mode: "ngrok" | "cloudflared" | "external" | "none"
            port: FastAPI'nin dinlediği yerel port (örn. 8010)

        Returns:
            Public HTTPS URL (https://...) veya None.
        """
        mode = (mode or "none").strip().lower()
        self._active_mode = mode

        if mode == "ngrok":
            self._public_url = self._start_ngrok(port)
        elif mode == "cloudflared":
            self._public_url = self._start_cloudflared(port)
        elif mode == "external":
            self._public_url = self._read_external_url()
        elif mode == "none":
            logger.info("Webhook proxy devre dışı (WEBHOOK_PROXY=none).")
            self._public_url = None
        else:
            logger.warning("Bilinmeyen WEBHOOK_PROXY modu: %r — proxy başlatılmadı.", mode)
            self._public_url = None

        if self._public_url:
            logger.info("Webhook public URL: %s", self._public_url)

        return self._public_url

    async def lifecycle_startup(self) -> None:
        import asyncio as _aio
        from ..config import settings
        await _aio.to_thread(self.start, settings.webhook_proxy, settings.port)

    async def lifecycle_shutdown(self) -> None:
        import asyncio as _aio
        try:
            await _aio.to_thread(self.stop)
        except Exception as exc:
            logger.warning("Webhook proxy kapatma hatası: %s", exc)

    # ── Private helpers ───────────────────────────────────────────

    def _start_ngrok(self, port: int) -> str | None:
        try:
            from pyngrok import ngrok, conf  # type: ignore
            from ..config import settings

            ngrok_token = settings.ngrok_authtoken
            if ngrok_token:
                conf.get_default().auth_token = ngrok_token

            connect_kwargs: dict = {"proto": "http"}
            if settings.ngrok_domain:
                connect_kwargs["hostname"] = settings.ngrok_domain
            tunnel = ngrok.connect(port, **connect_kwargs)
            url: str = tunnel.public_url  # type: ignore[attr-defined]
            # ngrok ücretsiz planda http → https yönlendirir; https'i tercih et
            if url.startswith("http://"):
                url = url.replace("http://", "https://", 1)
            logger.info("ngrok tüneli açıldı: %s → localhost:%d", url, port)
            return url
        except ImportError:
            logger.error(
                "pyngrok kurulu değil. Kur: pip install pyngrok  "
                "veya WEBHOOK_PROXY=none yap."
            )
        except Exception as e:
            logger.error("ngrok başlatılamadı: %s", e)
        return None

    def _start_cloudflared(self, port: int) -> str | None:
        """cloudflared Quick Tunnel açar; stdout'tan URL'yi okur (en fazla 15 saniye bekler)."""
        try:
            proc = subprocess.Popen(
                ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self._cloudflared_proc = proc  # type: ignore[assignment]
        except FileNotFoundError:
            logger.error(
                "cloudflared bulunamadı. Kur: "
                "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
            )
            return None

        url_pattern = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
        found_url: list[str] = []

        def _reader() -> None:
            assert proc.stdout
            for line in proc.stdout:
                logger.debug("cloudflared: %s", line.rstrip())
                m = url_pattern.search(line)
                if m and not found_url:
                    found_url.append(m.group(0))

        reader_thread = threading.Thread(target=_reader, daemon=True)
        reader_thread.start()

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not found_url:
            time.sleep(0.2)

        if found_url:
            logger.info("cloudflared tüneli açıldı: %s → localhost:%d", found_url[0], port)
            return found_url[0]

        logger.error("cloudflared URL 15 saniyede alınamadı.")
        proc.terminate()
        return None

    def _read_external_url(self) -> str | None:
        from ..config import settings
        url = settings.public_url.strip()
        if not url:
            logger.error(
                "WEBHOOK_PROXY=external ancak PUBLIC_URL tanımlı değil. "
                ".env'e PUBLIC_URL=https://... ekle."
            )
            return None
        if not url.startswith("https://"):
            logger.warning("PUBLIC_URL 'https://' ile başlamıyor: %r", url)
        logger.info("Harici webhook URL kullanılıyor: %s", url)
        return url


# Modül düzeyinde singleton — main.py ve _registry.py mevcut API'yi kullanır
_manager = WebhookProxyManager()


# ── Backward-compat shim'ler ─────────────────────────────────────────────────

def get_public_url() -> str | None:
    """Başlatılan proxy'nin public URL'sini döndür."""
    return _manager.get_public_url()


def stop_proxy() -> None:
    """Çalışan proxy'yi durdur."""
    _manager.stop()


def start_proxy(mode: str, port: int) -> str | None:
    """Belirtilen modda proxy başlat; public URL'yi döndür."""
    return _manager.start(mode, port)


async def lifecycle_startup() -> None:
    await _manager.lifecycle_startup()


async def lifecycle_shutdown() -> None:
    await _manager.lifecycle_shutdown()
