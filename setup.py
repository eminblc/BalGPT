#!/usr/bin/env python3
"""Personal Agent — İnteraktif kurulum sihirbazı.

Kullanım:
    python setup.py

stdlib dışı bağımlılık yoktur.
"""
from __future__ import annotations

import base64
import secrets
import sys
from abc import ABC, abstractmethod
from pathlib import Path


# ── Renkler (ANSI; TTY yoksa düz metin) ─────────────────────────────────────
_USE_COLOR = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def bold(t: str)   -> str: return _c("1",  t)
def cyan(t: str)   -> str: return _c("36", t)
def green(t: str)  -> str: return _c("32", t)
def yellow(t: str) -> str: return _c("33", t)
def red(t: str)    -> str: return _c("31", t)
def dim(t: str)    -> str: return _c("2",  t)


# ── TOTP secret üretici (pyotp olmadan) ──────────────────────────────────────
def _make_totp_secret() -> str:
    """20 byte rastgele → Base32 (pyotp uyumlu)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


# ── BaseSetupStep ────────────────────────────────────────────────────────────
class BaseSetupStep(ABC):
    """Her soru kendi sınıfında yaşar (SRP).

    Alt sınıf en az ``prompt()`` ve ``env_key()`` metodlarını uygulamalıdır.
    """

    @abstractmethod
    def prompt(self) -> str:
        """Kullanıcıya gösterilecek soru başlığı."""

    @abstractmethod
    def env_key(self) -> str:
        """.env'e yazılacak anahtar."""

    def example(self) -> str:
        """Örnek değer (parantez içinde gösterilir)."""
        return ""

    def hint(self) -> str:
        """Nereden bulunacağını açıklayan kısa metin."""
        return ""

    def optional(self) -> bool:
        """True ise Enter ile atlanabilir."""
        return False

    def default(self) -> str:
        """optional() True iken Enter'a basılınca kullanılır."""
        return ""

    def validate(self, val: str) -> bool:
        """False dönerse girdi reddedilir; hata mesajını bu metod basar."""
        return bool(val)

    # ------------------------------------------------------------------
    def ask(self) -> tuple[str, str]:
        """Değeri okur, (env_key, value) döndürür."""
        while True:
            lines = [bold(self.prompt())]
            if self.example():
                lines.append(dim(f"  örnek : {self.example()}"))
            if self.hint():
                lines.append(dim(f"  nereden: {self.hint()}"))
            if self.optional():
                dflt = f" [{self.default()}]" if self.default() else " [atla]"
                lines.append(dim(f"  (isteğe bağlı{dflt} — Enter ile geç)"))
            print("\n".join(lines))

            try:
                raw = input(cyan("  > ")).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nİptal edildi.")
                sys.exit(0)

            if not raw:
                if self.optional():
                    return self.env_key(), self.default()
                print(red("  Bu alan zorunludur."))
                continue

            if not self.validate(raw):
                continue

            return self.env_key(), raw


# ── Zorunlu adımlar ──────────────────────────────────────────────────────────
class MessengerStep(BaseSetupStep):
    def prompt(self)  -> str: return "Mesajlaşma platformu (MESSENGER_TYPE)"
    def env_key(self) -> str: return "MESSENGER_TYPE"
    def example(self) -> str: return "whatsapp"
    def hint(self)    -> str: return "whatsapp | telegram  (Telegram desteği yakında)"
    def optional(self) -> bool: return True
    def default(self) -> str: return "whatsapp"

    def validate(self, val: str) -> bool:
        if val not in {"whatsapp", "telegram"}:
            print(red("  Geçersiz değer. Desteklenenler: whatsapp, telegram"))
            return False
        return True


class WhatsAppTokenStep(BaseSetupStep):
    def prompt(self)  -> str: return "WHATSAPP_ACCESS_TOKEN"
    def env_key(self) -> str: return "WHATSAPP_ACCESS_TOKEN"
    def example(self) -> str: return "EAAxxxxxxxxxxxxxxx"
    def hint(self)    -> str: return "Meta Developer → WhatsApp → API Setup → Access Token"


class PhoneNumberIdStep(BaseSetupStep):
    def prompt(self)  -> str: return "WHATSAPP_PHONE_NUMBER_ID"
    def env_key(self) -> str: return "WHATSAPP_PHONE_NUMBER_ID"
    def example(self) -> str: return "123456789012345"
    def hint(self)    -> str: return "Meta Developer → WhatsApp → API Setup → Phone Number ID"


