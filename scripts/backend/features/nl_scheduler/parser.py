"""NLScheduleParser — doğal dil metninden zamanlama parametrelerini çıkarır.

Akış:
  1. Hızlı keyword ön filtresi → LLM çağrısını gerektirir mi?
  2. Mevcut proje ve tarama tiplerini yükle
  3. LLM (Haiku) ile JSON çıkarımı
  4. Doğrulama ve ScheduleParams döndürme

SRP: Yalnızca çıkarım — session yönetimi ve schedule oluşturma dışarıda.
DIP: get_llm() fabrikası üzerinden LLM erişimi.
"""
from __future__ import annotations

import json
import logging
import re

from .models import ScheduleParams

logger = logging.getLogger(__name__)

# ── Keyword ön filtreleri ─────────────────────────────────────────
# Her iki gruptan en az birer kelime gerekir → LLM çağrısı tetiklenir

_TIME_KEYWORDS: frozenset[str] = frozenset({
    "dakika", "dakikada", "saatte", "saatlik", "günlük", "haftalık",
    "günde", "haftada", "zamanla", "planla", "düzenli", "otomatik",
    "periyodik", "schedule", "cron", "her",
})

_TASK_KEYWORDS: frozenset[str] = frozenset({
    "tarama", "tara", "güvenlik", "security", "bug", "bugfix",
    "backlog", "executor", "çalıştır", "çalıştır", "scan",
})

_VALID_ACTION_TYPES: frozenset[str] = frozenset({
    "run_scanner",
    "run_backlog_executor",
})


