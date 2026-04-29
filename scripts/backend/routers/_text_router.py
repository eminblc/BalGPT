"""Metin mesajı yönlendirme — !komutlar, wizard adımları, niyet tespiti, Bridge iletimi (SRP).

Sorumluluk: Metin mesajlarını doğru hedefe yönlendirmek.
Auth state akışları: _auth_dispatcher.py
Genel dispatch (interactive vb.): _dispatcher.py

Wizard state dispatch OCP-V2: _WIZ_REGISTRY sözlüğü session key'ini handler fonksiyonuna eşler.
Yeni wizard adımı eklemek için bu dosyaya dokunmak gerekmez; _WIZ_REGISTRY'ye giriş eklemek yeterlidir.
"""
from __future__ import annotations

import logging
import random
from typing import Awaitable, Callable

from ..guards import get_perm_mgr, Perm
from ..guards.commands import registry as cmd_registry
from ..store.message_logger import log_outbound
from ..adapters.messenger.messenger_factory import get_messenger
from ..i18n import t
from ..features.project_wizard import (
    ask_description,
    ask_auto_arch,
    handle_arch_edit_input,
    handle_path_input,
    handle_service_name,
    handle_service_cmd,
    handle_service_port,
    handle_service_cwd,
    clear_wizard,
)
from . import _intent_classifier

logger = logging.getLogger(__name__)

# Matematik challenge gerektiren yıkıcı komutlar (math challenge → owner TOTP)
_MATH_CHALLENGE_CMDS: frozenset[str] = frozenset({"/shutdown", "/restart", "/project-delete"})

# ── Wizard state handler registry ──────────────────────────────────────────
# Key: session flag → async handler(sender, text, session) -> None
# Yeni wizard adımı: handler fonksiyonu yaz + _WIZ_REGISTRY'ye ekle.

async def _wiz_project_name(sender: str, text: str, session: dict) -> None:
    lang = session.get("lang", "tr")
    context_id = session.get("active_context", "main")
    messenger = get_messenger()
    name = text.strip()
    if not name:
        await messenger.send_text(sender, t("cmd.wiz_empty_name", lang))
        log_outbound(sender, "text", "wiz_empty_name", context_id=context_id)
        return
    session.accept_project_name()
    await ask_description(sender, name, session)
    log_outbound(sender, "text", "wiz_ask_description", context_id=context_id)


async def _wiz_project_description(sender: str, text: str, session: dict) -> None:
    context_id = session.get("active_context", "main")
    desc = "" if text.strip() == "-" else text.strip()
    session.accept_project_description(desc)
    # WIZ-LLM-4: Açıklamadan sonra önce AI mimari önerisi sor (ask_auto_arch);
    # restrict_wizard_llm_scaffold=True ise ask_auto_arch sessizce ask_options'a düşer.
    await ask_auto_arch(sender, session)
    log_outbound(sender, "text", "wiz_ask_auto_arch", context_id=context_id)


async def _wiz_arch_edit(sender: str, text: str, session: dict) -> None:
    context_id = session.get("active_context", "main")
    await handle_arch_edit_input(sender, text, session)
    log_outbound(sender, "text", "wiz_arch_edit_input", context_id=context_id)


async def _wiz_project_path(sender: str, text: str, session: dict) -> None:
    context_id = session.get("active_context", "main")
    await handle_path_input(sender, text, session)
    log_outbound(sender, "text", "wiz_path_input", context_id=context_id)


async def _wiz_service_name(sender: str, text: str, session: dict) -> None:
    context_id = session.get("active_context", "main")
    await handle_service_name(sender, text, session)
    log_outbound(sender, "text", "wiz_service_name", context_id=context_id)


async def _wiz_service_cmd(sender: str, text: str, session: dict) -> None:
    context_id = session.get("active_context", "main")
    await handle_service_cmd(sender, text, session)
    log_outbound(sender, "text", "wiz_service_cmd", context_id=context_id)


async def _wiz_service_port(sender: str, text: str, session: dict) -> None:
    context_id = session.get("active_context", "main")
    await handle_service_port(sender, text, session)
    log_outbound(sender, "text", "wiz_service_port", context_id=context_id)


async def _wiz_service_cwd(sender: str, text: str, session: dict) -> None:
    context_id = session.get("active_context", "main")
    await handle_service_cwd(sender, text, session)
    log_outbound(sender, "text", "wiz_service_cwd", context_id=context_id)


async def _wiz_pending_pdf(sender: str, text: str, session: dict) -> None:  # noqa: ARG001
    lang = session.get("lang", "tr")
    context_id = session.get("active_context", "main")
    messenger = get_messenger()
    session.pop("pending_pdf", None)
    await messenger.send_text(sender, t("cmd.pdf_cancelled", lang))
    log_outbound(sender, "text", "pdf_cancelled", context_id=context_id)