class AppSecretStep(BaseSetupStep):
    def prompt(self)  -> str: return "WHATSAPP_APP_SECRET"
    def env_key(self) -> str: return "WHATSAPP_APP_SECRET"
    def example(self) -> str: return "abcdef1234567890abcdef1234567890"
    def hint(self)    -> str: return "Meta Developer → Uygulamanız → App Settings → App Secret"


class VerifyTokenStep(BaseSetupStep):
    def prompt(self)  -> str: return "WHATSAPP_VERIFY_TOKEN"
    def env_key(self) -> str: return "WHATSAPP_VERIFY_TOKEN"
    def example(self) -> str: return "my-secret-webhook-token-2024"
    def hint(self)    -> str: return "Webhook doğrulama için kendin belirle (rastgele string)"


class OwnerNumberStep(BaseSetupStep):
    def prompt(self)  -> str: return "WHATSAPP_OWNER"
    def env_key(self) -> str: return "WHATSAPP_OWNER"
    def example(self) -> str: return "+905xxxxxxxxx"
    def hint(self)    -> str: return "Komut gönderecek WhatsApp numarası (+ ile ülke kodu)"

    def validate(self, val: str) -> bool:
        if not val.startswith("+"):
            print(red("  Numara + ile başlamalı (örn. +905xxxxxxxxx)"))
            return False
        return True


class AnthropicKeyStep(BaseSetupStep):
    def prompt(self)  -> str: return "ANTHROPIC_API_KEY"
    def env_key(self) -> str: return "ANTHROPIC_API_KEY"
    def example(self) -> str: return "sk-ant-api03-..."
    def hint(self)    -> str: return "https://console.anthropic.com → API Keys"

    def validate(self, val: str) -> bool:
        if not val.startswith("sk-ant-"):
            print(yellow("  Uyarı: Anthropic anahtarları genellikle 'sk-ant-' ile başlar."))
            try:
                ans = input(cyan("  Yine de kullanmak istiyor musun? [e/H] ")).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nİptal edildi.")
                sys.exit(0)
            return ans in ("e", "evet", "y", "yes")
        return True


class ApiKeyStep(BaseSetupStep):
    def __init__(self) -> None:
        self._generated = secrets.token_urlsafe(32)

    def prompt(self)  -> str: return "API_KEY  (dahili /agent/* endpoint'leri için)"
    def env_key(self) -> str: return "API_KEY"
    def example(self) -> str: return self._generated
    def hint(self)    -> str: return "Güçlü rastgele string — yukarıdaki örnek otomatik üretildi"


class TotpStep(BaseSetupStep):
    def __init__(self) -> None:
        self._generated = _make_totp_secret()

    def prompt(self)  -> str: return "TOTP_SECRET  (normal komutlar için)"
    def env_key(self) -> str: return "TOTP_SECRET"
    def example(self) -> str: return self._generated
    def hint(self) -> str:
        return "Yukarıdaki örnek otomatik üretildi — TOTP uygulamanıza (Google Authenticator vb.) ekleyin"


class TotpAdminStep(BaseSetupStep):
    def __init__(self) -> None:
        self._generated = _make_totp_secret()

    def prompt(self)  -> str: return "TOTP_SECRET_ADMIN  (!restart / !shutdown için ayrı TOTP)"
    def env_key(self) -> str: return "TOTP_SECRET_ADMIN"
    def example(self) -> str: return self._generated
    def hint(self)    -> str: return "Yukarıdaki örnek otomatik üretildi — birinci TOTP'dan farklı olmalı"


# ── İsteğe bağlı adımlar ─────────────────────────────────────────────────────
class WhatsAppApiVersionStep(BaseSetupStep):
    def prompt(self)   -> str:  return "WHATSAPP_API_VERSION"
    def env_key(self)  -> str:  return "WHATSAPP_API_VERSION"
    def example(self)  -> str:  return "v19.0"
    def optional(self) -> bool: return True
    def default(self)  -> str:  return "v19.0"


class FastapiPortStep(BaseSetupStep):
    def prompt(self)   -> str:  return "FASTAPI_PORT"
    def env_key(self)  -> str:  return "FASTAPI_PORT"
    def example(self)  -> str:  return "8010"
    def optional(self) -> bool: return True
    def default(self)  -> str:  return "8010"


class BridgePortStep(BaseSetupStep):
    def prompt(self)   -> str:  return "BRIDGE_PORT"
    def env_key(self)  -> str:  return "BRIDGE_PORT"
    def example(self)  -> str:  return "8013"
    def optional(self) -> bool: return True
    def default(self)  -> str:  return "8013"


