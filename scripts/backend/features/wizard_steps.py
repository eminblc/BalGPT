"""Proje wizard adım fonksiyonları — ask_* / handle_* / show_* / confirm_* (SRP).

Paylaşılan sabitler, yardımcılar ve session temizleme: wizard_core.py
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .wizard_core import (
    _DEFAULT_LEVEL,
    _DEFAULT_MDS,
    _DEFAULT_SVC,
    _MDS_MAP,
    _REVERSE_MDS_MAP,
    _default_project_path,
    _options_sections,
    clear_wizard,
    get_level_label,
)
from .wizard_validator import WizardValidator
from ..i18n import t

logger = logging.getLogger(__name__)


# ── Adım 2: Açıklama ─────────────────────────────────────────────────

async def ask_description(sender: str, name: str, session: dict) -> None:
    """Ad alındı → genel amaç sor."""
    from ..adapters.messenger import get_messenger
    lang = session.get("lang", "tr")
    session.start_project_description(name)
    await get_messenger().send_text(
        sender,
        t("wizard.ask_description", lang, name=name),
    )


# ── Adım 2.5: AI mimari önizlemesi (WIZ-LLM-3) ───────────────────────

async def ask_auto_arch(sender: str, session: dict) -> None:
    """Amaç alındıktan sonra: AI mimari önerisi ister misin? sor.

    `settings.restrict_wizard_llm_scaffold=True` ise adımı sessizce atla ve
    doğrudan seçenekler menüsüne geç. Böylece kısıtlama aktifken akış bozulmaz.
    """
    from ..adapters.messenger import get_messenger
    from ..config import settings

    lang = session.get("lang", "tr")
    # WIZ-LLM-6 bu kısıtlamayı CapabilityGuard'a bağlayacak; şimdilik settings flag'i.
    if getattr(settings, "restrict_wizard_llm_scaffold", False):
        session.set_wizard_auto_arch_choice("no")
        await ask_options(sender, session)
        return

    name = session.get("wiz_name", "")
    await get_messenger().send_buttons(
        sender,
        t("wizard.ask_auto_arch", lang, name=name),
        [
            {"id": "wiz_auto_arch_yes", "title": t("wizard.auto_arch_yes_btn", lang)},
            {"id": "wiz_auto_arch_no",  "title": t("wizard.auto_arch_no_btn", lang)},
        ],
    )


async def handle_auto_arch_reply(sender: str, reply_id: str, session: dict) -> None:
    """wiz_auto_arch_yes / wiz_auto_arch_no butonlarını işle."""
    from ..adapters.messenger import get_messenger
    lang = session.get("lang", "tr")

    if reply_id == "wiz_auto_arch_no":
        session.set_wizard_auto_arch_choice("no")
        await ask_options(sender, session)
        return

    if reply_id == "wiz_auto_arch_yes":
        session.set_wizard_auto_arch_choice("yes")
        await get_messenger().send_text(sender, t("wizard.arch_generating", lang))

        name = session.get("wiz_name", "")
        desc = session.get("wiz_desc", "")

        from .wizard_llm_scaffold import generate_arch_preview
        preview = await generate_arch_preview(name=name, desc=desc, lang=lang)

        if preview is None:
            await get_messenger().send_text(sender, t("wizard.arch_failed", lang))
            await ask_options(sender, session)
            return

        session.set_wizard_ai_arch(
            ai_desc=preview["description"],
            ai_arch=preview["architecture"],
            ai_stack=list(preview["stack"]),
            ai_dirs=list(preview["directories"]),
            prev_json=dict(preview),
        )
        await show_arch_preview(sender, session)


async def show_arch_preview(sender: str, session: dict) -> None:
    """Üretilen AI önizlemesini göster + kabul/düzenle/atla butonları."""
    from ..adapters.messenger import get_messenger
    lang = session.get("lang", "tr")

    ai_desc  = session.get("wiz_ai_desc",  "")
    ai_arch  = session.get("wiz_ai_arch",  "")
    ai_stack = session.get("wiz_ai_stack", []) or []
    ai_dirs  = session.get("wiz_ai_dirs",  []) or []

    stack_label = ", ".join(ai_stack) if ai_stack else t("wizard.none_label", lang)
    dirs_label  = "\n".join(f"  • {d}" for d in ai_dirs) if ai_dirs else "  —"

    msg = t(
        "wizard.arch_preview", lang,
        desc=ai_desc,
        stack=stack_label,
        directories=dirs_label,
        architecture=ai_arch,
    )
    await get_messenger().send_buttons(
        sender,
        msg,
        [
            {"id": "wiz_arch_accept", "title": t("wizard.arch_accept_btn", lang)},
            {"id": "wiz_arch_edit",   "title": t("wizard.arch_edit_btn", lang)},
            {"id": "wiz_arch_skip",   "title": t("wizard.arch_skip_btn", lang)},
        ],
    )


async def ask_arch_edit_input(sender: str, session: dict) -> None:
    """AI önizlemesi için kullanıcı düzenleme metni iste."""
    from ..adapters.messenger import get_messenger
    lang = session.get("lang", "tr")
    session.start_wizard_arch_edit()
    await get_messenger().send_text(sender, t("wizard.arch_edit_prompt", lang))


async def handle_arch_edit_input(sender: str, text: str, session: dict) -> None:
    """Kullanıcı düzenleme metni geldi → regenerate → preview göster.

    Boş metinde prompt'u tekrar gönderir. LLM başarısız olursa mevcut önizlemeyi
    yeniden gösterir (prev_json korunur) — kullanıcı tekrar deneyebilir veya
    `wiz_arch_accept/skip` basabilir.
    """
    from ..adapters.messenger import get_messenger
    lang = session.get("lang", "tr")

    feedback = text.strip()
    if not feedback:
        # Boş yanıt — bekleme durumunu koru, prompt tekrar
        await get_messenger().send_text(sender, t("wizard.arch_edit_prompt", lang))
        return

    session.clear_wizard_arch_edit()
    await get_messenger().send_text(sender, t("wizard.arch_regenerating", lang))

    name = session.get("wiz_name", "")
    desc = session.get("wiz_desc", "")
    prev = session.get("wiz_ai_prev_json") or {}

    from .wizard_llm_scaffold import regenerate_arch_preview
    preview = await regenerate_arch_preview(
        name=name,
        desc=desc,
        lang=lang,
        prev_json=prev,
        user_feedback=feedback,
    )

    if preview is None:
        await get_messenger().send_text(sender, t("wizard.arch_failed", lang))
        await show_arch_preview(sender, session)
        return

    session.set_wizard_ai_arch(
        ai_desc=preview["description"],
        ai_arch=preview["architecture"],
        ai_stack=list(preview["stack"]),
        ai_dirs=list(preview["directories"]),
        prev_json=dict(preview),
    )
    await show_arch_preview(sender, session)


# ── Adım 3: Seçenekler ───────────────────────────────────────────────

async def ask_options(sender: str, session: dict) -> None:
    """Birleşik seçenekler menüsünü göster (adım 3)."""
    from ..adapters.messenger import get_messenger
    # AI wizard ile önizleme kabul edildiyse CLAUDE.md+README zorunlu gelir → önceden seç
    has_ai = session.get("wiz_auto_arch") == "yes" and session.get("wiz_ai_prev_json")
    default_mds = "claude_readme" if has_ai else _DEFAULT_MDS
    session.setdefault("wiz_pending_level", _DEFAULT_LEVEL)
    session.setdefault("wiz_pending_mds",   default_mds)
    session.setdefault("wiz_pending_svc",   _DEFAULT_SVC)

    lang = session.get("lang", "tr")
    name = session.get("wiz_name", "Proje")
    await get_messenger().send_list(
        sender,
        t("wizard.options_title", lang, name=name),
        _options_sections(session),
    )


async def handle_options_reply(sender: str, reply_id: str, session: dict) -> None:
    """wiz_opt_* ve wiz_options_confirm seçimlerini işle."""
    if reply_id.startswith("wiz_opt_level_"):
        session.set_wiz("wiz_pending_level", reply_id[len("wiz_opt_level_"):])
        await ask_options(sender, session)

    elif reply_id.startswith("wiz_opt_mds_"):
        session.set_wiz("wiz_pending_mds", reply_id[len("wiz_opt_mds_"):])
        await ask_options(sender, session)

    elif reply_id.startswith("wiz_opt_svc_"):
        session.set_wiz("wiz_pending_svc", reply_id[len("wiz_opt_svc_"):])
        await ask_options(sender, session)

    elif reply_id == "wiz_options_confirm":
        await _finalize_options(sender, session)


async def _finalize_options(sender: str, session: dict) -> None:
    """Seçimleri session'a aktar → yol onayına yönlendir."""
    level   = session.pop("wiz_pending_level", _DEFAULT_LEVEL)
    mds_key = session.pop("wiz_pending_mds",   _DEFAULT_MDS)
    svc     = session.pop("wiz_pending_svc",   _DEFAULT_SVC)

    session.set_wizard_options(level, _MDS_MAP.get(mds_key, []), svc)

    await _ask_path_confirm(sender, session)


