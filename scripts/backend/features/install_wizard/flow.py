"""Install wizard orchestrator — button taps + text input → state advance + UI (SRP).

Public surface:
  is_wizard_callback(reply_id)              — prefix check, pure
  start_or_resume_wizard(chat_id, lang)     — entry; resets state, shows LLM step
  handle_install_wizard_callback(...)       — button tap dispatch
  handle_install_wizard_text(...)           — free-form text dispatch (API key, custom TZ, etc.)

Owner-gating: callers (router) already enforce owner via OwnerPermissionGuard;
defense-in-depth check here as well, refusing if chat_id != settings.owner_id.
"""
from __future__ import annotations

import io
import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from ...adapters.messenger.messenger_factory import get_messenger
from ...config import settings
from ...i18n import t
from ...store.repositories import install_wizard_repo
from . import keyboards
from .env_writer import write_env, delete_keys
from .state_machine import (
    ALL_CAPS,
    PRESET_TIMEZONES,
    initial_state,
    toggle_capability,
)

logger = logging.getLogger(__name__)

_CB_PREFIX = "iw:"

# IANA timezone format: Region/City — letters, digits, _, -, /. Loose validation.
_IANA_TZ_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+\-/]{1,63}$")
_ANTHROPIC_KEY_RE = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,}$")
_GEMINI_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{20,}$")


def is_wizard_callback(reply_id: str) -> bool:
    """True if reply_id is an install-wizard callback (used by interactive router)."""
    return reply_id.startswith(_CB_PREFIX)


def _is_owner(chat_id: str) -> bool:
    return str(chat_id) == str(settings.owner_id)


# ── Public entry points ───────────────────────────────────────────

async def start_or_resume_wizard(chat_id: str, lang: str = "tr") -> None:
    """Reset state and show the LLM step. Called from /wizard or `iw:start`."""
    if not _is_owner(chat_id):
        await get_messenger().send_text(chat_id, t("install_wizard.not_owner", lang))
        return

    state = initial_state()
    await install_wizard_repo.set_state(
        chat_id, state["step"], state["data"], state["awaiting_text"]
    )
    await _render_step(chat_id, "llm", state["data"], lang)


async def handle_install_wizard_callback(chat_id: str, callback_data: str, lang: str = "tr") -> None:
    """Dispatch a button tap. callback_data must start with 'iw:'."""
    if not _is_owner(chat_id):
        await get_messenger().send_text(chat_id, t("install_wizard.not_owner", lang))
        return

    if not callback_data.startswith(_CB_PREFIX):
        return  # not ours
    payload = callback_data[len(_CB_PREFIX):]

    # Welcome → start
    if payload == "start":
        await start_or_resume_wizard(chat_id, lang)
        return

    state = await install_wizard_repo.get_state(chat_id)
    if state is None or state["step"] == "done":
        await get_messenger().send_text(chat_id, t("install_wizard.already_done", lang))
        return

    data = state["data"]

    # Branch by callback prefix
    if payload.startswith("llm:"):
        await _on_llm_choice(chat_id, payload[4:], data, lang)
    elif payload.startswith("auth:"):
        await _on_auth_choice(chat_id, payload[5:], data, lang)
    elif payload.startswith("cap:toggle:"):
        cap = payload[len("cap:toggle:"):]
        if cap in ALL_CAPS:
            toggle_capability(data, cap)
            await install_wizard_repo.set_state(chat_id, "capabilities", data, None)
            await _render_step(chat_id, "capabilities", data, lang)
    elif payload == "cap:done":
        await install_wizard_repo.set_state(chat_id, "timezone", data, None)
        await _render_step(chat_id, "timezone", data, lang)
    elif payload.startswith("tz:"):
        await _on_timezone_choice(chat_id, payload[3:], data, lang)
    else:
        logger.warning("install_wizard: unknown callback %s", callback_data)