class ClaudeBridgeUrlStep(BaseSetupStep):
    def prompt(self)   -> str:  return "CLAUDE_BRIDGE_URL"
    def env_key(self)  -> str:  return "CLAUDE_BRIDGE_URL"
    def example(self)  -> str:  return "http://localhost:8013"
    def hint(self)     -> str:  return "BRIDGE_PORT ile aynı port kullanılmalı"
    def optional(self) -> bool: return True
    def default(self)  -> str:  return "http://localhost:8013"


class ClaudePermissionsStep(BaseSetupStep):
    def prompt(self)   -> str:  return "CLAUDE_CODE_PERMISSIONS"
    def env_key(self)  -> str:  return "CLAUDE_CODE_PERMISSIONS"
    def example(self)  -> str:  return "bypassPermissions"
    def hint(self)     -> str:  return "bypassPermissions | default"
    def optional(self) -> bool: return True
    def default(self)  -> str:  return "bypassPermissions"


class ClaudeMaxTurnsStep(BaseSetupStep):
    def prompt(self)   -> str:  return "CLAUDE_CODE_MAX_TURNS"
    def env_key(self)  -> str:  return "CLAUDE_CODE_MAX_TURNS"
    def example(self)  -> str:  return "1000"
    def hint(self)     -> str:  return "Tek sorguda maksimum Claude Code turu"
    def optional(self) -> bool: return True
    def default(self)  -> str:  return "1000"


class ClaudeTimeoutStep(BaseSetupStep):
    def prompt(self)   -> str:  return "CLAUDE_CODE_TIMEOUT_MS"
    def env_key(self)  -> str:  return "CLAUDE_CODE_TIMEOUT_MS"
    def example(self)  -> str:  return "300000"
    def hint(self)     -> str:  return "ms cinsinden zaman aşımı (300000 = 5 dakika)"
    def optional(self) -> bool: return True
    def default(self)  -> str:  return "300000"


class SessionTtlStep(BaseSetupStep):
    def prompt(self)   -> str:  return "SESSION_TTL_HOURS"
    def env_key(self)  -> str:  return "SESSION_TTL_HOURS"
    def example(self)  -> str:  return "24"
    def hint(self)     -> str:  return "Bellek içi oturum yaşam süresi (saat)"
    def optional(self) -> bool: return True
    def default(self)  -> str:  return "24"


class LogLevelStep(BaseSetupStep):
    def prompt(self)   -> str:  return "LOG_LEVEL"
    def env_key(self)  -> str:  return "LOG_LEVEL"
    def example(self)  -> str:  return "INFO"
    def hint(self)     -> str:  return "DEBUG | INFO | WARNING | ERROR"
    def optional(self) -> bool: return True
    def default(self)  -> str:  return "INFO"

    def validate(self, val: str) -> bool:
        if val.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            print(red("  Geçersiz değer. İzin verilenler: DEBUG, INFO, WARNING, ERROR"))
            return False
        return True


# ── Yol ayarları (çok nadir değişir) ─────────────────────────────────────────
class RootDirStep(BaseSetupStep):
    def prompt(self)   -> str:  return "ROOT_DIR  (yol geçersizleme)"
    def env_key(self)  -> str:  return "ROOT_DIR"
    def hint(self)     -> str:  return "Varsayılan: repo kökü otomatik tespit edilir — boş bırakabilirsin"
    def optional(self) -> bool: return True
    def default(self)  -> str:  return ""


class ProjectsDirStep(BaseSetupStep):
    def prompt(self)   -> str:  return "PROJECTS_DIR"
    def env_key(self)  -> str:  return "PROJECTS_DIR"
    def hint(self)     -> str:  return "Varsayılan: <ROOT_DIR>/data/projects"
    def optional(self) -> bool: return True
    def default(self)  -> str:  return ""


class SessionsDirStep(BaseSetupStep):
    def prompt(self)   -> str:  return "SESSIONS_DIR"
    def env_key(self)  -> str:  return "SESSIONS_DIR"
    def hint(self)     -> str:  return "Varsayılan: <ROOT_DIR>/data/claude_sessions"
    def optional(self) -> bool: return True
    def default(self)  -> str:  return ""


class ConvHistoryDirStep(BaseSetupStep):
    def prompt(self)   -> str:  return "CONV_HISTORY_DIR"
    def env_key(self)  -> str:  return "CONV_HISTORY_DIR"
    def hint(self)     -> str:  return "Varsayılan: <ROOT_DIR>/data/conv_history"
    def optional(self) -> bool: return True
    def default(self)  -> str:  return ""


