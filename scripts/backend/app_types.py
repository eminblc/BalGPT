"""Paylaşılan tip tanımları — tek kaynak (SRP).

Başka modüller bu dosyadan import eder; kendi TypedDict'lerini tanımlamaz.
"""
from __future__ import annotations

from pathlib import Path
from typing import TypedDict

# REFAC-18: tek kaynak — üç farklı modülde tekrarlanan Path(...) hesabı buraya taşındı
_REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent  # 99-root dizini
ACTIVE_CONTEXT_PATH: Path = _REPO_ROOT / "data" / "active_context.json"
DEFAULT_PROJECTS_DIR: Path = _REPO_ROOT.parent / "33-projects"


class SessionState(dict):
    """WhatsApp kullanıcı oturum durumu — OOP-1.

    dict alt sınıfı olduğundan mevcut `session["key"]` / `session.get("key")`
    erişimleri değiştirilmeden çalışır. Ek olarak auth akışı geçişleri için
    invariant-enforcing metotlar sağlar: birden fazla anahtarın birlikte
    güncellenmesi gereken durumlarda bu metotlar kullanılır.

    SOLID-1 — Kapsülleme (ENC-V1):
      Aşağıdaki anahtarlar "controlled" (korumalı) olarak tanımlanmıştır.
      Bu anahtarlara doğrudan `session["key"] = value` ile atama yapmak
      AttributeError fırlatır; bunun yerine karşılık gelen start_*/clear_*
      metotları kullanılmalıdır. Metotların kendisi `dict.__setitem__` ile
      guard'ı atlar — yalnızca dış çağrılar bloklanır.

    Alan dokümantasyonu:
      active_context: str           # "main" | "project:{id}"
      beta_project_id: str | None   # Beta modundaki proje ID'si
      active_project_id: str | None # Ana modda odaklanılan proje ID'si
      awaiting_totp: bool           # TOTP bekleniyor mu
      pending_command: str          # TOTP/math onayı bekleyen komut
      awaiting_math_challenge: bool  # Matematik sorusu yanıtı bekleniyor
      math_challenge_answer: int     # Beklenen cevap
      math_challenge_command: str    # Challenge geçince çalıştırılacak komut
      awaiting_guardrail_confirm: bool  # Tehlikeli eylem onayı bekleniyor
      pending_guardrail_action: str  # Onay bekleyen eylem metni
      pending_bridge_message: str    # Onay sonrası bridge'e gidecek mesaj
      menu_page: int                # Proje listesi sayfa numarası
      last_activity: float          # Unix timestamp
      started_at: float             # Session başlangıç zamanı (özet için)
      pending_pdf: str              # Bekleyen PDF media_id
      awaiting_task: bool           # Görev metni bekleniyor mu
      lang: str                     # Kullanıcı dil tercihi: "tr" | "en" (varsayılan: settings.default_language)
      awaiting_project_name: bool   # Yeni proje adı bekleniyor
      pending_project_name: str     # Scaffold seçimi bekleyen proje adı
      pending_scaffold_source: str  # "manual" | "pdf"
    """

    # SOLID-1: Bu anahtarlar yalnızca start_*/clear_* metotları üzerinden
    # değiştirilebilir; doğrudan `session["key"] = ...` ataması yasaktır.
    _CONTROLLED_KEYS: frozenset[str] = frozenset({
        # Auth state machine
        "awaiting_totp",
        "awaiting_math_challenge",
        "awaiting_guardrail_confirm",
        "pending_guardrail_action",
        # Desktop TOTP gate — server-side flow (DESK-TOTP-2)
        "awaiting_desktop_totp",
        "math_challenge_answer",
        "math_challenge_command",
        "pending_command",
        "pending_bridge_message",
        # UI/wizard entry points
        "awaiting_project_description",
        "awaiting_project_name",
        "awaiting_task",
        "pending_pdf",
        "_terminal_pending_cmd",
        # Wizard step flow-control (SOLID-v2-5)
        "awaiting_project_path",
        "awaiting_service_name",
        "awaiting_service_cmd",
        "awaiting_service_port",
        "awaiting_service_cwd",
        # Wizard value stores (SOLID-v2-5)
        "wiz_name", "wiz_desc", "wiz_level", "wiz_mds", "wiz_path",
        "wiz_svc_decision", "wiz_services",
        "wiz_svc_name", "wiz_svc_cmd", "wiz_svc_port",
        "wiz_pending_level", "wiz_pending_mds", "wiz_pending_svc",
        "wiz_overwrite_confirmed",
        # Wizard LLM scaffold (WIZ-LLM-3) — AI mimari önizlemesi
        "awaiting_arch_edit",
        "wiz_auto_arch",
        "wiz_ai_desc", "wiz_ai_arch", "wiz_ai_stack", "wiz_ai_dirs",
        "wiz_ai_prev_json",
    })

    def __setitem__(self, key: str, value: object) -> None:  # type: ignore[override]
        if key in self._CONTROLLED_KEYS:
            raise AttributeError(
                f"SessionState: '{key}' is controlled — "
                f"use the corresponding start_*/clear_* method instead of direct assignment."
            )
        super().__setitem__(key, value)

    # ── Auth akışı geçiş metotları ────────────────────────────────

    def start_totp(self, cmd: str) -> None:
        """OWNER_TOTP akışını başlat: komutu sakla, TOTP bekle."""
        dict.__setitem__(self, "awaiting_totp", True)
        dict.__setitem__(self, "pending_command", cmd)

    def clear_totp(self) -> None:
        """OWNER_TOTP akışını sonlandır."""
        dict.__setitem__(self, "awaiting_totp", False)
        self.pop("pending_command", None)

    def start_math_challenge(self, answer: int, cmd: str) -> None:
        """Matematik challenge akışını başlat: üç anahtarı atomik olarak yaz."""
        dict.__setitem__(self, "awaiting_math_challenge", True)
        dict.__setitem__(self, "math_challenge_answer", answer)
        dict.__setitem__(self, "math_challenge_command", cmd)

    def clear_math_challenge(self) -> None:
        """Matematik challenge akışını sonlandır."""
        dict.__setitem__(self, "awaiting_math_challenge", False)
        self.pop("math_challenge_answer", None)
        self.pop("math_challenge_command", None)
        self.pop("math_fail_count", None)

    def start_guardrail(self, action: str) -> None:
        """Guardrail onay akışını başlat."""
        dict.__setitem__(self, "awaiting_guardrail_confirm", True)
        dict.__setitem__(self, "pending_guardrail_action", action)

    def clear_guardrail(self) -> None:
        """Guardrail onay akışını sonlandır."""
        dict.__setitem__(self, "awaiting_guardrail_confirm", False)
        self.pop("pending_guardrail_action", None)

    def start_desktop_totp(self) -> None:
        """Desktop TOTP akışını başlat — sunucu kullanıcıdan TOTP bekler."""
        dict.__setitem__(self, "awaiting_desktop_totp", True)

    def clear_desktop_totp(self) -> None:
        """Desktop TOTP akışını sonlandır."""
        dict.__setitem__(self, "awaiting_desktop_totp", False)

    # ── Proje oluşturma sihirbazı geçiş metotları (REFAC-17) ────────────

    def start_project_name(self) -> None:
        """Proje adı bekleme durumunu başlat."""
        dict.__setitem__(self, "awaiting_project_name", True)

    def accept_project_name(self) -> None:
        """Proje adı bekleme durumunu kapat."""
        self.pop("awaiting_project_name", None)

    def start_project_description(self, name: str) -> None:
        """Proje açıklaması bekleme durumunu başlat ve proje adını sakla.

        İki anahtarın birlikte güncellenmesini tek metotta toplar.
        """
        super().__setitem__("wiz_name", name)  # wiz_name kontrolsüz — normal setitem OK
        dict.__setitem__(self, "awaiting_project_description", True)

    def accept_project_description(self, desc: str) -> None:
        """Proje açıklaması bekleme durumunu kapat ve açıklamayı kaydet.

        İki anahtarın birlikte güncellenmesini tek metotta toplar —
        _text_router.py'nin iç anahtar adlarını bilmesini engeller.
        """
        self.pop("awaiting_project_description", None)
        dict.__setitem__(self, "wiz_desc", desc)

    def start_task(self) -> None:
        """Görev metni bekleme durumunu başlat."""
        dict.__setitem__(self, "awaiting_task", True)

    def set_pending_pdf(self, media_id: str) -> None:
        """Bekleyen PDF media_id'sini kaydet."""
        dict.__setitem__(self, "pending_pdf", media_id)

    def set_terminal_pending(self, cmd: str) -> None:
        """Tehlikeli terminal komutunu admin TOTP onayı için sakla."""
        dict.__setitem__(self, "_terminal_pending_cmd", cmd)

    # ── Wizard state geçiş metotları (SOLID-v2-5) ─────────────────────

    # Tüm wizard anahtarları — clear_wizard() tarafından kullanılır
    _WIZARD_KEYS: tuple[str, ...] = (
        "wiz_name", "wiz_desc", "wiz_level", "wiz_mds", "wiz_path",
        "wiz_svc_decision", "wiz_services",
        "wiz_svc_name", "wiz_svc_cmd", "wiz_svc_port",
        "wiz_pending_level", "wiz_pending_mds", "wiz_pending_svc",
        "wiz_overwrite_confirmed",
        "awaiting_project_description",
        "awaiting_project_path",
        "awaiting_service_name", "awaiting_service_cmd",
        "awaiting_service_port", "awaiting_service_cwd",
        "pending_project_name", "pending_project_description",
        "pending_scaffold_source",
        # Wizard LLM scaffold (WIZ-LLM-3)
        "awaiting_arch_edit",
        "wiz_auto_arch",
        "wiz_ai_desc", "wiz_ai_arch", "wiz_ai_stack", "wiz_ai_dirs",
        "wiz_ai_prev_json",
    )

    def clear_wizard(self) -> None:
        """Wizard'a ait tüm session anahtarlarını temizle."""
        for key in self._WIZARD_KEYS:
            self.pop(key, None)

    def is_wizard_active(self) -> bool:
        """Wizard akışı aktif mi? (wiz_name mevcutsa aktif.)"""
        return bool(self.get("wiz_name"))

    def set_wiz(self, key: str, value: object) -> None:
        """Wizard değer alanını kontrollü olarak ata."""
        dict.__setitem__(self, key, value)

    # ── Wizard adım geçişleri ─────────────────────────────────────────

    def start_wizard_path(self) -> None:
        """Proje yolu girişi bekleme durumunu başlat."""
        dict.__setitem__(self, "awaiting_project_path", True)

    def clear_wizard_path(self) -> None:
        """Proje yolu girişi bekleme durumunu kapat."""
        self.pop("awaiting_project_path", None)

    def start_wizard_service_name(self) -> None:
        """Servis adı bekleme durumunu başlat."""
        dict.__setitem__(self, "awaiting_service_name", True)

    def clear_wizard_service_name(self) -> None:
        """Servis adı bekleme durumunu kapat."""
        self.pop("awaiting_service_name", None)

    def start_wizard_service_cmd(self) -> None:
        """Servis komutu bekleme durumunu başlat."""
        dict.__setitem__(self, "awaiting_service_cmd", True)

    def clear_wizard_service_cmd(self) -> None:
        """Servis komutu bekleme durumunu kapat."""
        self.pop("awaiting_service_cmd", None)

    def start_wizard_service_port(self) -> None:
        """Servis port bekleme durumunu başlat."""
        dict.__setitem__(self, "awaiting_service_port", True)

    def clear_wizard_service_port(self) -> None:
        """Servis port bekleme durumunu kapat."""
        self.pop("awaiting_service_port", None)

    def start_wizard_service_cwd(self) -> None:
        """Servis cwd bekleme durumunu başlat."""
        dict.__setitem__(self, "awaiting_service_cwd", True)

    def clear_wizard_service_cwd(self) -> None:
        """Servis cwd bekleme durumunu kapat."""
        self.pop("awaiting_service_cwd", None)

    def set_wizard_options(self, level: str, mds: list, svc_decision: str) -> None:
        """Seçenekler adımı sonuçlarını atomik olarak kaydet."""
        dict.__setitem__(self, "wiz_level", level)
        dict.__setitem__(self, "wiz_mds", mds)
        dict.__setitem__(self, "wiz_svc_decision", svc_decision)

    def set_wizard_overwrite_confirmed(self) -> None:
        """Üzerine yazma onayını işaretle."""
        dict.__setitem__(self, "wiz_overwrite_confirmed", True)

    def add_wizard_service(self, svc: dict) -> None:
        """Servis listesine yeni servis ekle."""
        services = self.get("wiz_services")
        if not services:
            services = []
            dict.__setitem__(self, "wiz_services", services)
        services.append(svc)

    def set_wizard_pending_options(
        self, level: str, mds_key: str, svc: str,
    ) -> None:
        """Düzenleme modunda pending seçimleri geri yükle."""
        dict.__setitem__(self, "wiz_pending_level", level)
        dict.__setitem__(self, "wiz_pending_mds", mds_key)
        dict.__setitem__(self, "wiz_pending_svc", svc)

    # ── Wizard LLM scaffold (WIZ-LLM-3) ───────────────────────────────

    def set_wizard_auto_arch_choice(self, choice: str) -> None:
        """Auto-arch kullanıcı kararını kaydet ("yes" | "no")."""
        dict.__setitem__(self, "wiz_auto_arch", choice)

    def set_wizard_ai_arch(
        self,
        ai_desc: str,
        ai_arch: str,
        ai_stack: list,
        ai_dirs: list,
        prev_json: dict,
    ) -> None:
        """AI mimari önizlemesini atomik olarak kaydet (ilk üretim / regenerate)."""
        dict.__setitem__(self, "wiz_ai_desc", ai_desc)
        dict.__setitem__(self, "wiz_ai_arch", ai_arch)
        dict.__setitem__(self, "wiz_ai_stack", ai_stack)
        dict.__setitem__(self, "wiz_ai_dirs", ai_dirs)
        dict.__setitem__(self, "wiz_ai_prev_json", prev_json)

    def start_wizard_arch_edit(self) -> None:
        """AI mimari düzenleme metni bekleme durumunu başlat."""
        dict.__setitem__(self, "awaiting_arch_edit", True)

    def clear_wizard_arch_edit(self) -> None:
        """AI mimari düzenleme metni bekleme durumunu kapat."""
        self.pop("awaiting_arch_edit", None)