async def handle_install_wizard_text(chat_id: str, text: str, lang: str = "tr") -> bool:
    """If wizard is awaiting text input from this chat, consume it.

    Returns True if the message was handled (caller should not pass to bridge).
    Returns False if no wizard text input is pending.
    """
    if not _is_owner(chat_id):
        return False

    state = await install_wizard_repo.get_state(chat_id)
    if state is None or state["awaiting_text"] is None:
        return False

    field = state["awaiting_text"]
    data = state["data"]
    text = text.strip()

    if field == "anthropic_api_key":
        if not _ANTHROPIC_KEY_RE.match(text):
            await get_messenger().send_text(chat_id, t("install_wizard.bad_anthropic_key", lang))
            return True
        data["anthropic_api_key"] = text
        await install_wizard_repo.set_state(chat_id, "capabilities", data, None)
        await _render_step(chat_id, "capabilities", data, lang)
        return True

    if field == "ollama_base_url":
        if not (text.startswith("http://") or text.startswith("https://")):
            await get_messenger().send_text(chat_id, t("install_wizard.bad_url", lang))
            return True
        data["ollama_base_url"] = text
        await install_wizard_repo.set_state(chat_id, "ollama_model", data, "ollama_model")
        await get_messenger().send_text(chat_id, t("install_wizard.ollama_model_prompt", lang))
        return True

    if field == "ollama_model":
        if not text:
            await get_messenger().send_text(chat_id, t("install_wizard.required", lang))
            return True
        data["ollama_model"] = text
        await install_wizard_repo.set_state(chat_id, "capabilities", data, None)
        await _render_step(chat_id, "capabilities", data, lang)
        return True

    if field == "gemini_api_key":
        if not _GEMINI_KEY_RE.match(text):
            await get_messenger().send_text(chat_id, t("install_wizard.bad_gemini_key", lang))
            return True
        data["gemini_api_key"] = text
        await install_wizard_repo.set_state(chat_id, "capabilities", data, None)
        await _render_step(chat_id, "capabilities", data, lang)
        return True

    if field == "timezone":
        if not _IANA_TZ_RE.match(text) or "/" not in text:
            await get_messenger().send_text(chat_id, t("install_wizard.bad_tz", lang))
            return True
        data["timezone"] = text
        await _finalize(chat_id, data, lang)
        return True

    logger.warning("install_wizard: unknown awaiting_text field=%s", field)
    return False


# ── Step transition handlers ──────────────────────────────────────

async def _on_llm_choice(chat_id: str, provider: str, data: dict, lang: str) -> None:
    if provider not in ("anthropic", "ollama", "gemini"):
        return
    data["llm_backend"] = provider
    if provider == "anthropic":
        await install_wizard_repo.set_state(chat_id, "anthropic_auth", data, None)
        await _render_step(chat_id, "anthropic_auth", data, lang)
    elif provider == "ollama":
        await install_wizard_repo.set_state(chat_id, "ollama_url", data, "ollama_base_url")
        await get_messenger().send_text(chat_id, t("install_wizard.ollama_url_prompt", lang))
    elif provider == "gemini":
        await install_wizard_repo.set_state(chat_id, "gemini_key", data, "gemini_api_key")
        await get_messenger().send_text(chat_id, t("install_wizard.gemini_key_prompt", lang))


async def _on_auth_choice(chat_id: str, method: str, data: dict, lang: str) -> None:
    if method not in ("login", "apikey"):
        return
    data["anthropic_auth_method"] = method
    if method == "apikey":
        await install_wizard_repo.set_state(chat_id, "anthropic_key", data, "anthropic_api_key")
        await get_messenger().send_text(chat_id, t("install_wizard.anthropic_key_prompt", lang))
    else:
        # Claude Login chosen — skip key, go straight to capabilities
        await install_wizard_repo.set_state(chat_id, "capabilities", data, None)
        await get_messenger().send_text(chat_id, t("install_wizard.claude_login_note", lang))
        await _render_step(chat_id, "capabilities", data, lang)


async def _on_timezone_choice(chat_id: str, tz: str, data: dict, lang: str) -> None:
    if tz == "other":
        await install_wizard_repo.set_state(chat_id, "timezone_custom", data, "timezone")
        await get_messenger().send_text(chat_id, t("install_wizard.tz_custom_prompt", lang))
        return
    presets = {p[0] for p in PRESET_TIMEZONES}
    if tz not in presets:
        return
    data["timezone"] = tz
    await _finalize(chat_id, data, lang)


# ── Rendering ─────────────────────────────────────────────────────

async def _render_step(chat_id: str, step: str, data: dict, lang: str) -> None:
    messenger = get_messenger()
    if step == "llm":
        text, buttons = keyboards.llm_step(lang)
    elif step == "anthropic_auth":
        text, buttons = keyboards.anthropic_auth_step(lang)
    elif step == "capabilities":
        text, buttons = keyboards.capabilities_step(lang, data.get("capabilities", []))
    elif step == "timezone":
        text, buttons = keyboards.timezone_step(lang)
    else:
        return
    await messenger.send_buttons(chat_id, text, buttons)


# ── Finalization ──────────────────────────────────────────────────

async def _finalize(chat_id: str, data: dict[str, Any], lang: str) -> None:
    """Write .env, send TOTP QR codes, completion message, mark done."""
    messenger = get_messenger()

    # 1. Build env updates from collected data.
    updates, drop_keys = _build_env_updates(data)
    env_path = _resolve_env_path()
    try:
        if drop_keys:
            delete_keys(env_path, drop_keys)
        write_env(env_path, updates)
    except OSError as exc:
        logger.exception("install_wizard: .env write failed: %s", exc)
        await messenger.send_text(chat_id, t("install_wizard.env_write_failed", lang))
        return

    # 2. Send TOTP QR code (best-effort; falls back to text on failure).
    await _send_totp_qr(chat_id, "owner", settings.totp_secret.get_secret_value(), lang)

    # 3. Completion message + restart instruction.
    await messenger.send_text(chat_id, t("install_wizard.done", lang))

    # 4. Mark done (state row preserved for "already complete" detection on re-tap).
    await install_wizard_repo.set_state(chat_id, "done", data, None)


