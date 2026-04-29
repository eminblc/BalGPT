"""Wizard LLM Scaffold — proje açıklamasından mimari önizlemesi üretir (WIZ-LLM-1).

SOLID ayrımı (CLAUDE.md "Kod Kalitesi — OOP ve SOLID" kuralı):
    - `ArchPromptBuilder`         (SRP) — prompt string oluşturur
    - `ArchResponseExtractor`     (SRP) — ham LLM yanıtından JSON bloğu çıkarır
    - `ArchSchemaSanitizer`       (SRP) — parse edilmiş sözlüğü whitelist + tip + boyut ile temizler
    - `WizardLLMConfig`           (SRP) — backend-bazlı model + API anahtarı çözümleme
    - `WizardLLMScaffoldService`  (DIP) — yukarıdakileri constructor-injection ile birleştiren
                                           orkestratör

Kamuya açık kontrat (geri uyumluluk + mevcut testler):
    - `build_arch_prompt`, `sanitize_arch_dict`, `_extract_json_block`
    - `generate_arch_preview`, `regenerate_arch_preview`
    - modül-seviye `settings`, `get_llm`, `_LLM_TIMEOUT_SECONDS` —
      `patch.object(mod, ...)` ile testlerde değiştirilebilir.
      `_build_service()` her çağrıda bu isimleri yeniden okur.

Hata toleransı:
    - 60 sn `asyncio.wait_for` timeout
    - API anahtarı yok / timeout / JSON parse / şema fail → `None`
    - Çağıran taraf `None` dönüşünde statik şablona düşer (WIZ-LLM-5)

Güvenlik:
    - K56 (JSON bomb): alan boyutlarına sert limit
    - K58 (eval/exec yasağı): `json.loads` dışında kod çalıştırma yok
    - K38 (bağlam zehirlenmesi): yanıttan yalnızca whitelist alanlar kabul edilir
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any, Callable

import httpx

from ..adapters.llm.llm_factory import get_llm
from ..adapters.llm.result import CompletionResult
from ..config import settings
from ..store.repositories import token_stat_repo

logger = logging.getLogger(__name__)

# ── Sabitler ─────────────────────────────────────────────────────────

_LLM_TIMEOUT_SECONDS: float = 60.0
_LLM_MAX_TOKENS: int = 2048

# JSON bomb ve kaynak tükenmesi koruması (KATEGORİ 56)
_MAX_DESCRIPTION_LEN: int = 2000
_MAX_ARCHITECTURE_LEN: int = 4000
_MAX_STACK_ITEMS: int = 30
_MAX_DIRECTORIES_ITEMS: int = 50
_MAX_FIELD_STR_LEN: int = 200  # stack / directories tek eleman üst sınırı

_ALLOWED_KEYS: frozenset[str] = frozenset(
    {"description", "stack", "directories", "architecture"}
)

# JSON bloğu çıkarma — markdown code fence veya ham {...} destekler
_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


# ══════════════════════════════════════════════════════════════════════
# SRP — Prompt kurulumu
# ══════════════════════════════════════════════════════════════════════


class ArchPromptBuilder:
    """Proje adı + amaç (+ opsiyonel prev/feedback) → LLM prompt string.

    Yalnızca metin inşasından sorumludur; LLM çağırmaz, JSON parse etmez,
    şema doğrulamaz. Durumsuzdur; her çağrı bağımsız.
    """

    @staticmethod
    def _language_label(lang: str) -> str:
        return "Türkçe" if lang == "tr" else "English"

    def build(
        self,
        name: str,
        desc: str,
        lang: str,
        prev_json: dict | None = None,
        user_feedback: str | None = None,
    ) -> str:
        """Wizard mimari önizlemesi için LLM prompt üretir.

        `prev_json` + `user_feedback` ikisi de verilirse regenerate modudur;
        aksi halde ilk üretim modudur. Her iki mod aynı JSON şemasını zorunlu kılar.
        """
        lang_label = self._language_label(lang)

        schema_block = (
            "Yanıtı SADECE geçerli bir JSON nesnesi olarak ver. Açıklama veya kod "
            "bloğu işaretleyicisi ekleme. Şema:\n"
            "{\n"
            '  "description": "<string — 3-5 cümle, projeyi genişletilmiş açıklama>",\n'
            '  "stack":       ["<string>", "..."],   // teknoloji listesi, max 30\n'
            '  "directories": ["<string>", "..."],   // göreli klasör yolları, max 50\n'
            '  "architecture": "<string — markdown paragraf veya madde listesi>"\n'
            "}\n"
            "Tüm alanlar zorunludur. Değerleri yanıtın dili: "
            f"{lang_label}."
        )

        header = (
            f"Sen bir kişisel yazılım proje mimarısın. Kullanıcının verdiği proje adı ve "
            f"amacından yola çıkarak öneri üret.\n\n"
            f"Proje adı: {name}\n"
            f"Amaç: {desc}\n"
        )

        if prev_json is not None and user_feedback is not None:
            # Regenerate modu
            try:
                prev_repr = json.dumps(prev_json, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                prev_repr = str(prev_json)
            return (
                header
                + "\nÖnceki öneri:\n"
                + prev_repr
                + "\n\nKullanıcı düzeltme isteği:\n"
                + user_feedback
                + "\n\nKullanıcının isteğini dikkate alarak güncellenmiş bir JSON üret.\n"
                + schema_block
            )

        # İlk üretim modu
        return (
            header
            + "\nProjenin mantığına uygun bir teknoloji yığını (stack), klasör yapısı "
              "(directories) ve kısa bir mimari açıklaması (architecture) öner. "
              "description alanı amaçı 3-5 cümleyle genişletmeli.\n\n"
            + schema_block
        )


# ══════════════════════════════════════════════════════════════════════
# SRP — Yanıttan JSON bloğu çıkarma
# ══════════════════════════════════════════════════════════════════════


class ArchResponseExtractor:
    """Ham LLM yanıtından JSON nesne bloğunu çıkarır.

    Markdown code-fence (```json … ```) veya ham `{...}` destekler; parse etmez.
    Durumsuzdur.
    """

    def extract(self, raw: str) -> str | None:
        if not raw:
            return None

        fence_match = _CODE_FENCE_RE.search(raw)
        if fence_match:
            candidate = fence_match.group(1).strip()
            if candidate.startswith("{"):
                return candidate

        obj_match = _JSON_BLOCK_RE.search(raw)
        if obj_match:
            return obj_match.group(0)
        return None


# ══════════════════════════════════════════════════════════════════════
# SRP — Şema whitelist + tip + boyut doğrulama
# ══════════════════════════════════════════════════════════════════════


class ArchSchemaSanitizer:
    """Parse edilmiş sözlüğü güvenli şema sözleşmesine indirger.

    - K38 (bağlam zehirlenmesi): whitelist dışı anahtarlar sessizce atılır.
    - K56 (JSON bomb): string/liste uzunlukları sert sınırlandırılır.

    Geçerli → `{"description": str, "stack": [str], "directories": [str], "architecture": str}`
    Geçersiz → `None`
    """

    def sanitize(self, data: Any) -> dict | None:
        if not isinstance(data, dict):
            return None

        description = data.get("description")
        stack = data.get("stack")
        directories = data.get("directories")
        architecture = data.get("architecture")

        if not isinstance(description, str) or not isinstance(architecture, str):
            return None

        description = description.strip()
        architecture = architecture.strip()
        if not description or not architecture:
            return None
        if len(description) > _MAX_DESCRIPTION_LEN:
            description = description[:_MAX_DESCRIPTION_LEN]
        if len(architecture) > _MAX_ARCHITECTURE_LEN:
            architecture = architecture[:_MAX_ARCHITECTURE_LEN]

        stack_clean = self._coerce_str_list(stack, _MAX_STACK_ITEMS)
        dirs_clean = self._coerce_str_list(directories, _MAX_DIRECTORIES_ITEMS)
        if stack_clean is None or dirs_clean is None:
            return None

        return {
            "description":  description,
            "stack":        stack_clean,
            "directories":  dirs_clean,
            "architecture": architecture,
        }

    @staticmethod
    def _coerce_str_list(value: Any, max_items: int) -> list[str] | None:
        if not isinstance(value, list):
            return None
        result: list[str] = []
        for item in value[:max_items]:
            if not isinstance(item, str):
                return None
            trimmed = item.strip()
            if not trimmed:
                continue
            if len(trimmed) > _MAX_FIELD_STR_LEN:
                trimmed = trimmed[:_MAX_FIELD_STR_LEN]
            result.append(trimmed)
        if not result:
            return None
        return result


# ══════════════════════════════════════════════════════════════════════
# SRP — Backend-bazlı model + API anahtarı çözümleme
# ══════════════════════════════════════════════════════════════════════


class WizardLLMConfig:
    """Settings + aktif LLM backend → model + API anahtarı durumu.

    `settings` nesnesi constructor üzerinden enjekte edilir (DIP) — testler
    `patch.object(mod, "settings", ...)` ile farklı bir mock verebilir.
    """

    def __init__(self, settings_obj: Any) -> None:
        self._settings = settings_obj

    def resolve_model(self) -> str | None:
        """Anthropic backend'de `wizard_llm_model`; aksi halde `None`."""
        backend = self._settings.llm_backend.lower()
        if backend != "anthropic":
            return None
        return getattr(
            self._settings,
            "wizard_llm_model",
            self._settings.intent_classifier_model,
        )

    def has_api_key(self) -> bool:
        backend = self._settings.llm_backend.lower()
        if backend == "anthropic":
            return bool(self._settings.anthropic_api_key.get_secret_value())
        if backend == "gemini":
            return bool(self._settings.gemini_api_key.get_secret_value())
        return True  # ollama — API anahtarı gerekmez


