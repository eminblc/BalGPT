"""NLScheduleParser unit testleri — tüm LLM ve DB çağrıları mock'lanır."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Yardımcı fabrikalar
# ─────────────────────────────────────────────────────────────────────────────

def _make_parser():
    from backend.features.nl_scheduler.parser import NLScheduleParser
    return NLScheduleParser()


def _make_valid_raw(**overrides) -> dict:
    base = {
        "project_id": "my-project",
        "action_type": "run_scanner",
        "scan_type": "security",
        "prefix": "",
        "max_items": 3,
        "auto_review": True,
        "dry_run": False,
        "cron_expr": "*/30 * * * *",
        "human_readable": "Her 30 dakikada bir",
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TestIsScheduleIntent
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsScheduleIntent:
    """Keyword ön filtresi — hem time hem task keyword gerekir."""

    def test_security_scan_every_30min_returns_true(self):
        parser = _make_parser()
        assert parser.is_schedule_intent(
            "my-project için yarım saatte bir güvenlik taraması yap"
        ) is True

    def test_hourly_security_scan_returns_true(self):
        parser = _make_parser()
        assert parser.is_schedule_intent(
            "saatlik security scan my-project"
        ) is True

    def test_daily_backlog_executor_returns_true(self):
        parser = _make_parser()
        assert parser.is_schedule_intent(
            "backlog executor her gün çalıştır"
        ) is True

    def test_greeting_returns_false(self):
        parser = _make_parser()
        assert parser.is_schedule_intent("merhaba nasılsın") is False

    def test_read_file_returns_false(self):
        parser = _make_parser()
        assert parser.is_schedule_intent("dosyayı oku") is False

    def test_security_without_time_keyword_returns_false(self):
        """'güvenlik önemlidir' — task keyword var ama time keyword yok."""
        parser = _make_parser()
        assert parser.is_schedule_intent("güvenlik önemlidir") is False

    def test_time_keyword_only_returns_false(self):
        """'her gün' — time keyword var ama task keyword yok."""
        parser = _make_parser()
        assert parser.is_schedule_intent("her gün") is False


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TestPostProcess
# ═══════════════════════════════════════════════════════════════════════════════

class TestPostProcess:
    """_post_process: doğrulama ve ScheduleParams dönüşümü."""

    def test_valid_dict_returns_schedule_params(self):
        parser = _make_parser()
        raw = _make_valid_raw()
        result = parser._post_process(raw)
        assert result is not None
        assert result["project_id"] == "my-project"
        assert result["cron_expr"] == "*/30 * * * *"

    def test_empty_project_id_returns_none(self):
        parser = _make_parser()
        raw = _make_valid_raw(project_id="")
        assert parser._post_process(raw) is None

    def test_unknown_action_type_returns_none(self):
        parser = _make_parser()
        raw = _make_valid_raw(action_type="unknown")
        assert parser._post_process(raw) is None

    def test_empty_cron_expr_returns_none(self):
        parser = _make_parser()
        raw = _make_valid_raw(cron_expr="")
        assert parser._post_process(raw) is None

    def test_run_scanner_description_contains_scanner(self):
        parser = _make_parser()
        raw = _make_valid_raw(action_type="run_scanner")
        result = parser._post_process(raw)
        assert result is not None
        assert "scanner" in result["description"]

    def test_run_backlog_executor_description_contains_executor(self):
        parser = _make_parser()
        raw = _make_valid_raw(action_type="run_backlog_executor")
        result = parser._post_process(raw)
        assert result is not None
        assert "executor" in result["description"]

    def test_missing_auto_review_defaults_to_true(self):
        parser = _make_parser()
        raw = _make_valid_raw()
        raw.pop("auto_review", None)
        result = parser._post_process(raw)
        assert result is not None
        assert result["auto_review"] is True

    def test_missing_max_items_defaults_to_3(self):
        parser = _make_parser()
        raw = _make_valid_raw()
        raw.pop("max_items", None)
        result = parser._post_process(raw)
        assert result is not None
        assert result["max_items"] == 3

    def test_missing_prefix_defaults_to_empty_string(self):
        parser = _make_parser()
        raw = _make_valid_raw()
        raw.pop("prefix", None)
        result = parser._post_process(raw)
        assert result is not None
        assert result["prefix"] == ""


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TestBuildPrompt
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildPrompt:
    """_build_prompt: prompt içeriği doğrulama."""

    def test_prompt_contains_user_text(self):
        parser = _make_parser()
        prompt = parser._build_prompt(
            "saatlik güvenlik taraması yap",
            ["my-project"],
            ["security", "bugfix"],
        )
        assert "saatlik güvenlik taraması yap" in prompt

    def test_prompt_contains_project_list(self):
        parser = _make_parser()
        prompt = parser._build_prompt(
            "test mesajı",
            ["my-project", "other-project"],
            ["security"],
        )
        assert "my-project" in prompt
        assert "other-project" in prompt

    def test_prompt_contains_scan_types(self):
        parser = _make_parser()
        prompt = parser._build_prompt(
            "test",
            ["proj"],
            ["security", "bugfix"],
        )
        assert "security" in prompt
        assert "bugfix" in prompt

    def test_prompt_contains_cron_format_examples(self):
        parser = _make_parser()
        prompt = parser._build_prompt("test", ["proj"], ["security"])
        # Prompt'ta cron örneklerinden en az biri bulunmalı
        assert "* * * *" in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TestParseAsync
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseAsync:
    """parse(): LLM ve DB tamamen mock'lanır."""

    @pytest.mark.asyncio
    async def test_no_schedule_intent_returns_none_without_llm(self):
        """is_schedule_intent False olunca LLM hiç çağrılmamalı."""
        parser = _make_parser()
        with patch.object(parser, "is_schedule_intent", return_value=False):
            with patch(
                "backend.adapters.llm.llm_factory.get_llm"
            ) as mock_get_llm:
                result = await parser.parse("merhaba nasılsın")
        assert result is None
        mock_get_llm.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_llm_response_returns_schedule_params(self):
        """LLM geçerli JSON döndürünce ScheduleParams elde edilmeli."""
        import json as _json
        parser = _make_parser()
        raw = _make_valid_raw()

        mock_llm = MagicMock()
        mock_result = MagicMock()
        mock_result.text = _json.dumps(raw)
        mock_llm.complete = AsyncMock(return_value=mock_result)

        with patch.object(parser, "is_schedule_intent", return_value=True), \
             patch.object(parser, "_get_available_projects", new=AsyncMock(return_value=["my-project"])), \
             patch.object(parser, "_get_scan_types", return_value=["security", "bugfix"]), \
             patch(
                 "backend.adapters.llm.llm_factory.get_llm",
                 return_value=mock_llm,
             ):
            result = await parser.parse("my-project için saatlik güvenlik taraması")

        assert result is not None
        assert result["project_id"] == "my-project"
        assert result["cron_expr"] == "*/30 * * * *"

    @pytest.mark.asyncio
    async def test_llm_returns_empty_project_id_returns_none(self):
        """LLM {"project_id": ""} döndürünce None beklenir."""
        import json as _json
        parser = _make_parser()

        mock_llm = MagicMock()
        mock_result = MagicMock()
        mock_result.text = _json.dumps({"project_id": ""})
        mock_llm.complete = AsyncMock(return_value=mock_result)

        with patch.object(parser, "is_schedule_intent", return_value=True), \
             patch.object(parser, "_get_available_projects", new=AsyncMock(return_value=[])), \
             patch.object(parser, "_get_scan_types", return_value=["security"]), \
             patch(
                 "backend.adapters.llm.llm_factory.get_llm",
                 return_value=mock_llm,
             ):
            result = await parser.parse("belirsiz bir istek")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_returns_invalid_json_returns_none(self):
        """LLM bozuk JSON döndürünce None beklenir, exception fırlatılmamalı."""
        parser = _make_parser()

        mock_llm = MagicMock()
        mock_result = MagicMock()
        mock_result.text = "bu geçerli bir JSON değil"
        mock_llm.complete = AsyncMock(return_value=mock_result)

        with patch.object(parser, "is_schedule_intent", return_value=True), \
             patch.object(parser, "_get_available_projects", new=AsyncMock(return_value=["proj"])), \
             patch.object(parser, "_get_scan_types", return_value=["security"]), \
             patch(
                 "backend.adapters.llm.llm_factory.get_llm",
                 return_value=mock_llm,
             ):
            result = await parser.parse("bir şey yap")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_raises_exception_returns_none(self):
        """LLM exception fırlatırsa None beklenir, exception dışarı sızmamalı."""
        parser = _make_parser()

        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(side_effect=RuntimeError("LLM bağlantı hatası"))

        with patch.object(parser, "is_schedule_intent", return_value=True), \
             patch.object(parser, "_get_available_projects", new=AsyncMock(return_value=["proj"])), \
             patch.object(parser, "_get_scan_types", return_value=["security"]), \
             patch(
                 "backend.adapters.llm.llm_factory.get_llm",
                 return_value=mock_llm,
             ):
            result = await parser.parse("güvenlik taraması planla")

        assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TestGetAvailableProjects
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetAvailableProjects:
    """_get_available_projects: DB erişimi mock'lanır."""

    @pytest.mark.asyncio
    async def test_returns_project_ids_from_project_list(self):
        """project_list sonuçlarından ID'ler döner."""
        parser = _make_parser()
        fake_projects = [{"id": "my-project"}, {"id": "my-app"}]

        # _get_available_projects içinde 'from ...store.repositories.project_repo import project_list'
        # şeklinde lazy import yapılıyor; modül düzeyinde patch'liyoruz.
        with patch(
            "backend.store.repositories.project_repo.project_list",
            new=AsyncMock(return_value=fake_projects),
        ):
            result = await parser._get_available_projects()

        assert isinstance(result, list)
        assert result == ["my-project", "my-app"]

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_project_list_raises(self):
        """project_list exception fırlatırsa boş liste döner."""
        parser = _make_parser()

        async def _raise(*_a, **_kw):
            raise RuntimeError("DB kapalı")

        with patch(
            "backend.store.repositories.project_repo.project_list",
            new=_raise,
        ):
            result = await parser._get_available_projects()

        assert result == []
