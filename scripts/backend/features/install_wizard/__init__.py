"""Install Wizard — Stage-2 Telegram-based setup completion (TG-WIZ-1).

After install.sh finishes the minimal terminal questions (bot token, ngrok),
this package handles the remaining configuration via Telegram inline buttons:
LLM backend, Anthropic auth method, Ollama/Gemini keys, capabilities, timezone,
TOTP QR delivery.

Module split (SRP):
  state_machine.py — pure state transitions; no I/O
  env_writer.py    — atomic .env file mutation, format-compatible with lib/env.sh:_env_set
  keyboards.py     — InlineKeyboardMarkup builders for each step
  flow.py          — orchestrator: handles button taps + text input, persists via repo
"""
from __future__ import annotations

from .flow import (
    handle_install_wizard_callback,
    handle_install_wizard_text,
    is_wizard_callback,
    start_or_resume_wizard,
)

__all__ = [
    "handle_install_wizard_callback",
    "handle_install_wizard_text",
    "is_wizard_callback",
    "start_or_resume_wizard",
]