# ── Adım 4: Proje yolu ───────────────────────────────────────────────

async def _ask_path_confirm(sender: str, session: dict) -> None:
    """Varsayılan proje yolunu göster, değiştirmek isteyip istemediğini sor."""
    from ..adapters.messenger import get_messenger
    lang         = session.get("lang", "tr")
    name         = session.get("wiz_name", "")
    default_path = _default_project_path(name)
    session.set_wiz("wiz_path", default_path)  # default olarak kaydet

    await get_messenger().send_buttons(
        sender,
        t("wizard.path_confirm", lang, path=default_path),
        [
            {"id": "wiz_path_keep",   "title": t("wizard.path_keep_btn", lang)},
            {"id": "wiz_path_change", "title": t("wizard.path_change_btn", lang)},
        ],
    )


async def handle_path_keep(sender: str, session: dict) -> None:
    """Yol onaylandı → servis veya özete geç."""
    await _proceed_after_path(sender, session)


async def ask_path_input(sender: str, session: dict) -> None:
    """Özel yol girişi başlat."""
    from ..adapters.messenger import get_messenger
    lang = session.get("lang", "tr")
    session.start_wizard_path()
    current = session.get("wiz_path", "")
    await get_messenger().send_text(
        sender,
        t("wizard.path_input_prompt", lang, current=current),
    )


