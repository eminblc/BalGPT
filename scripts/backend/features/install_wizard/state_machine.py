"""Install wizard state transitions — pure logic, no I/O (SRP).

Step graph:
  llm → (anthropic_auth | ollama_url | gemini_key) → capabilities →
    timezone → (timezone_custom?) → totp → done

Each transition is a pure function: (current_state, input) → next_state_dict.
The flow.py orchestrator persists the result via install_wizard_repo and
sends the appropriate UI message.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ── Capability defaults — Telegram path (per project decision) ────
# Confirmed: spec list overrides lib/capabilities.sh defaults for this path.
DEFAULT_CAPS_ENABLED: tuple[str, ...] = (
    "fs", "network", "shell", "service_mgmt",
    "media", "calendar", "project_wizard", "screenshot",
    "scheduler", "pdf_import", "conv_history", "plans",
    "intent_classifier", "wizard_llm_scaffold",
)
# desktop, browser → off by default (need extra X11/headless deps)


@dataclass(frozen=True)
class StepInfo:
    """One step's metadata for the orchestrator."""
    name: str
    awaiting_text: str | None  # None → button-driven; str → key under which to store
    next_step: str | None      # static next; None means transition is data-dependent


# Static parts of the graph. Branching steps (llm/auth/timezone) are resolved
# in flow.py because next-step depends on user choice.
STEPS: dict[str, StepInfo] = {
    "llm":              StepInfo("llm",              None, None),
    "anthropic_auth":   StepInfo("anthropic_auth",   None, None),
    "anthropic_key":    StepInfo("anthropic_key",    "anthropic_api_key", "capabilities"),
    "ollama_url":       StepInfo("ollama_url",       "ollama_base_url",   "ollama_model"),
    "ollama_model":     StepInfo("ollama_model",     "ollama_model",      "capabilities"),
    "gemini_key":       StepInfo("gemini_key",       "gemini_api_key",    "capabilities"),
    "capabilities":     StepInfo("capabilities",     None, "timezone"),
    "timezone":         StepInfo("timezone",         None, None),
    "timezone_custom":  StepInfo("timezone_custom",  "timezone",          "totp"),
    "totp":             StepInfo("totp",             None, "done"),
    "done":             StepInfo("done",             None, None),
}


def initial_state() -> dict[str, Any]:
    """Fresh state — caps default-enabled, no llm yet."""
    return {
        "step": "llm",
        "data": {"capabilities": list(DEFAULT_CAPS_ENABLED)},
        "awaiting_text": None,
    }


def toggle_capability(data: dict[str, Any], cap: str) -> list[str]:
    """Toggle a cap in the selection; return the new list (mutates data)."""
    selected = list(data.get("capabilities", []))
    if cap in selected:
        selected.remove(cap)
    else:
        selected.append(cap)
    data["capabilities"] = selected
    return selected


# Capability list shown in the multi-select UI. Order = display order.
# Must stay in sync with lib/capabilities.sh:cap_keys + enabled_keys.
ALL_CAPS: tuple[str, ...] = (
    "fs", "network", "shell", "service_mgmt",
    "media", "calendar", "project_wizard", "screenshot",
    "scheduler", "pdf_import", "conv_history", "plans",
    "intent_classifier", "wizard_llm_scaffold",
    "desktop", "browser",
)

# Preset timezone choices. "other" → free-form text input.
PRESET_TIMEZONES: tuple[tuple[str, str], ...] = (
    ("Europe/Istanbul",   "🇹🇷 Istanbul"),
    ("Europe/London",     "🇬🇧 London"),
    ("Europe/Paris",      "🇫🇷 Paris"),
    ("America/New_York",  "🇺🇸 New York"),
    ("Asia/Tokyo",        "🇯🇵 Tokyo"),
    ("UTC",               "🌐 UTC"),
)
