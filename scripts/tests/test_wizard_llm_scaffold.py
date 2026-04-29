"""WIZ-LLM-8 — wizard_llm_scaffold birim testleri.

Kapsam:
  - `build_arch_prompt` (ilk üretim + regenerate + dil etiketi)
  - `sanitize_arch_dict` (whitelist + tip + boyut + kırpma)
  - `_extract_json_block` (code fence, raw obj, yok)
  - `generate_arch_preview` (happy / timeout / JSON parse / sanitize fail / API key yok)
  - `regenerate_arch_preview` (prev_json + feedback prompt'a geçer)
  - `project_scaffold._build_md_content` (ai_overrides yolu)
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.adapters.llm.result import CompletionResult


def _cr(text: str) -> CompletionResult:
    """Test için minimal CompletionResult oluşturur."""
    return CompletionResult(
        text=text, model_id="claude-haiku-4-5-20251001",
        model_name="Haiku 4.5", backend="anthropic",
        input_tokens=10, output_tokens=5,
    )


# ══════════════════════════════════════════════════════════════════════
# build_arch_prompt
# ══════════════════════════════════════════════════════════════════════


def test_build_arch_prompt_first_gen_tr():
    from backend.features.wizard_llm_scaffold import build_arch_prompt

    prompt = build_arch_prompt(name="Foo", desc="Bir proje.", lang="tr")

    assert "Foo" in prompt
    assert "Bir proje." in prompt
    assert "Türkçe" in prompt
    # İlk üretim modunda önceki öneri ibaresi olmamalı
    assert "Önceki öneri" not in prompt
    # Şema başlıkları
    assert "description" in prompt
    assert "stack" in prompt
    assert "directories" in prompt
    assert "architecture" in prompt


def test_build_arch_prompt_first_gen_en_language_label():
    from backend.features.wizard_llm_scaffold import build_arch_prompt

    prompt = build_arch_prompt(name="Bar", desc="Some project.", lang="en")

    assert "English" in prompt
    assert "Türkçe" not in prompt


def test_build_arch_prompt_regenerate_includes_prev_and_feedback():
    from backend.features.wizard_llm_scaffold import build_arch_prompt

    prev = {
        "description": "Önceki açıklama",
        "stack":        ["python"],
        "directories":  ["src/"],
        "architecture": "Eski mimari",
    }
    prompt = build_arch_prompt(
        name="Foo",
        desc="Amaç",
        lang="tr",
        prev_json=prev,
        user_feedback="FastAPI ekle lütfen",
    )

    assert "Önceki öneri" in prompt
    assert "Önceki açıklama" in prompt
    assert "FastAPI ekle lütfen" in prompt
    assert "Kullanıcı düzeltme isteği" in prompt


def test_build_arch_prompt_regenerate_handles_non_serializable_prev():
    """prev_json serileştirilemezse str() fallback kullanılır, exception atılmaz."""
    from backend.features.wizard_llm_scaffold import build_arch_prompt

    class _Unserializable:
        def __repr__(self) -> str:
            return "<UNSERIALIZABLE>"

    prev = {"obj": _Unserializable()}  # json.dumps başarısız olur
    prompt = build_arch_prompt(
        name="X",
        desc="Y",
        lang="tr",
        prev_json=prev,
        user_feedback="fb",
    )
    # str() fallback → prompt içinde nesne görünmeli ama exception atılmamalı
    assert "UNSERIALIZABLE" in prompt or "obj" in prompt
    assert "fb" in prompt


# ══════════════════════════════════════════════════════════════════════
# sanitize_arch_dict
# ══════════════════════════════════════════════════════════════════════


def _valid_payload() -> dict:
    return {
        "description":  "Geçerli açıklama.",
        "stack":        ["python", "fastapi"],
        "directories":  ["src/", "tests/"],
        "architecture": "Kısa mimari metni.",
    }


def test_sanitize_arch_dict_happy_path():
    from backend.features.wizard_llm_scaffold import sanitize_arch_dict

    out = sanitize_arch_dict(_valid_payload())
    assert out is not None
    assert out["description"] == "Geçerli açıklama."
    assert out["stack"] == ["python", "fastapi"]
    assert out["directories"] == ["src/", "tests/"]
    assert out["architecture"] == "Kısa mimari metni."


def test_sanitize_arch_dict_non_dict_returns_none():
    from backend.features.wizard_llm_scaffold import sanitize_arch_dict

    assert sanitize_arch_dict("string") is None
    assert sanitize_arch_dict(None) is None
    assert sanitize_arch_dict([1, 2, 3]) is None


def test_sanitize_arch_dict_missing_required_fields_returns_none():
    from backend.features.wizard_llm_scaffold import sanitize_arch_dict

    payload = _valid_payload()
    del payload["description"]
    assert sanitize_arch_dict(payload) is None

    payload = _valid_payload()
    del payload["architecture"]
    assert sanitize_arch_dict(payload) is None


def test_sanitize_arch_dict_empty_strings_return_none():
    from backend.features.wizard_llm_scaffold import sanitize_arch_dict

    payload = _valid_payload()
    payload["description"] = "   "
    assert sanitize_arch_dict(payload) is None

    payload = _valid_payload()
    payload["architecture"] = ""
    assert sanitize_arch_dict(payload) is None


def test_sanitize_arch_dict_whitelist_strips_extra_keys():
    """Bilinmeyen anahtarlar sessizce atılmalı (K38 bağlam zehirlenmesi koruması)."""
    from backend.features.wizard_llm_scaffold import sanitize_arch_dict

    payload = _valid_payload()
    payload["malicious_field"] = "drop table projects"
    payload["another_extra"]   = {"nested": "payload"}

    out = sanitize_arch_dict(payload)
    assert out is not None
    assert "malicious_field" not in out
    assert "another_extra" not in out
    assert set(out.keys()) == {"description", "stack", "directories", "architecture"}


def test_sanitize_arch_dict_truncates_long_description_and_architecture():
    from backend.features.wizard_llm_scaffold import sanitize_arch_dict

    payload = _valid_payload()
    payload["description"]  = "x" * 5000  # _MAX_DESCRIPTION_LEN=2000
    payload["architecture"] = "y" * 9000  # _MAX_ARCHITECTURE_LEN=4000

    out = sanitize_arch_dict(payload)
    assert out is not None
    assert len(out["description"]) == 2000
    assert len(out["architecture"]) == 4000


def test_sanitize_arch_dict_rejects_non_string_list_items():
    from backend.features.wizard_llm_scaffold import sanitize_arch_dict

    payload = _valid_payload()
    payload["stack"] = ["python", 123]  # int → None beklenir
    assert sanitize_arch_dict(payload) is None

    payload = _valid_payload()
    payload["directories"] = ["src/", None]
    assert sanitize_arch_dict(payload) is None


def test_sanitize_arch_dict_rejects_non_list_stack_or_dirs():
    from backend.features.wizard_llm_scaffold import sanitize_arch_dict

    payload = _valid_payload()
    payload["stack"] = "python,fastapi"  # string — list olmalı
    assert sanitize_arch_dict(payload) is None


def test_sanitize_arch_dict_truncates_long_list_items():
    from backend.features.wizard_llm_scaffold import sanitize_arch_dict

    payload = _valid_payload()
    payload["stack"] = ["a" * 500]  # _MAX_FIELD_STR_LEN=200

    out = sanitize_arch_dict(payload)
    assert out is not None
    assert len(out["stack"][0]) == 200


def test_sanitize_arch_dict_caps_list_length():
    """Stack/directories uzunluk üst sınırı aşan elemanlar kırpılır."""
    from backend.features.wizard_llm_scaffold import sanitize_arch_dict

    payload = _valid_payload()
    payload["stack"]       = [f"item_{i}" for i in range(100)]  # _MAX_STACK_ITEMS=30
    payload["directories"] = [f"dir_{i}" for i in range(200)]   # _MAX_DIRECTORIES_ITEMS=50

    out = sanitize_arch_dict(payload)
    assert out is not None
    assert len(out["stack"]) == 30
    assert len(out["directories"]) == 50


# ══════════════════════════════════════════════════════════════════════
# _extract_json_block
# ══════════════════════════════════════════════════════════════════════


def test_extract_json_block_from_code_fence():
    from backend.features.wizard_llm_scaffold import _extract_json_block

    raw = 'Açıklama\n```json\n{"a": 1}\n```\nSon söz.'
    block = _extract_json_block(raw)
    assert block is not None
    assert block.strip().startswith("{")
    assert '"a": 1' in block


def test_extract_json_block_raw_object():
    from backend.features.wizard_llm_scaffold import _extract_json_block

    raw = 'İşte sonuç: {"a": 1, "b": [2,3]}'
    block = _extract_json_block(raw)
    assert block is not None
    assert '"a"' in block


def test_extract_json_block_returns_none_when_absent():
    from backend.features.wizard_llm_scaffold import _extract_json_block

    assert _extract_json_block("") is None
    assert _extract_json_block("no json here") is None


# ══════════════════════════════════════════════════════════════════════
# generate_arch_preview — LLM mock
# ══════════════════════════════════════════════════════════════════════


def _mock_settings(backend: str = "anthropic", api_key: str = "test-key") -> MagicMock:
    mock = MagicMock()
    mock.llm_backend = backend
    mock.anthropic_api_key.get_secret_value.return_value = api_key
    mock.gemini_api_key.get_secret_value.return_value    = api_key
    mock.wizard_llm_model        = "claude-haiku-4-5-20251001"
    mock.intent_classifier_model = "claude-haiku-4-5-20251001"
    return mock


@pytest.mark.asyncio
async def test_generate_arch_preview_happy_path():
    """LLM geçerli JSON döndürürse sanitized dict dönmeli."""
    import json as _json
    from backend.features import wizard_llm_scaffold as mod

    payload = _valid_payload()
    llm_raw = "Yanıt:\n```json\n" + _json.dumps(payload) + "\n```"

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value=_cr(llm_raw))

    with patch.object(mod, "settings", _mock_settings()), \
         patch.object(mod, "get_llm", return_value=fake_llm):
        result = await mod.generate_arch_preview(name="X", desc="Y", lang="tr")

    assert result is not None
    assert result["description"] == payload["description"]
    assert result["stack"] == payload["stack"]
    fake_llm.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_arch_preview_timeout_returns_none():
    """LLM zaman aşımına uğrarsa None dönmeli (statik şablona düşüş)."""
    from backend.features import wizard_llm_scaffold as mod

    async def _hang(*a, **kw):
        await asyncio.sleep(10)
        return "never"

    fake_llm = MagicMock()
    fake_llm.complete = _hang

    with patch.object(mod, "settings", _mock_settings()), \
         patch.object(mod, "get_llm", return_value=fake_llm), \
         patch.object(mod, "_LLM_TIMEOUT_SECONDS", 0.05):
        result = await mod.generate_arch_preview(name="X", desc="Y", lang="tr")

    assert result is None


@pytest.mark.asyncio
async def test_generate_arch_preview_no_api_key_uses_bridge():
    """API anahtarı boşsa bridge fallback devreye girmeli."""
    import json as _json
    from backend.features import wizard_llm_scaffold as mod

    payload = _valid_payload()
    llm_raw = _json.dumps(payload)

    fake_bridge = MagicMock()
    fake_bridge.complete = AsyncMock(return_value=_cr(llm_raw))

    with patch.object(mod, "settings", _mock_settings(api_key="")), \
         patch.object(mod, "_bridge_factory", return_value=fake_bridge):
        result = await mod.generate_arch_preview(name="X", desc="Y", lang="tr")

    assert result is not None
    fake_bridge.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_arch_preview_json_parse_error_returns_none():
    """JSON bloğu çözümlenemezse None dönmeli."""
    from backend.features import wizard_llm_scaffold as mod

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value=_cr("{bozuk json ::: }"))

    with patch.object(mod, "settings", _mock_settings()), \
         patch.object(mod, "get_llm", return_value=fake_llm):
        result = await mod.generate_arch_preview(name="X", desc="Y", lang="tr")

    assert result is None


@pytest.mark.asyncio
async def test_generate_arch_preview_sanitize_fail_returns_none():
    """Geçerli JSON ama şema uyumsuzsa None dönmeli (whitelist)."""
    import json as _json
    from backend.features import wizard_llm_scaffold as mod

    bad = {"stack": ["x"], "directories": ["src/"], "architecture": "m"}

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(return_value=_cr(_json.dumps(bad)))

    with patch.object(mod, "settings", _mock_settings()), \
         patch.object(mod, "get_llm", return_value=fake_llm):
        result = await mod.generate_arch_preview(name="X", desc="Y", lang="tr")

    assert result is None


@pytest.mark.asyncio
async def test_generate_arch_preview_llm_exception_returns_none():
    """LLM adapter beklenmedik hata atarsa None dönmeli (ağ/HTTP/JSON)."""
    from backend.features import wizard_llm_scaffold as mod

    fake_llm = MagicMock()
    fake_llm.complete = AsyncMock(side_effect=RuntimeError("network down"))

    with patch.object(mod, "settings", _mock_settings()), \
         patch.object(mod, "get_llm", return_value=fake_llm):
        result = await mod.generate_arch_preview(name="X", desc="Y", lang="tr")

    assert result is None


# ══════════════════════════════════════════════════════════════════════
# regenerate_arch_preview
# ══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_regenerate_arch_preview_passes_prev_and_feedback_to_llm():
    """Regenerate modu prompt içinde prev_json + feedback göndermeli."""
    import json as _json
    from backend.features import wizard_llm_scaffold as mod

    new_payload = _valid_payload()
    new_payload["description"] = "Güncellenmiş açıklama"
    llm_raw = _json.dumps(new_payload)

    captured_prompt = {}

    async def _capture(messages, model=None, max_tokens=1024):
        captured_prompt["content"] = messages[0]["content"]
        return _cr(llm_raw)

    fake_llm = MagicMock()
    fake_llm.complete = _capture

    prev = {
        "description":  "Eski açıklama",
        "stack":        ["py"],
        "directories":  ["src/"],
        "architecture": "Eski mimari",
    }

    with patch.object(mod, "settings", _mock_settings()), \
         patch.object(mod, "get_llm", return_value=fake_llm):
        out = await mod.regenerate_arch_preview(
            name="Foo",
            desc="Amaç",
            lang="tr",
            prev_json=prev,
            user_feedback="Pydantic ekle",
        )

    assert out is not None
    assert out["description"] == "Güncellenmiş açıklama"
    assert "Eski açıklama" in captured_prompt["content"]
    assert "Pydantic ekle" in captured_prompt["content"]
    assert "Kullanıcı düzeltme isteği" in captured_prompt["content"]


# ══════════════════════════════════════════════════════════════════════
# project_scaffold._build_md_content — ai_overrides
# ══════════════════════════════════════════════════════════════════════


def test_build_md_content_claude_md_without_overrides():
    """ai_overrides=None → yalnızca statik başlık + Proje Kök Dizini kalır."""
    from backend.features.project_scaffold import _build_md_content

    out = _build_md_content(
        filename="CLAUDE.md",
        name="Foo",
        description="Bir proje.",
        project_dir=Path("/tmp/foo"),
        ai_overrides=None,
    )

    assert out.startswith("# Foo\n")
    assert "Bir proje." in out
    assert "## Proje Kök Dizini" in out
    assert "/tmp/foo" in out
    # AI bölümleri yok
    assert "## Stack" not in out
    assert "## Klasör Yapısı" not in out
    assert "## Mimari" not in out


def test_build_md_content_claude_md_with_stack_only():
    from backend.features.project_scaffold import _build_md_content

    out = _build_md_content(
        filename="CLAUDE.md",
        name="Foo",
        description="Bir proje.",
        project_dir=Path("/tmp/foo"),
        ai_overrides={"stack": ["python", "fastapi"]},
    )
    assert "## Stack" in out
    assert "- python" in out
    assert "- fastapi" in out
    # Dolmamış alanlar görünmemeli
    assert "## Klasör Yapısı" not in out
    assert "## Mimari" not in out


def test_build_md_content_claude_md_with_directories_only():
    from backend.features.project_scaffold import _build_md_content

    out = _build_md_content(
        filename="CLAUDE.md",
        name="Foo",
        description="Bir proje.",
        project_dir=Path("/tmp/foo"),
        ai_overrides={"directories": ["src/", "tests/"]},
    )
    assert "## Klasör Yapısı" in out
    assert "`src/`" in out
    assert "`tests/`" in out
    assert "## Stack" not in out
    assert "## Mimari" not in out


def test_build_md_content_claude_md_with_architecture_only():
    from backend.features.project_scaffold import _build_md_content

    out = _build_md_content(
        filename="CLAUDE.md",
        name="Foo",
        description="Bir proje.",
        project_dir=Path("/tmp/foo"),
        ai_overrides={"architecture": "Katman diyagramı"},
    )
    assert "## Mimari" in out
    assert "Katman diyagramı" in out
    assert "## Stack" not in out
    assert "## Klasör Yapısı" not in out


def test_build_md_content_claude_md_full_ai_overrides():
    from backend.features.project_scaffold import _build_md_content

    out = _build_md_content(
        filename="CLAUDE.md",
        name="Foo",
        description="Bir proje.",
        project_dir=Path("/tmp/foo"),
        ai_overrides={
            "stack":        ["python"],
            "directories":  ["src/"],
            "architecture": "Monolith FastAPI",
        },
    )
    # Statik başlık + yol KORUNMALI (WIZ-LLM-5 kuralı)
    assert out.startswith("# Foo\n")
    assert "## Proje Kök Dizini" in out
    # Üç blok da var ve statik sonrası ekli
    assert "## Stack\n- python\n" in out
    assert "## Klasör Yapısı\n- `src/`\n" in out
    assert "## Mimari\nMonolith FastAPI\n" in out


def test_build_md_content_claude_md_empty_overrides_dict_no_sections():
    """ai_overrides={} → boş truthy-false olduğundan sadece statik çıktı."""
    from backend.features.project_scaffold import _build_md_content

    out = _build_md_content(
        filename="CLAUDE.md",
        name="Foo",
        description="Bir proje.",
        project_dir=Path("/tmp/foo"),
        ai_overrides={},
    )
    assert "## Stack" not in out
    assert "## Klasör Yapısı" not in out
    assert "## Mimari" not in out


def test_build_md_content_non_claude_file_ignores_ai_overrides():
    """AGENT.md / BACKLOG.md / README.md ai_overrides'tan etkilenmez."""
    from backend.features.project_scaffold import _build_md_content

    overrides = {"stack": ["x"], "directories": ["y"], "architecture": "z"}

    agent = _build_md_content("AGENT.md",   "Foo", "desc", Path("/tmp/foo"), ai_overrides=overrides)
    backlog = _build_md_content("BACKLOG.md", "Foo", "desc", Path("/tmp/foo"), ai_overrides=overrides)
    readme  = _build_md_content("README.md",  "Foo", "desc", Path("/tmp/foo"), ai_overrides=overrides)

    for content in (agent, backlog, readme):
        assert "## Stack" not in content
        assert "## Klasör Yapısı" not in content
        assert "## Mimari" not in content