async def handle_path_input(sender: str, text: str, session: dict) -> None:
    """Özel yol alındı → doğrula, servis veya özete geç."""
    from ..adapters.messenger import get_messenger
    session.clear_wizard_path()
    stripped = text.strip()

    lang = session.get("lang", "tr")
    if stripped and stripped != "-":
        err = WizardValidator.validate_path(stripped)
        if err == "not_absolute":
            session.start_wizard_path()
            await get_messenger().send_text(sender, t("wizard.path_absolute_required", lang))
            return
        if err == "traversal":
            session.start_wizard_path()
            await get_messenger().send_text(sender, t("wizard.path_traversal_error", lang))
            return
        if err == "unsafe_prefix":
            session.start_wizard_path()
            await get_messenger().send_text(sender, t("wizard.path_unsafe_prefix", lang))
            return
        session.set_wiz("wiz_path", stripped)

    await _proceed_after_path(sender, session)


async def _proceed_after_path(sender: str, session: dict) -> None:
    """Yol adımı tamamlandı: servis kararına göre yönlendir.

    wiz_svc_decision'ı pop ederek ikinci kez çalışmayı önler (S-4: çift basış koruması).
    Karar zaten tüketilmişse (key yok) session'ın ilerlediği varsayılır → özete geç.
    """
    svc = session.pop("wiz_svc_decision", None)
    if svc is None:
        # Karar daha önce tüketildi (çift basış) → zaten yönlendirildi, sessizce dön
        logger.debug("_proceed_after_path: wiz_svc_decision yok, çift basış atlandı")
        return
    if svc == "yes":
        await ask_service_name(sender, session)
    else:
        await show_summary(sender, session)


# ── Adım 5-6: Servis akışı ───────────────────────────────────────────

async def ask_service_name(sender: str, session: dict) -> None:
    """Servis akışı başlat — servis adını sor.

    WIZ-UX-2: İlk servis için (count == 0) önce `service_intro` bilgilendirme
    mesajı gönder (ad/komut/port/cwd ne anlama geliyor); sonra isim prompt'una geç.
    """
    from ..adapters.messenger import get_messenger
    lang = session.get("lang", "tr")
    session.start_wizard_service_name()
    existing = len(session.get("wiz_services", []))
    messenger = get_messenger()
    if existing == 0:
        await messenger.send_text(sender, t("wizard.service_intro", lang))
    count = existing + 1
    await messenger.send_text(
        sender,
        t("wizard.service_name_prompt", lang, count=count),
    )


async def handle_service_name(sender: str, text: str, session: dict) -> None:
    """Servis adı alındı → WIZ-B7 validasyonu, komut sor."""
    from ..adapters.messenger import get_messenger
    name = text.strip()

    lang = session.get("lang", "tr")
    if WizardValidator.validate_service_name(name) is not None:
        session.start_wizard_service_name()
        await get_messenger().send_text(sender, t("wizard.service_name_invalid", lang))
        return

    session.clear_wizard_service_name()
    session.set_wiz("wiz_svc_name", name)
    session.start_wizard_service_cmd()
    await get_messenger().send_text(
        sender,
        t("wizard.service_cmd_prompt", lang, name=name),
    )


