"""Proje sihirbazı giriş doğrulama — SRP ayrımı (SOLID-SRP-2).

wizard_steps.py'den ayrıldı: validasyon sorumluluğu tek modülde toplanır.
Tüm regex kalıpları ve WizardValidator sınıfı buradadır; wizard_steps.py
UI akışına odaklanır.
"""
from __future__ import annotations

import os
import re


# ── Derlenmiş regex kalıpları ─────────────────────────────────────────────
# Modül yüklenirken bir kez derlenir; her mesajda yeniden derlenmez.

# Cmd string'inden port çıkarma — genişletilmiş format desteği
# --port 8020 / --port=8020 / -p 8020 / PORT=8020 / port=8020 / :8020
PORT_RE = re.compile(
    r"(?:--port[=\s]+|-p\s+|[Pp][Oo][Rr][Tt]\s*=\s*|:)(\d{2,5})"
)

PATH_TRAVERSAL_RE = re.compile(r"(^|/)\.\.(/|$)")

# Kabul edilen kök dizinler — güvensiz sistem yollarını engeller
SAFE_PATH_PREFIXES: tuple[str, ...] = (
    "/home/", "/tmp/", "/opt/", "/srv/", "/var/projects/", "/projects/",
)

WINDOW_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,50}$")

# Shell injection için tehlikeli karakter kalıbı
UNSAFE_CMD_RE = re.compile(r"[;&|`$<>]|\$\(|`|\n|\r|\x00")


class WizardValidator:
    """Wizard adımlarına özgü giriş doğrulama metotları (SRP).

    Tüm metotlar static; WizardValidator() örneği oluşturmak gerekmez.
    Her metot ya None (geçerli) ya da hata nedeni string'i döner.
    """

    @staticmethod
    def extract_port(cmd: str) -> str | None:
        """Komut string'inden port numarasını çıkarır; bulunamazsa None döner."""
        m = PORT_RE.search(cmd)
        return m.group(1) if m else None

    @staticmethod
    def validate_service_name(name: str) -> str | None:
        """Servis adını doğrular. Hata varsa hata nedeni string'i, geçerliyse None döner."""
        if not WINDOW_NAME_RE.match(name):
            return "invalid_name"
        return None

    @staticmethod
    def validate_service_cmd(cmd: str) -> str | None:
        """Servis komutunu güvenlik açısından doğrular. Hata varsa string, geçerliyse None."""
        if UNSAFE_CMD_RE.search(cmd):
            return "unsafe_cmd"
        return None

    @staticmethod
    def validate_port(port: str) -> str | None:
        """Port string'ini doğrular (1-65535 veya boş). Hata varsa string, geçerliyse None."""
        if not port or port == "-":
            return None
        try:
            port_int = int(port)
            if not (1 <= port_int <= 65535):
                raise ValueError
        except ValueError:
            return "invalid_port"
        return None

    @staticmethod
    def validate_path(path: str) -> str | None:
        """Proje yolunu güvenlik açısından doğrular. Hata varsa neden string'i, geçerliyse None.

        Kontroller (sırayla):
          1. Mutlak yol zorunlu
          2. Path traversal engeli
          3. Güvenli ön ek kontrolü
        """
        if not path.startswith("/"):
            return "not_absolute"
        if PATH_TRAVERSAL_RE.search(path):
            return "traversal"
        home = os.path.expanduser("~")
        if not any(path.startswith(p) for p in SAFE_PATH_PREFIXES) and not path.startswith(home):
            return "unsafe_prefix"
        return None