class ActiveContextPathStep(BaseSetupStep):
    def prompt(self)   -> str:  return "ACTIVE_CONTEXT_PATH"
    def env_key(self)  -> str:  return "ACTIVE_CONTEXT_PATH"
    def hint(self)     -> str:  return "Varsayılan: <ROOT_DIR>/data/active_context.json"
    def optional(self) -> bool: return True
    def default(self)  -> str:  return ""


# ── EnvWriter ────────────────────────────────────────────────────────────────
class EnvWriter:
    """Toplanan anahtar-değer çiftlerini .env dosyasına yazar."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def write(self, values: dict[str, str]) -> None:
        lines = [
            "# Personal Agent — .env (setup.py tarafından oluşturuldu)",
            "# Değiştirmek için bu dosyayı doğrudan düzenleyebilirsin.",
            "",
        ]
        for key, val in values.items():
            if val:
                lines.append(f"{key}={val}")

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(green(f"\n✔  .env yazıldı: {self._path}"))


# ── SetupOrchestrator ────────────────────────────────────────────────────────
class SetupOrchestrator:
    """Adımları sırayla çalıştırır (OCP: yeni adım = yeni sınıf, orchestrator değişmez)."""

    def __init__(
        self,
        required: list[BaseSetupStep],
        optional: list[BaseSetupStep],
        writer: EnvWriter,
    ) -> None:
        self._required = required
        self._optional = optional
        self._writer = writer

    def run(self) -> None:
        _print_banner()

        env_path = self._writer._path
        if env_path.exists():
            try:
                ans = input(yellow(f"  '{env_path}' zaten var. Üzerine yazmak ister misin? [e/H] ")).strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nİptal edildi.")
                sys.exit(0)
            if ans not in ("e", "evet", "y", "yes"):
                print("  İptal edildi.")
                sys.exit(0)

        print(f"\n{bold('── Zorunlu Alanlar ──')}")
        print(dim("  Enter geçerli değil — tüm alanlar doldurulmalıdır.\n"))

        values: dict[str, str] = {}

        for step in self._required:
            key, val = step.ask()
            values[key] = val
            print()

        print(f"\n{bold('── İsteğe Bağlı Alanlar ──')}")
        print(dim("  Enter ile varsayılan değer kabul edilir.\n"))

        for step in self._optional:
            key, val = step.ask()
            values[key] = val
            print()

        self._writer.write(values)
        _print_next_steps()


# ── Yardımcı çıktı fonksiyonları ─────────────────────────────────────────────
def _print_banner() -> None:
    print()
    print(bold("══════════════════════════════════════════"))
    print(bold("   Personal Agent — Kurulum Sihirbazı   "))
    print(bold("══════════════════════════════════════════"))
    print()


def _print_next_steps() -> None:
    print(green("✔  Kurulum tamamlandı!\n"))
    print("  Sonraki adım — birini seç:")
    print(f"  {bold('Docker  :')}  docker compose up -d")
    print(f"  {bold('systemd :')}  sudo ./install.sh")
    print()
    print(dim("  Servis sağlığı:"))
    print(dim("    curl -s http://localhost:8010/health"))
    print(dim("    curl -s http://localhost:8013/health"))
    print()


# ── Adım listeleri ────────────────────────────────────────────────────────────
def _build_required() -> list[BaseSetupStep]:
    return [
        MessengerStep(),
        WhatsAppTokenStep(),
        PhoneNumberIdStep(),
        AppSecretStep(),
        VerifyTokenStep(),
        OwnerNumberStep(),
        AnthropicKeyStep(),
        ApiKeyStep(),
        TotpStep(),
        TotpAdminStep(),
    ]


def _build_optional() -> list[BaseSetupStep]:
    return [
        WhatsAppApiVersionStep(),
        FastapiPortStep(),
        BridgePortStep(),
        ClaudeBridgeUrlStep(),
        ClaudePermissionsStep(),
        ClaudeMaxTurnsStep(),
        ClaudeTimeoutStep(),
        SessionTtlStep(),
        LogLevelStep(),
        RootDirStep(),
        ProjectsDirStep(),
        SessionsDirStep(),
        ConvHistoryDirStep(),
        ActiveContextPathStep(),
    ]


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    env_path = Path(__file__).parent / "scripts" / "backend" / ".env"
    orchestrator = SetupOrchestrator(
        required=_build_required(),
        optional=_build_optional(),
        writer=EnvWriter(env_path),
    )
    orchestrator.run()


if __name__ == "__main__":
    main()