async def handle_service_cmd(sender: str, text: str, session: dict) -> None:
    """Komut alındı → güvenlik kontrolü, port çıkar veya sor."""
    from ..adapters.messenger import get_messenger
    stripped = text.strip()

    lang = session.get("lang", "tr")
    # Erken güvenlik kontrolü — wizard adımında reddet (O-1)
    if WizardValidator.validate_service_cmd(stripped) is not None:
        session.start_wizard_service_cmd()
        await get_messenger().send_text(sender, t("wizard.service_cmd_unsafe", lang))
        return

    session.clear_wizard_service_cmd()
    session.set_wiz("wiz_svc_cmd", stripped)
    port = WizardValidator.extract_port(text)
    if port:
        session.set_wiz("wiz_svc_port", port)
        await _ask_service_cwd(sender, session)
    else:
        session.start_wizard_service_port()
        await get_messenger().send_text(sender, t("wizard.service_port_prompt", lang))


async def handle_service_port(sender: str, text: str, session: dict) -> None:
    """Port alındı → WIZ-B6 aralık kontrolü, cwd sor."""
    from ..adapters.messenger import get_messenger
    port = text.strip()

    lang = session.get("lang", "tr")
    if WizardValidator.validate_port(port) is not None:
        session.start_wizard_service_port()
        await get_messenger().send_text(sender, t("wizard.service_port_invalid", lang))
        return

    session.clear_wizard_service_port()
    session.set_wiz("wiz_svc_port", "" if port == "-" else port)
    await _ask_service_cwd(sender, session)


async def _ask_service_cwd(sender: str, session: dict) -> None:
    from ..adapters.messenger import get_messenger
    lang = session.get("lang", "tr")
    session.start_wizard_service_cwd()
    await get_messenger().send_text(
        sender,
        t("wizard.service_cwd_prompt", lang),
    )


async def handle_service_cwd(sender: str, text: str, session: dict) -> None:
    """cwd alındı → servisi listeye ekle, başka servis sor."""
    from ..adapters.messenger import get_messenger
    session.clear_wizard_service_cwd()
    cwd = text.strip()
    cwd = "" if cwd in ("-", "") else cwd

    name = session.pop("wiz_svc_name", "servis")
    cmd  = session.pop("wiz_svc_cmd",  "")
    port = session.pop("wiz_svc_port", "")

    svc: dict = {"name": name, "tmux_window": name, "cmd": cmd, "cwd": cwd}
    if port:
        try:
            svc["port"] = int(port)
        except ValueError:
            pass

    session.add_wizard_service(svc)

    lang = session.get("lang", "tr")
    await get_messenger().send_buttons(
        sender,
        t("wizard.service_added", lang, name=name),
        [
            {"id": "wiz_service_more",  "title": t("wizard.add_service_btn", lang)},
            {"id": "wiz_show_summary",  "title": t("wizard.summary_btn", lang)},
        ],
    )


# ── Adım 7-8: Özet ve onay ───────────────────────────────────────────

async def show_summary(sender: str, session: dict) -> None:
    """Özet mesajı göster + onayla."""
    from ..adapters.messenger import get_messenger
    lang     = session.get("lang", "tr")
    name     = session.get("wiz_name",  "?")
    desc     = session.get("wiz_desc",  "") or "—"
    level    = session.get("wiz_level", "full")
    mds      = session.get("wiz_mds",   [])
    path     = session.get("wiz_path",  _default_project_path(name))
    services = session.get("wiz_services", [])

    level_label = get_level_label(level, lang)
    mds_label   = ", ".join(mds) if mds else t("wizard.none_label", lang)

    if session.get("wiz_auto_arch") == "yes" and session.get("wiz_ai_prev_json"):
        mds_label += "\n" + t("wizard.ai_forced_mds", lang)

    svc_lines = ""
    for svc in services:
        port_str = f":{svc['port']}" if svc.get("port") else ""
        cwd_str  = f" ({svc['cwd']})" if svc.get("cwd") else ""
        svc_lines += f"\n  • {svc['name']}{port_str}: `{svc['cmd']}`{cwd_str}"

    svc_label = svc_lines if svc_lines else f"\n  {t('wizard.no_services', lang)}"

    msg = t("wizard.summary", lang,
            name=name, desc=desc, level=level_label,
            mds=mds_label, path=path, services=svc_label)
    await get_messenger().send_buttons(
        sender,
        msg,
        [
            {"id": "wiz_confirm",      "title": t("wizard.create_btn", lang)},
            {"id": "wiz_edit_options", "title": t("wizard.edit_btn", lang)},
            {"id": "wiz_cancel",       "title": t("wizard.cancel_btn", lang)},
        ],
    )


