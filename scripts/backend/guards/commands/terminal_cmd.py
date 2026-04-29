"""/terminal komutu — WhatsApp üzerinden shell komutu çalıştır (FEAT-12b).

Güvenlik:
  - Yalnızca owner kullanabilir (Perm.OWNER).
  - Tehlikeli komutlar (is_dangerous → True) owner TOTP gerektirir.
  - Güvenli komutlar doğrudan çalıştırılır.

Tehlikeli komut akışı:
  1. /terminal <tehlikeli_cmd>
  2. Komut _terminal_pending_cmd session key'ine kaydedilir.
  3. session.start_totp(cmd="/terminal") ile onay istenir.
  4. TOTP onaylandıktan sonra handle_totp execute("", session) çağırır.
  5. Boş arg → _terminal_pending_cmd okunur → komut çalıştırılır (is_dangerous yeniden kontrol edilmez).

Not: _terminal_pending_cmd, clear_totp() tarafından iptal/tamamlanmada temizlenir.
"""
from __future__ import annotations

import logging

from .registry import registry
from ..permission import Perm

logger = logging.getLogger(__name__)

# Session key — admin TOTP onayı bekleyen tehlikeli terminal komutu
_SESSION_PENDING_KEY = "_terminal_pending_cmd"


class TerminalCommand:
    cmd_id      = "/terminal"
    perm        = Perm.OWNER
    label       = "Terminal Komutu"
    description = "Shell komutu çalıştır ve çıktıyı WhatsApp'a gönder. Tehlikeli komutlar admin TOTP gerektirir."
    usage       = "/terminal <komut>"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...i18n import t
        from ...features.terminal import is_dangerous

        messenger = get_messenger()
        lang = session.get("lang", "tr")

        # ── Case 1: Boş arg ──────────────────────────────────────────────────
        # Admin TOTP onayı sonrası buraya gelinir: pending key'den komutu al.
        if not arg.strip():
            pending_cmd = session.pop(_SESSION_PENDING_KEY, None)
            if pending_cmd:
                await self._run(sender, pending_cmd, lang, messenger)
            else:
                await messenger.send_text(sender, t("terminal.usage", lang))
            return

        # ── Case 2: Güvenli komut — doğrudan çalıştır ───────────────────────
        if not is_dangerous(arg):
            await self._run(sender, arg, lang, messenger)
            return

        # ── Case 3: Tehlikeli komut — owner TOTP iste ───────────────────────
        # Komutu session'a yaz; pending_command = "/terminal" (arg yok) ile
        # TOTP onaylandığında execute(sender, "", session) çağrılır → Case 1.
        session.set_terminal_pending(arg)
        session.start_totp(cmd="/terminal")
        await messenger.send_text(
            sender,
            t("terminal.dangerous_prompt", lang, cmd=arg[:300]),
        )
        logger.warning(
            "/terminal tehlikeli komut — owner TOTP istendi: sender=%s, cmd=%r",
            sender, arg[:80],
        )

    async def _run(self, sender: str, cmd_str: str, lang: str, messenger) -> None:
        """Komutu çalıştır ve sonucu gönder."""
        from ...features.terminal import execute_command
        from ...i18n import t

        logger.info("/terminal çalıştırılıyor: %r", cmd_str[:80])
        result = await execute_command(cmd_str)

        if result.timed_out:
            text = t("terminal.timeout", lang)
        else:
            output = result.stdout.strip() or t("terminal.empty_output", lang)
            if result.returncode == 0:
                text = t("terminal.success", lang, code=result.returncode, output=output, cwd=result.cwd)
            else:
                text = t("terminal.error", lang, code=result.returncode, output=output, cwd=result.cwd)

        await messenger.send_text(sender, text)


registry.register(TerminalCommand())
