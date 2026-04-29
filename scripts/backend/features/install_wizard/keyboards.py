"""Inline keyboard builders for install wizard steps (SRP).

Each public function returns a (text, buttons) tuple. `buttons` matches the
shape consumed by AbstractMessenger.send_buttons(): list of {"id", "title"}.

Callback ID convention (Telegram limit: 64 bytes):
  iw:llm:<provider>            llm:anthropic | llm:ollama | llm:gemini
  iw:auth:<method>             auth:login | auth:apikey
  iw:cap:toggle:<key>          cap:toggle:browser
  iw:cap:done
  iw:tz:<value>                tz:Europe/Istanbul | tz:other
  iw:done                      finalize
  iw:start                     entry button from welcome message
"""
from __future__ import annotations

from typing import Iterable

from ...i18n import t
from .state_machine import ALL_CAPS, PRESET_TIMEZONES


def llm_step(lang: str) -> tuple[str, list[dict]]:
    text = t("install_wizard.llm_prompt", lang)
    return text, [
        {"id": "iw:llm:anthropic", "title": t("install_wizard.llm_anthropic", lang)},
        {"id": "iw:llm:ollama",    "title": t("install_wizard.llm_ollama", lang)},
        {"id": "iw:llm:gemini",    "title": t("install_wizard.llm_gemini", lang)},
    ]


def anthropic_auth_step(lang: str) -> tuple[str, list[dict]]:
    text = t("install_wizard.anthropic_prompt", lang)
    return text, [
        {"id": "iw:auth:login",  "title": t("install_wizard.auth_login", lang)},
        {"id": "iw:auth:apikey", "title": t("install_wizard.auth_apikey", lang)},
    ]


def _cap_label(cap: str, lang: str) -> str:
    """Lookup display label for a cap key under the existing `capability.*` namespace.

    `fs`, `desktop`, `browser` are not in that namespace yet — fall back to
    `install_wizard.cap_<key>` for those.
    """
    # The capability namespace uses "filesystem" for the `fs` key
    aliases = {"fs": "filesystem"}
    primary = f"capability.{aliases.get(cap, cap)}"
    label = t(primary, lang)
    if label != primary:
        return label
    # Fallback for caps not in the original namespace (desktop/browser)
    return t(f"install_wizard.cap_{cap}", lang)


def capabilities_step(lang: str, selected: Iterable[str]) -> tuple[str, list[dict]]:
    selected_set = set(selected)
    text = t("install_wizard.cap_prompt", lang)
    buttons: list[dict] = []
    for cap in ALL_CAPS:
        prefix = "✓ " if cap in selected_set else "☐ "
        label = _cap_label(cap, lang)
        # Truncate to keep callback_data + title under Telegram limits
        title = f"{prefix}{label}"[:64]
        buttons.append({"id": f"iw:cap:toggle:{cap}", "title": title})
    buttons.append({"id": "iw:cap:done", "title": t("install_wizard.cap_done", lang)})
    return text, buttons


def timezone_step(lang: str) -> tuple[str, list[dict]]:
    text = t("install_wizard.tz_prompt", lang)
    buttons = [
        {"id": f"iw:tz:{tz}", "title": label}
        for tz, label in PRESET_TIMEZONES
    ]
    buttons.append({"id": "iw:tz:other", "title": t("install_wizard.tz_other", lang)})
    return text, buttons


def welcome_step(lang: str) -> tuple[str, list[dict]]:
    """Initial greeting with single 'start' button — sent by install.sh post-install ping."""
    text = t("install_wizard.welcome", lang)
    return text, [
        {"id": "iw:start", "title": t("install_wizard.welcome_start", lang)},
    ]