# ══════════════════════════════════════════════════════════════════════
# Bridge adapter — LLM arayüzüyle uyumlu bridge istemcisi (DIP)
# ══════════════════════════════════════════════════════════════════════

_BRIDGE_SESSION_PREFIX = "wizard-arch-"


class WizardBridgeAdapter:
    """Bridge /query endpoint'ini LLM provider arayüzüyle saran adapter.

    Claude Code Bridge OAuth ile doğrulandığından Anthropic API anahtarı
    gerekmez. Her çağrıya özgü session_id üretilir — oturumlar arası
    durum kirleşmesi olmaz.
    """

    def __init__(self, bridge_url: str, api_key: str) -> None:
        self._bridge_url = bridge_url
        self._api_key = api_key

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> CompletionResult:
        prompt = next(
            (m["content"] for m in messages if m.get("role") == "user"),
            "",
        )
        session_id = f"{_BRIDGE_SESSION_PREFIX}{uuid.uuid4().hex[:8]}"
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{self._bridge_url}/query",
                headers={"X-Api-Key": self._api_key},
                json={"session_id": session_id, "message": prompt},
            )
            r.raise_for_status()
            answer = r.json().get("answer", "")
        return CompletionResult(
            text=answer,
            model_id="bridge",
            model_name="bridge",
            backend="bridge",
            input_tokens=0,
            output_tokens=0,
        )