async def confirm_create(sender: str, session: dict) -> None:
    """Onaylandı → projeyi oluştur."""
    from ..adapters.messenger import get_messenger
    from .projects import create_project

    name        = session.get("wiz_name",     "")
    desc        = session.get("wiz_desc",     "")
    level       = session.get("wiz_level",    "full")
    mds         = session.get("wiz_mds",      None)
    custom_path = session.get("wiz_path",     None)
    services    = session.get("wiz_services", [])

    # WIZ-LLM-5: AI önizlemesi kabul edildiyse override dict'i kur.
    ai_overrides: dict | None = None
    if session.get("wiz_auto_arch") == "yes" and session.get("wiz_ai_prev_json"):
        ai_overrides = {
            "stack":        list(session.get("wiz_ai_stack", []) or []),
            "directories":  list(session.get("wiz_ai_dirs",  []) or []),
            "architecture": session.get("wiz_ai_arch", "") or "",
        }

    metadata = json.dumps({"services": services}, ensure_ascii=False) if services else "{}"

    lang = session.get("lang", "tr")
    # Hedef dizin zaten varsa uyar — kullanıcı zaten onayladıysa atla (O-2)
    target_path = Path(custom_path) if custom_path else Path(_default_project_path(name))
    if not session.pop("wiz_overwrite_confirmed", False):
        if target_path.exists() and any(target_path.iterdir()):
            # Dizin var ve boş değil → session'ı koruyarak uyar, kullanıcıya karar ver
            await get_messenger().send_buttons(
                sender,
                t("wizard.overwrite_confirm", lang, path=str(target_path)),
                [
                    {"id": "wiz_confirm_overwrite", "title": t("wizard.overwrite_yes_btn", lang)},
                    {"id": "wiz_cancel",            "title": t("wizard.cancel_btn", lang)},
                ],
            )
            return

    await get_messenger().send_text(sender, t("wizard.creating", lang))
    try:
        project = await create_project(
            name, desc, level=level, mds=mds, metadata=metadata, path=custom_path,
            ai_overrides=ai_overrides,
        )
    except ValueError as exc:
        clear_wizard(session)
        msg = str(exc)
        if "zaten mevcut" in msg:
            await get_messenger().send_text(
                sender,
                t("wizard.duplicate_name", lang, name=name),
            )
            logger.warning("Wizard: duplicate proje adı reddedildi: %s", name)
        else:
            await get_messenger().send_text(
                sender,
                t("wizard.create_failed", lang, error=exc),
            )
            logger.warning("Wizard: geçersiz proje adı: %s — %s", name, exc)
        return
    except PermissionError:
        clear_wizard(session)
        await get_messenger().send_text(
            sender,
            t("wizard.permission_error", lang, path=custom_path),
        )
        logger.error("Wizard: dizin izin hatası: path=%s", custom_path)
        return
    except Exception as exc:
        clear_wizard(session)
        await get_messenger().send_text(
            sender,
            t("wizard.unexpected_error", lang),
        )
        logger.exception("Wizard: proje oluşturma hatası: name=%s exc=%s", name, exc)
        return

    level_label = get_level_label(level, lang)
    svc_note = t("wizard.svc_count", lang, count=len(services)) if services else ""

    await get_messenger().send_text(
        sender,
        t("wizard.created", lang, name=project["name"], level=level_label, path=project["path"], svc_note=svc_note),
    )
    clear_wizard(session)
    logger.info("Wizard tamamlandı: %s", project["id"])


async def handle_edit_summary(sender: str, session: dict) -> None:
    """Özet ekranındaki 'Düzenle' butonu — seçenekler menüsüne geri döndür (WIZ-UX1).

    Mevcut wiz_level / wiz_mds / wiz_services değerlerini wiz_pending_* olarak geri yükler,
    ardından yol ve servis adımlarının yeniden doldurulabilmesi için onları temizler.
    """
    level = session.get("wiz_level", _DEFAULT_LEVEL)
    current_mds = session.get("wiz_mds", [])
    mds_key = _REVERSE_MDS_MAP.get(str(sorted(current_mds)), "none")
    svc = "yes" if session.get("wiz_services") else "no"
    session.set_wizard_pending_options(level, mds_key, svc)

    # Yol ve servis adımlarını sıfırla — kullanıcı tekrar geçecek
    for key in ("wiz_level", "wiz_mds", "wiz_path", "wiz_services", "wiz_svc_decision"):
        session.pop(key, None)

    await ask_options(sender, session)
