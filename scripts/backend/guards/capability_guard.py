"""Yetenek kısıtlama guard — FEAT-3.

OCP: yeni kısıtlama = yeni dosyadan register_capability_rule() çağrısı.
     Bu dosyaya veya router'a dokunulmaz. llm_factory.register_backend() kalıbıyla aynı.

Kullanım:
    from backend.guards.capability_guard import register_capability_rule, CapabilityRule
    register_capability_rule(CapabilityRule("restrict_foo", "foo",
                                            lambda ctx: _FOO_RE.search(_text(ctx)) is not None))
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Callable, Optional

from .guard_chain import GuardContext, GuardResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapabilityRule:
    """Tek bir yetenek kısıtlama kuralı.

    env_key:  config.Settings üzerindeki bool field adı (ör. "restrict_media")
    label:    i18n suffix ve log etiketi (ör. "media") → t("capability.media", lang)
    matcher:  GuardContext alıp True döndüğünde kuralın tetiklendiğini belirtir
    """
    env_key:  str
    label:    str
    matcher:  Callable[[GuardContext], bool]


def _text(ctx: GuardContext) -> str:
    """GuardContext'ten lowercase mesaj metnini çıkarır.

    WhatsApp mesajları doğrudan ctx.msg ile gelir; Telegram router
    metni {"text": {"body": text}} formatına normalize ederek iletir.
    """
    msg      = ctx.msg or {}
    text_obj = msg.get("text") or {}
    body     = text_obj.get("body", "") if isinstance(text_obj, dict) else str(text_obj)
    return body.lower()


# Pre-compiled patterns — modül yüklenirken bir kez derlenir, her mesajda yeniden derlenmez
_FS_RE      = re.compile(r"\.\./\.\.|/etc/|/usr/|/var/lib|/root/")
_NET_RE     = re.compile(r"https?://|curl\s|wget\s")
_SHELL_RE   = re.compile(r"\bbash\b|\bsh\b|\bexec\b|\bsubprocess\b")
_SVC_RE     = re.compile(r"systemctl|tmux|servis.*ba[sş]lat|servis.*durdur|service\s+(start|stop)")
_CAL_RE     = re.compile(r"takvim|hat[iı]rlatıcı|remind|calendar|schedule|zamanlı")
_WIZ_RE     = re.compile(r"proje.*olu[sş]tur|yeni.*proje|new.*project|create.*project")
_SS_RE      = re.compile(r"ekran\s*g[oö]r[uü]nt[uü]s[uü]|screenshot|playwright|puppeteer")
_PDF_RE     = re.compile(r"\bpdf\b.*(?:import|içe\s*aktar|yükle|upload)|(?:import|içe\s*aktar|yükle|upload).*\bpdf\b", re.IGNORECASE)
# Sadece açık CRUD aksiyonlarını yakalar; genel "plan" kelimesini değil
_PLANS_RE   = re.compile(
    r"/plan\b"
    r"|iş\s*plan[ıi]"
    r"|yeni\s*plan\s*(ekle|oluştur|yaz)"
    r"|plan\s*(ekle|sil|tamamla|listele|göster)"
    r"|work\s*plan|task\s*(creat|add|list|delet)",
    re.IGNORECASE,
)


# OCP extension point — llm_factory._BACKENDS kalıbıyla aynı
# Yeni kısıtlama eklemek için bu dosyaya dokunma: register_capability_rule() kullan
_RULES: list[CapabilityRule] = [
    CapabilityRule("restrict_fs_outside_root", "filesystem",
                   lambda ctx: _FS_RE.search(_text(ctx)) is not None),
    CapabilityRule("restrict_network",         "network",
                   lambda ctx: _NET_RE.search(_text(ctx)) is not None),
    CapabilityRule("restrict_shell",           "shell",
                   lambda ctx: _SHELL_RE.search(_text(ctx)) is not None),
    CapabilityRule("restrict_service_mgmt",    "service_mgmt",
                   lambda ctx: _SVC_RE.search(_text(ctx)) is not None),
    CapabilityRule("restrict_media",           "media",
                   lambda ctx: ctx.msg_type in ("image", "video", "document", "audio")),
    CapabilityRule("restrict_calendar",        "calendar",
                   lambda ctx: _CAL_RE.search(_text(ctx)) is not None),
    CapabilityRule("restrict_project_wizard",  "project_wizard",
                   lambda ctx: _WIZ_RE.search(_text(ctx)) is not None),
    CapabilityRule("restrict_screenshot",      "screenshot",
                   # TODO: Playwright özelliği eklendiğinde feature-call guard da eklenmeli
                   lambda ctx: _SS_RE.search(_text(ctx)) is not None),
    CapabilityRule("restrict_plans",           "plans",
                   lambda ctx: _PLANS_RE.search(_text(ctx)) is not None),
    CapabilityRule("restrict_pdf_import",      "pdf_import",
                   lambda ctx: ctx.msg_type == "document" or _PDF_RE.search(_text(ctx)) is not None),
    # WIZ-LLM-6: feature-call düzeyinde enforce edilir (wizard_steps.py:72).
    # Burada kayıt yalnızca log_active_restrictions() görünürlüğü + install.sh
    # cap_keys uyumu için; mesaj düzeyinde eşleşme yok (matcher False döner).
    CapabilityRule("restrict_wizard_llm_scaffold", "wizard_llm_scaffold",
                   lambda ctx: False),
]


def register_capability_rule(rule: CapabilityRule) -> None:
    """Dışarıdan yeni kısıtlama kuralı eklemek için — OCP extension point.

    Yeni bir kısıtlama eklemek için bu dosyayı değiştirme; bu fonksiyonu çağır:

        from backend.guards.capability_guard import register_capability_rule, CapabilityRule
        register_capability_rule(CapabilityRule(
            "restrict_foo",
            "foo",
            lambda ctx: _FOO_RE.search(_text(ctx)) is not None,
        ))

    Checklist — yeni kısıtlama eklerken:
      1. config.py'e ilgili restrict_foo bool field'ı ekle
      2. .env.example'a açıklama satırı ekle
      3. install.sh → cap_keys/cap_envs (veya enabled_keys/enabled_envs) dizilerine ekle
      4. locales/tr.json ve locales/en.json → capability.* key'leri ekle
    """
    _RULES.append(rule)
    logger.debug("Yetenek kuralı kaydedildi: %s", rule.label)


class CapabilityGuard:
    """Yapılandırılmış yetenek kısıtlamalarını mesaj düzeyinde uygular.

    Guard zincirinde owner doğrulandıktan sonra çalışır. cfg.restrict_* = True olan
    ve matcher'ı tetiklenen ilk kuralda mesaj engellenir; kullanıcıya yerelleşmiş
    bildirim gönderilir.

    DIP: messenger opsiyonel olarak inject edilebilir; verilmezse get_messenger() lazy çağrılır.
    Bu sayede testlerde mock messenger geçilebilir.
    """

    def __init__(self, cfg=None, messenger=None) -> None:
        if cfg is None:
            from ..config import settings
            cfg = settings
        self._cfg = cfg
        self._messenger = messenger  # None → lazy get_messenger()

    def _get_messenger(self):
        if self._messenger is not None:
            return self._messenger
        # Lazy import: guards paketi uygulama başında yüklenir; bu noktada
        # messenger_factory henüz hazır olmayabilir. Döngüsel import riski de var.
        from ..adapters.messenger.messenger_factory import get_messenger
        return get_messenger()

    async def check(self, ctx: GuardContext) -> GuardResult:
        for rule in _RULES:
            if getattr(self._cfg, rule.env_key, False) and rule.matcher(ctx):
                logger.info(
                    "Yetenek kısıtlandı: capability=%s sender=%.6s",
                    rule.label, ctx.sender,
                )
                try:
                    from ..i18n import t
                    cap_name = t(f"capability.{rule.label}", ctx.lang)
                    await self._get_messenger().send_text(
                        ctx.sender,
                        t("guard.capability_restricted", ctx.lang, capability=cap_name),
                    )
                except Exception:
                    logger.debug("Yetenek bildirim gönderilemedi: capability=%s", rule.label)
                return GuardResult(passed=False, reason=f"capability_restricted:{rule.label}")
        return GuardResult(passed=True)

    def log_active_restrictions(self) -> None:
        """Başlangıçta aktif kısıtlamaları loglar (main.py lifespan içinden çağrılır)."""
        active = [r.label for r in _RULES if getattr(self._cfg, r.env_key, False)]
        if active:
            logger.warning("CapabilityGuard — kısıtlı yetenekler: %s", ", ".join(active))
        else:
            logger.info("CapabilityGuard — tüm yetenekler aktif (kısıtlama yok)")