class NLScheduleParser:
    """Doğal dil metninden ScheduleParams çıkaran parser.

    OOP: Tüm durum ve yardımcı metodlar bu sınıfa aittir.
    DIP: LLM erişimi get_llm() fabrikası üzerinden sağlanır.
    SRP: Yalnızca parse sorumluluğu — session ve schedule yönetimi dışarıda.
    """

    def is_schedule_intent(self, text: str) -> bool:
        """Hızlı keyword ön filtresi — LLM çağrısı gerekmeden karar verir.

        Her iki gruptan (_TIME_KEYWORDS, _TASK_KEYWORDS) en az birer kelime
        varsa True döner; aksi hâlde False (LLM çağrısı yapılmaz).
        """
        lowered = text.lower()
        has_time = any(kw in lowered for kw in _TIME_KEYWORDS)
        has_task = any(kw in lowered for kw in _TASK_KEYWORDS)
        return has_time and has_task

    async def parse(self, text: str) -> ScheduleParams | None:
        """Metinden ScheduleParams çıkar.

        Returns:
            ScheduleParams dict veya çıkarım başarısızsa None.
        """
        if not self.is_schedule_intent(text):
            return None

        available_projects = await self._get_available_projects()
        available_scan_types = self._get_scan_types()

        prompt = self._build_prompt(text, available_projects, available_scan_types)

        try:
            from ...adapters.llm.llm_factory import get_llm
            llm = get_llm()
            result = await llm.complete(
                messages=[{"role": "user", "content": prompt}],
                model=self._get_model(),
                max_tokens=300,
            )
            raw_text = result.text.strip()
            # JSON bloğu varsa sadece onu al
            json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if not json_match:
                logger.warning("NLScheduleParser: LLM yanıtında JSON bulunamadı")
                return None
            raw = json.loads(json_match.group())
            return self._post_process(raw)
        except json.JSONDecodeError as exc:
            logger.warning("NLScheduleParser: JSON parse hatası: %s", exc)
            return None
        except Exception as exc:
            logger.warning("NLScheduleParser: LLM çağrısı başarısız: %s", exc)
            return None

    def _build_prompt(
        self,
        text: str,
        projects: list[str],
        scan_types: list[str],
    ) -> str:
        """LLM için JSON çıkarım prompt'u oluşturur."""
        return f"""Kullanıcının zamanlama isteğini analiz et ve JSON olarak çıkar.

Kullanıcı mesajı: "{text}"

Mevcut projeler: {", ".join(projects) if projects else "petekv5"}
Mevcut tarama tipleri: {", ".join(scan_types) if scan_types else "security, bugfix"}

Çıkar ve SADECE şu JSON'u döndür (başka metin ekleme):
{{
  "project_id": "proje adı (kesinlikle tanınan projelerden biri olmalı, yoksa boş string)",
  "action_type": "run_scanner veya run_backlog_executor",
  "scan_type": "security veya bugfix (sadece run_scanner için, yoksa boş string)",
  "prefix": "SEC veya BUG gibi prefix (run_backlog_executor için, yoksa boş string)",
  "max_items": 3,
  "auto_review": true,
  "dry_run": false,
  "cron_expr": "dakika saat gün ay hgün formatında (örn: '*/30 * * * *')",
  "human_readable": "Türkçe sıklık açıklaması (örn: 'Her 30 dakikada bir')"
}}

Sıklık çeviri rehberi:
- "yarım saatte bir" / "30 dakikada" → "*/30 * * * *"
- "saatte bir" / "saatlik" / "her saat" → "0 * * * *"
- "2 saatte bir" → "0 */2 * * *"
- "günde bir" / "günlük" / "her gün" → "0 9 * * *"
- "sabah X'de" → "0 X * * *"
- "her N dakikada" → "*/N * * * *"

Eğer zamanlama isteği değilse veya gerekli bilgiler eksikse: {{"project_id": ""}}"""

    async def _get_available_projects(self) -> list[str]:
        """DB'den proje ID listesini çeker.

        Hata durumunda boş liste döner (graceful degradation).
        """
        try:
            from ...store.repositories.project_repo import project_list
            projects = await project_list()
            return [p["id"] for p in projects]
        except Exception as exc:
            logger.warning("NLScheduleParser: proje listesi alınamadı: %s", exc)
            return []

    def _get_scan_types(self) -> list[str]:
        """Mevcut scan config tiplerini listeler.

        Hata durumunda varsayılan listeyi döner (graceful degradation).
        """
        try:
            from ...features.scan_pipeline.config_loader import ScanConfigLoader
            return ScanConfigLoader().list_available()
        except Exception as exc:
            logger.warning("NLScheduleParser: scan tipleri alınamadı: %s", exc)
            return ["security", "bugfix"]

    def _get_model(self) -> str | None:
        """Anthropic backend'de intent classifier modelini döner, diğerlerinde None."""
        from ...config import settings
        if settings.llm_backend.lower() == "anthropic":
            return settings.intent_classifier_model
        return None

    def _post_process(self, raw: dict) -> ScheduleParams | None:
        """Ham LLM çıktısını doğrular ve ScheduleParams'a dönüştürür.

        Returns:
            Doğrulanmış ScheduleParams veya geçersizse None.
        """
        project_id = raw.get("project_id", "").strip()
        if not project_id:
            return None

        action_type = raw.get("action_type", "").strip()
        if action_type not in _VALID_ACTION_TYPES:
            logger.warning(
                "NLScheduleParser: geçersiz action_type=%r, beklenen: %s",
                action_type, sorted(_VALID_ACTION_TYPES),
            )
            return None

        cron_expr = raw.get("cron_expr", "").strip()
        if not cron_expr:
            return None

        human_readable = raw.get("human_readable", cron_expr)
        description = (
            f"{human_readable} — "
            f"{action_type.replace('run_', '')} ({project_id})"
        )

        params: ScheduleParams = {
            "project_id": project_id,
            "action_type": action_type,
            "cron_expr": cron_expr,
            "human_readable": human_readable,
            "description": description,
            "scan_type": raw.get("scan_type", ""),
            "prefix": raw.get("prefix", ""),
            "max_items": int(raw.get("max_items", 3)),
            "auto_review": bool(raw.get("auto_review", True)),
            "dry_run": bool(raw.get("dry_run", False)),
        }
        return params