def _bridge_factory() -> WizardBridgeAdapter:
    """Bridge adapter örneği oluşturur — testlerde patch.object hedefi."""
    return WizardBridgeAdapter(
        bridge_url=settings.claude_bridge_url,
        api_key=settings.api_key.get_secret_value(),
    )


# ══════════════════════════════════════════════════════════════════════
# DIP — Orkestratör
# ══════════════════════════════════════════════════════════════════════


class WizardLLMScaffoldService:
    """Mimari önizleme orkestratörü.

    Tüm bağımlılıklar constructor üzerinden enjekte edilir; hiçbiri somut
    sınıfa doğrudan bağlı değildir. Yeni prompt stratejisi, yeni parser veya
    yeni şema doğrulama için servis değişmeden yalnızca bileşen değiştirilir.
    """

    def __init__(
        self,
        prompt_builder: ArchPromptBuilder,
        extractor: ArchResponseExtractor,
        sanitizer: ArchSchemaSanitizer,
        config: WizardLLMConfig,
        llm_factory: Callable[[], Any],
        timeout_seconds: float,
        max_tokens: int = _LLM_MAX_TOKENS,
    ) -> None:
        self._prompts = prompt_builder
        self._extractor = extractor
        self._sanitizer = sanitizer
        self._config = config
        self._llm_factory = llm_factory
        self._timeout = timeout_seconds
        self._max_tokens = max_tokens

    async def generate(self, name: str, desc: str, lang: str) -> dict | None:
        """İlk üretim — proje adı + amaç → mimari önizlemesi."""
        prompt = self._prompts.build(name=name, desc=desc, lang=lang)
        return await self._call_llm(prompt)

    async def regenerate(
        self,
        name: str,
        desc: str,
        lang: str,
        prev_json: dict,
        user_feedback: str,
    ) -> dict | None:
        """Kullanıcı geri bildirimi ışığında önizlemeyi yeniden üretir."""
        prompt = self._prompts.build(
            name=name,
            desc=desc,
            lang=lang,
            prev_json=prev_json,
            user_feedback=user_feedback,
        )
        return await self._call_llm(prompt)

    async def _call_llm(self, prompt: str) -> dict | None:
        """Ortak akış: API-key kontrolü → LLM veya bridge → timeout → extract → parse → sanitize.

        API anahtarı varsa doğrudan LLM adapter kullanılır; yoksa bridge fallback devreye girer.
        """
        if self._config.has_api_key():
            llm = self._llm_factory()
        else:
            logger.info("wizard_llm_scaffold: API anahtarı yok — bridge fallback kullanılıyor")
            llm = _bridge_factory()

        try:
            completion = await asyncio.wait_for(
                llm.complete(
                    messages=[{"role": "user", "content": prompt}],
                    model=self._config.resolve_model(),
                    max_tokens=self._max_tokens,
                ),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "wizard_llm_scaffold: LLM çağrısı %.1f sn içinde yanıt vermedi",
                self._timeout,
            )
            return None
        except Exception as exc:  # noqa: BLE001 — adapter hataları ağ/HTTP/JSON olabilir
            logger.warning("wizard_llm_scaffold: LLM çağrısı başarısız: %s", exc)
            return None

        try:
            await token_stat_repo.add_usage(
                completion.model_id, completion.model_name, completion.backend,
                completion.input_tokens, completion.output_tokens,
                context="wizard_scaffold",
            )
        except Exception:
            pass
        raw = completion.text if completion else ""
        block = self._extractor.extract(raw)
        if block is None:
            logger.warning(
                "wizard_llm_scaffold: yanıtta JSON bloğu bulunamadı (uzunluk=%d)",
                len(raw),
            )
            return None

        try:
            parsed = json.loads(block)
        except json.JSONDecodeError as exc:
            logger.warning("wizard_llm_scaffold: JSON parse hatası: %s", exc)
            return None

        sanitized = self._sanitizer.sanitize(parsed)
        if sanitized is None:
            logger.warning("wizard_llm_scaffold: yanıt şema doğrulamasından geçmedi")
        return sanitized