# Sıra önemlidir: ilk eşleşen handler çalışır.
_WIZ_REGISTRY: dict[str, Callable[[str, str, dict], Awaitable[None]]] = {
    "awaiting_project_name":        _wiz_project_name,
    "awaiting_project_description": _wiz_project_description,
    "awaiting_arch_edit":           _wiz_arch_edit,
    "awaiting_project_path":        _wiz_project_path,
    "awaiting_service_name":        _wiz_service_name,
    "awaiting_service_cmd":         _wiz_service_cmd,
    "awaiting_service_port":        _wiz_service_port,
    "awaiting_service_cwd":         _wiz_service_cwd,
    "pending_pdf":                  _wiz_pending_pdf,
}


async def _route_text(sender: str, text: str, session: dict) -> None:
    context_id = session.get("active_context", "main")
    lang       = session.get("lang", "tr")
    messenger  = get_messenger()

    # ── Beta modu: sadece /beta yerel, geri kalan HER ŞEY projeye gider ──
    if context_id != "main":
        cmd = text.split()[0].lower() if text.startswith("/") else ""
        if cmd == "/beta":
            command = cmd_registry.get("/beta")
            if command:
                await command.execute(sender, text[len("/beta"):].strip(), session)
            return
        await _forward_to_bridge(sender, text, session)
        return

    # ── TG-WIZ-1: Install wizard text input (free-form: API key, custom TZ, ollama URL) ──
    # Wizard awaiting_text aktifse ve mesaj `/` ile başlamıyorsa wizard yutar.
    # `/` komutları (özellikle /cancel) wizard'ı bypass edebilir.
    if not text.startswith("/"):
        from ..features.install_wizard import handle_install_wizard_text
        if await handle_install_wizard_text(sender, text, lang):
            return

    # ── Ana mod: / ile başlıyorsa yerel komut ──
    cmd = text.split()[0].lower() if text.startswith("/") else ""
    if cmd and session.get("wiz_name"):
        clear_wizard(session)
        await messenger.send_text(sender, t("cmd.wiz_auto_cancelled", lang))
        log_outbound(sender, "text", "wiz_auto_cancel_on_cmd", context_id=context_id)

    if cmd:
        required = get_perm_mgr().required_perm(cmd)

        if required == Perm.OWNER_TOTP:
            if cmd in _MATH_CHALLENGE_CMDS:
                a, b = random.randint(10, 99), random.randint(10, 99)
                session.start_math_challenge(answer=a + b, cmd=text)
                await messenger.send_text(sender, t("auth.math.prompt", lang, cmd=cmd, a=a, b=b))
                log_outbound(sender, "text", f"math_challenge:{cmd}", context_id=context_id)
                return
            session.start_totp(text)
            await messenger.send_text(sender, t("auth.totp.prompt", lang))
            log_outbound(sender, "text", "totp_prompt", context_id=context_id)
            return

        command = cmd_registry.get(cmd)
        if command:
            arg = text[len(cmd):].strip()
            await command.execute(sender, arg, session)
            return

        await messenger.send_text(sender, t("cmd.unknown", lang, cmd=cmd))
        log_outbound(sender, "text", f"unknown_cmd:{cmd}", context_id=context_id)
        return

    # ── Wizard / pending state dispatch (OCP-V2: registry tabanlı) ──────────
    for session_key, handler in _WIZ_REGISTRY.items():
        if session.get(session_key):
            await handler(sender, text, session)
            return

    # Doğal dil → yönetim komutu tespiti
    nl_cmd = await _intent_classifier.classify_admin_intent(text)
    if nl_cmd:
        logger.info("LLM niyet tespiti: '%s' → %s", text[:40], nl_cmd)
        if nl_cmd == "/restart":
            await messenger.send_text(sender, t("cmd.use_restart_instead", lang))
            log_outbound(sender, "text", "redirect:/restart", context_id=context_id)
            return
        if nl_cmd == "/shutdown":
            await messenger.send_text(sender, t("cmd.use_shutdown_instead", lang))
            log_outbound(sender, "text", "redirect:/shutdown", context_id=context_id)
            return
        # /root-reset: güvenlik zinciri gerektirmiyor — doğrudan yönlendir
        await _route_text(sender, nl_cmd, session)
        return

    # Doğal dil → yıkıcı işlem tespiti
    if await _intent_classifier.classify_destructive_intent(text):
        logger.info("Yıkıcı niyet tespit edildi: '%s'", text[:40])
        session.start_guardrail(text)
        await messenger.send_text(sender, t("auth.guardrail.confirm", lang))
        log_outbound(sender, "text", "guardrail_confirm_prompt", context_id=context_id)
        return

    # Düz metin → Bridge
    await _forward_to_bridge(sender, text, session)


async def _forward_to_bridge(sender: str, text: str, session: dict) -> None:
    """Mesajı Claude Code Bridge'e ilet; session kilidini kendisi alır."""
    from . import _bridge_client
    await _bridge_client.forward_locked(sender, text, session)