# REF-8: tek kaynak proje durum emojisi — menu.py ve projects.py paylaşır
PROJECT_STATUS_EMOJI: dict[str, str] = {
    "idle":    "⚪",
    "running": "🟢",
    "stopped": "🔴",
    "beta":    "🔀",
}


class InboundMessage(TypedDict, total=False):
    """Platform-bağımsız gelen mesaj payload'ı — REFAC-19.

    handle_common_message'ın keyword parametrelerini tek TypedDict'te toplar.
    total=False: tüm alanlar isteğe bağlı; her platform kullanmadığı alanları atlayabilir.

    Kullanım:
        from ..app_types import InboundMessage
        msg = InboundMessage(text="merhaba", reply_id="", extra_desc="", raw_payload=None)
        await handle_common_message(sender, msg_id, msg_type, session, msg)
    """
    text:        str
    reply_id:    str
    extra_desc:  str
    raw_payload: dict | None


class ProjectMeta(TypedDict):
    """Proje metadata (SQLite projects tablosundan)."""
    id: str
    name: str
    description: str
    status: str          # idle | running | stopped | beta
    path: str
    created_at: float
    updated_at: float
    source_pdf: str | None


class WorkPlan(TypedDict):
    """İş planı."""
    id: str
    title: str
    description: str
    status: str          # active | completed | cancelled
    priority: int        # 1=high 2=medium 3=low
    due_date: float | None
    created_at: float
    project_id: str | None


class CalendarEvent(TypedDict):
    """Takvim etkinliği."""
    id: str
    title: str
    description: str
    event_time: float
    remind_before_minutes: int
    recurring: str | None
    notified: bool
    created_at: float


class ScheduledTask(TypedDict):
    """Zamanlanmış görev."""
    id: str
    description: str
    cron_expr: str | None
    next_run: float | None
    active: bool
    action_type: str     # "send_message" | "run_bridge"
    action_payload: dict