def _resolve_env_path() -> Path:
    """Return scripts/backend/.env path."""
    # 99-root/scripts/backend/features/install_wizard/flow.py → 99-root/scripts/backend/.env
    return Path(__file__).resolve().parent.parent.parent / ".env"


def _build_env_updates(data: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    """Translate wizard data into .env key→value updates.

    Returns:
        (updates, drop_keys) — updates to write, plus keys to delete first
        (e.g. ANTHROPIC_API_KEY when user picks Claude Login).
    """
    updates: dict[str, str] = {}
    drop: list[str] = []

    llm = data.get("llm_backend", "anthropic")
    updates["LLM_BACKEND"] = llm

    if llm == "anthropic":
        if data.get("anthropic_auth_method") == "apikey" and data.get("anthropic_api_key"):
            updates["ANTHROPIC_API_KEY"] = data["anthropic_api_key"]
        else:
            # Claude Login — remove any stale key line so step_claude_auth is triggered
            drop.append("ANTHROPIC_API_KEY")
    elif llm == "ollama":
        updates["OLLAMA_BASE_URL"] = data.get("ollama_base_url", "http://localhost:11434")
        updates["OLLAMA_MODEL"] = data.get("ollama_model", "llama3")
    elif llm == "gemini":
        if data.get("gemini_api_key"):
            updates["GEMINI_API_KEY"] = data["gemini_api_key"]
        updates["GEMINI_MODEL"] = data.get("gemini_model", "gemini-2.0-flash")

    # Timezone
    if "timezone" in data:
        updates["TIMEZONE"] = data["timezone"]

    # Capabilities — RESTRICT_* (selected = false = unrestricted)
    selected = set(data.get("capabilities", []))
    cap_to_env = {
        "fs":                  "RESTRICT_FS_OUTSIDE_ROOT",
        "network":             "RESTRICT_NETWORK",
        "shell":               "RESTRICT_SHELL",
        "service_mgmt":        "RESTRICT_SERVICE_MGMT",
        "media":               "RESTRICT_MEDIA",
        "calendar":            "RESTRICT_CALENDAR",
        "project_wizard":      "RESTRICT_PROJECT_WIZARD",
        "screenshot":          "RESTRICT_SCREENSHOT",
        "scheduler":           "RESTRICT_SCHEDULER",
        "pdf_import":          "RESTRICT_PDF_IMPORT",
        "conv_history":        "RESTRICT_CONV_HISTORY",
        "plans":               "RESTRICT_PLANS",
        "intent_classifier":   "RESTRICT_INTENT_CLASSIFIER",
        "wizard_llm_scaffold": "RESTRICT_WIZARD_LLM_SCAFFOLD",
    }
    for cap, env_key in cap_to_env.items():
        updates[env_key] = "false" if cap in selected else "true"
    # *_ENABLED — direct mapping
    updates["DESKTOP_ENABLED"] = "true" if "desktop" in selected else "false"
    updates["BROWSER_ENABLED"] = "true" if "browser" in selected else "false"

    return updates, drop


async def _send_totp_qr(chat_id: str, label: str, secret: str, lang: str) -> None:
    """Render a TOTP QR PNG and send it; fall back to plain-text secret on failure."""
    messenger = get_messenger()
    if not secret:
        await messenger.send_text(
            chat_id, t("install_wizard.totp_missing", lang, label=label)
        )
        return

    issuer = "BalGPT"
    account = f"{label}@balgpt"
    otpauth_uri = (
        f"otpauth://totp/{issuer}:{account}?secret={secret}&issuer={issuer}"
    )
    caption = t("install_wizard.totp_caption", lang, label=label, secret=secret)

    try:
        png_bytes = _render_qr_png(otpauth_uri)
    except Exception as exc:
        logger.warning("install_wizard: QR render failed: %s", exc)
        await messenger.send_text(chat_id, caption)
        return

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f"totp_{label}_", suffix=".png", delete=False
        ) as fh:
            fh.write(png_bytes)
            tmp_path = Path(fh.name)
        await messenger.send_image(chat_id, str(tmp_path), caption=caption)
    except Exception as exc:
        logger.warning("install_wizard: QR send failed: %s", exc)
        await messenger.send_text(chat_id, caption)
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _render_qr_png(uri: str) -> bytes:
    """Render an otpauth URI to PNG bytes. Raises if qrcode lib is unavailable."""
    import qrcode  # local import — only needed at finalize
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
