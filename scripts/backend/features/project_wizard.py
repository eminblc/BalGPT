"""Proje oluşturma sihirbazı — geriye dönük uyum shim'i.

Implementasyonlar SRP'ye uygun alt modüllere taşındı:
  wizard_core.py  — sabitler, yardımcılar, session temizleme
  wizard_steps.py — adım fonksiyonları (ask_* / handle_* / show_* / confirm_*)
"""
from __future__ import annotations

from .wizard_core import (  # noqa: F401
    cancel_wizard,
    clear_wizard,
)
from .wizard_steps import (  # noqa: F401
    ask_description,
    ask_auto_arch,
    handle_auto_arch_reply,
    ask_arch_edit_input,
    handle_arch_edit_input,
    ask_options,
    handle_options_reply,
    handle_path_keep,
    ask_path_input,
    handle_path_input,
    ask_service_name,
    handle_service_name,
    handle_service_cmd,
    handle_service_port,
    handle_service_cwd,
    show_summary,
    confirm_create,
    handle_edit_summary,
)
