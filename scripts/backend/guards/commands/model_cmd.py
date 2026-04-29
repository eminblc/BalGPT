"""/model komutu — çalışma zamanında LLM modelini değiştir (FEAT-5).

Desteklenen alias'lar (Anthropic backend):
    sonnet → claude-sonnet-4-6
    haiku  → claude-haiku-4-5-20251001
    opus   → claude-opus-4-6

Tam model adı da kabul edilir (ör. /model claude-sonnet-4-6).
Ollama / Gemini backend'lerinde herhangi bir model adı kabul edilir.

Model seçimi global ve servis yeniden başlatılana kadar kalıcıdır.
"""
from .registry import registry
from ..permission import Perm

# Anthropic model alias → tam model adı
_ANTHROPIC_ALIASES: dict[str, str] = {
    "sonnet": "claude-sonnet-4-6",
    "haiku":  "claude-haiku-4-5-20251001",
    "opus":   "claude-opus-4-7",
}

# Anthropic backend için desteklenen tam model adları (alias hedefleri)
_ANTHROPIC_MODELS = list(_ANTHROPIC_ALIASES.values())


class ModelCommand:
    cmd_id      = "/model"
    button_id   = "cmd_model"
    perm        = Perm.OWNER
    label       = "Model Değiştir"
    description = "Çalışma zamanında LLM modelini değiştirir. Global etki, restart'a kadar kalıcı."
    usage       = "/model [model_adı|alias]"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...config import settings
        from ...guards.runtime_state import get_active_model, set_active_model
        from ...i18n import t

        lang = session.get("lang", "tr")
        messenger = get_messenger()
        backend = settings.llm_backend.lower()
        arg = arg.strip().lower()

        current = get_active_model() or settings.default_model

        # Argümansız → Anthropic backend'de butonlu seçim, diğerlerinde metin
        if not arg:
            if backend == "anthropic":
                buttons = []
                for alias, full in _ANTHROPIC_ALIASES.items():
                    marker = " ✓" if full == current else ""
                    buttons.append({
                        "id": f"model_select_{alias}",
                        "title": t(f"model.btn_{alias}", lang) + marker,
                    })
                await messenger.send_buttons(
                    sender,
                    t("model.select_prompt", lang, model=current, backend=backend),
                    buttons,
                )
            else:
                if backend == "ollama":
                    options = t("model.options_ollama", lang)
                elif backend == "gemini":
                    options = t("model.options_gemini", lang)
                else:
                    options = t("model.options_other", lang)
                await messenger.send_text(
                    sender,
                    t("model.current", lang, model=current, backend=backend, options=options),
                )
            return

        # Alias çözümle (yalnızca Anthropic için)
        if backend == "anthropic":
            resolved = _ANTHROPIC_ALIASES.get(arg, arg)
        else:
            resolved = arg  # Ollama / Gemini: kullanıcının girdiği adı aynen kullan

        # Aynı modele geçiş girişimi
        if resolved == current:
            await messenger.send_text(sender, t("model.already_active", lang, model=resolved))
            return

        set_active_model(resolved)

        from ...store.repositories.settings_repo import user_setting_set
        await user_setting_set(sender, "model", resolved)

        await messenger.send_text(sender, t("model.changed", lang, model=resolved))


async def handle_model_select(sender: str, alias: str, session: dict) -> None:
    """Buton callback'i: model_select_{alias} → model değiştir."""
    cmd = ModelCommand()
    await cmd.execute(sender, alias, session)


registry.register(ModelCommand())