# ══════════════════════════════════════════════════════════════════════
# Kamuya açık fasad — geri uyumluluk + modül-seviye patch desteği
# ══════════════════════════════════════════════════════════════════════
#
# Stateless yardımcı sınıflar tek kez kurulur (prompt/extractor/sanitizer).
# Servis ise çağrı başı yeniden kurulur ki test patch'leri (mod.settings,
# mod.get_llm, mod._LLM_TIMEOUT_SECONDS) güncel değerleri yakalasın.

_PROMPT_BUILDER = ArchPromptBuilder()
_EXTRACTOR = ArchResponseExtractor()
_SANITIZER = ArchSchemaSanitizer()


def _build_service() -> WizardLLMScaffoldService:
    """Modül-seviye bağımlılıklardan yeni bir servis oluşturur.

    Her çağrıda yeniden kurulur; `patch.object(mod, "settings", ...)`,
    `patch.object(mod, "get_llm", ...)`, `patch.object(mod, "_bridge_factory", ...)` ve
    `patch.object(mod, "_LLM_TIMEOUT_SECONDS", ...)` mevcut testler korunur.
    """
    return WizardLLMScaffoldService(
        prompt_builder=_PROMPT_BUILDER,
        extractor=_EXTRACTOR,
        sanitizer=_SANITIZER,
        config=WizardLLMConfig(settings),
        llm_factory=get_llm,
        timeout_seconds=_LLM_TIMEOUT_SECONDS,
    )


def build_arch_prompt(
    name: str,
    desc: str,
    lang: str,
    prev_json: dict | None = None,
    user_feedback: str | None = None,
) -> str:
    """Wizard mimari önizleme prompt'u üretir (ArchPromptBuilder sarmalayıcısı)."""
    return _PROMPT_BUILDER.build(
        name=name,
        desc=desc,
        lang=lang,
        prev_json=prev_json,
        user_feedback=user_feedback,
    )


def sanitize_arch_dict(data: Any) -> dict | None:
    """Ham sözlük → whitelist + tip + boyut doğrulanmış dict (ArchSchemaSanitizer)."""
    return _SANITIZER.sanitize(data)


def _extract_json_block(raw: str) -> str | None:
    """Ham LLM yanıtından JSON nesne bloğunu çıkarır (ArchResponseExtractor)."""
    return _EXTRACTOR.extract(raw)


async def generate_arch_preview(
    name: str,
    desc: str,
    lang: str,
) -> dict | None:
    """Proje adı + amaç → LLM mimari önizlemesi.

    Başarısızsa (API anahtarı yok, timeout, parse/şema hatası) `None` döner;
    çağıran taraf statik şablona düşer.
    """
    return await _build_service().generate(name=name, desc=desc, lang=lang)


async def regenerate_arch_preview(
    name: str,
    desc: str,
    lang: str,
    prev_json: dict,
    user_feedback: str,
) -> dict | None:
    """Kullanıcı geri bildirimi ışığında önizlemeyi yeniden üretir.

    `prev_json` önceki sanitized öneri; `user_feedback` kullanıcının serbest metni.
    """
    return await _build_service().regenerate(
        name=name,
        desc=desc,
        lang=lang,
        prev_json=prev_json,
        user_feedback=user_feedback,
    )
