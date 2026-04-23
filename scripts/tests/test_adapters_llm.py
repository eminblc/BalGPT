"""LLM factory ve provider seçimi testleri."""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import httpx


# ── get_llm factory ───────────────────────────────────────────────

def test_get_llm_anthropic():
    mock_settings = MagicMock()
    mock_settings.llm_backend = "anthropic"

    with patch("backend.adapters.llm.llm_factory.settings", mock_settings), \
         patch("backend.adapters.llm.llm_factory.get_active_model", return_value=None):
        from backend.adapters.llm.llm_factory import get_llm
        from backend.adapters.llm.anthropic_provider import AnthropicProvider
        llm = get_llm("anthropic")
    assert isinstance(llm, AnthropicProvider)


def test_get_llm_ollama():
    mock_settings = MagicMock()
    mock_settings.llm_backend = "ollama"

    with patch("backend.adapters.llm.llm_factory.settings", mock_settings), \
         patch("backend.adapters.llm.llm_factory.get_active_model", return_value=None):
        from backend.adapters.llm.llm_factory import get_llm
        from backend.adapters.llm.ollama_provider import OllamaProvider
        llm = get_llm("ollama")
    assert isinstance(llm, OllamaProvider)


def test_get_llm_gemini():
    mock_settings = MagicMock()
    mock_settings.llm_backend = "gemini"

    with patch("backend.adapters.llm.llm_factory.settings", mock_settings), \
         patch("backend.adapters.llm.llm_factory.get_active_model", return_value=None):
        from backend.adapters.llm.llm_factory import get_llm
        from backend.adapters.llm.gemini_provider import GeminiProvider
        llm = get_llm("gemini")
    assert isinstance(llm, GeminiProvider)


def test_get_llm_unknown_raises():
    mock_settings = MagicMock()
    mock_settings.llm_backend = "unknown_backend"

    with patch("backend.adapters.llm.llm_factory.settings", mock_settings), \
         patch("backend.adapters.llm.llm_factory.get_active_model", return_value=None):
        from backend.adapters.llm.llm_factory import get_llm
        with pytest.raises(ValueError, match="unknown_backend"):
            get_llm("unknown_backend")


def test_get_llm_uses_settings_backend():
    """Backend argümanı verilmezse settings.llm_backend kullanılmalı."""
    mock_settings = MagicMock()
    mock_settings.llm_backend = "anthropic"

    with patch("backend.adapters.llm.llm_factory.settings", mock_settings), \
         patch("backend.adapters.llm.llm_factory.get_active_model", return_value=None):
        from backend.adapters.llm.llm_factory import get_llm
        from backend.adapters.llm.anthropic_provider import AnthropicProvider
        llm = get_llm()
    assert isinstance(llm, AnthropicProvider)


def test_get_llm_with_active_model():
    """Aktif model varsa provider'a default_model olarak geçilmeli."""
    mock_settings = MagicMock()
    mock_settings.llm_backend = "anthropic"

    with patch("backend.adapters.llm.llm_factory.settings", mock_settings), \
         patch("backend.adapters.llm.llm_factory.get_active_model",
               return_value="claude-haiku-4-5-20251001"):
        from backend.adapters.llm.llm_factory import get_llm
        llm = get_llm("anthropic")
    assert llm._default_model == "claude-haiku-4-5-20251001"


def test_get_llm_case_insensitive():
    """Backend adı büyük-küçük harf duyarsız olmalı."""
    mock_settings = MagicMock()
    mock_settings.llm_backend = "ANTHROPIC"

    with patch("backend.adapters.llm.llm_factory.settings", mock_settings), \
         patch("backend.adapters.llm.llm_factory.get_active_model", return_value=None):
        from backend.adapters.llm.llm_factory import get_llm
        from backend.adapters.llm.anthropic_provider import AnthropicProvider
        llm = get_llm("ANTHROPIC")
    assert isinstance(llm, AnthropicProvider)


# ── register_backend OCP extension ───────────────────────────────

def test_register_backend_custom():
    from backend.adapters.llm.llm_factory import register_backend, _BACKENDS
    from backend.adapters.llm import AbstractLLMProvider

    class _FakeProvider(AbstractLLMProvider):
        def __init__(self, **kw): self.default_model = kw.get("default_model")
        async def complete(self, messages, model=None, max_tokens=1024): return "fake"

    register_backend("fake_llm", _FakeProvider)
    assert "fake_llm" in _BACKENDS
    # Temizlik
    del _BACKENDS["fake_llm"]


# ── AbstractLLMProvider — Protocol ve mock ile complete() ─────────

def test_abstract_llm_provider_protocol_check():
    """AbstractLLMProvider Protocol'ü uygulayan sınıf isinstance kontrolünden geçmeli."""
    from backend.adapters.llm import AbstractLLMProvider

    class _MockProvider:
        async def complete(self, messages, model=None, max_tokens=4096): return "mocked"

    assert isinstance(_MockProvider(), AbstractLLMProvider)


def test_abstract_llm_provider_missing_complete_fails_protocol():
    """complete() metodu olmayan sınıf Protocol kontrolünden geçmemeli."""
    from backend.adapters.llm import AbstractLLMProvider

    class _BrokenProvider:
        pass

    assert not isinstance(_BrokenProvider(), AbstractLLMProvider)


@pytest.mark.asyncio
async def test_abstract_llm_provider_mock_complete_returns_string():
    """Mock provider'dan complete() çağrısı string döndürmeli."""
    from backend.adapters.llm import AbstractLLMProvider

    class _StubProvider:
        async def complete(self, messages, model=None, max_tokens=4096):
            return "test yanıtı"

    provider = _StubProvider()
    assert isinstance(provider, AbstractLLMProvider)
    result = await provider.complete([{"role": "user", "content": "merhaba"}])
    assert result == "test yanıtı"


# ── AnthropicProvider.complete() ─────────────────────────────────

@pytest.mark.asyncio
async def test_anthropic_provider_complete_happy_path():
    """Başarılı API yanıtında metin döndürmeli."""
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {
        "content": [{"text": "Merhaba! Nasıl yardımcı olabilirim?"}]
    }

    mock_settings = MagicMock()
    mock_settings.anthropic_api_key.get_secret_value.return_value = "test-key"
    mock_settings.default_model = "claude-haiku-4-5-20251001"

    with patch("backend.adapters.llm.anthropic_provider.settings", mock_settings):
        from backend.adapters.llm.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider(api_key="test-key", default_model="claude-haiku-4-5-20251001")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("backend.adapters.llm.anthropic_provider.httpx.AsyncClient", return_value=mock_client):
        result = await provider.complete([{"role": "user", "content": "Merhaba"}])

    assert result.text == "Merhaba! Nasıl yardımcı olabilirim?"
    assert result.backend == "anthropic"
    assert result.input_tokens == 0
    assert result.output_tokens == 0


@pytest.mark.asyncio
async def test_anthropic_provider_system_message_extraction():
    """system role'lü mesajlar payload'da ayrı 'system' alanına taşınmalı."""
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {"content": [{"text": "ok"}]}

    provider = MagicMock()
    provider._api_key = "test-key"
    provider._default_model = "claude-haiku-4-5-20251001"
    provider._timeout = 60.0

    captured_payload = {}

    async def fake_post(url, headers, json):
        captured_payload.update(json)
        return mock_response

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=fake_post)

    from backend.adapters.llm.anthropic_provider import AnthropicProvider
    real_provider = AnthropicProvider.__new__(AnthropicProvider)
    real_provider._api_key = "test-key"
    real_provider._default_model = "claude-haiku-4-5-20251001"
    real_provider._timeout = 60.0

    with patch("backend.adapters.llm.anthropic_provider.httpx.AsyncClient", return_value=mock_client):
        await real_provider.complete([
            {"role": "system", "content": "Sen bir asistansın."},
            {"role": "user", "content": "Merhaba"},
        ])

    assert "system" in captured_payload
    assert "Sen bir asistansın." in captured_payload["system"]
    # system role chat_messages'e girmemeli
    roles_in_messages = [m["role"] for m in captured_payload["messages"]]
    assert "system" not in roles_in_messages


@pytest.mark.asyncio
async def test_anthropic_provider_no_api_key_raises():
    """API key yoksa RuntimeError fırlatmalı."""
    from backend.adapters.llm.anthropic_provider import AnthropicProvider
    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider._api_key = ""
    provider._default_model = "test"
    provider._timeout = 60.0

    with pytest.raises(RuntimeError, match="API anahtarı"):
        await provider.complete([{"role": "user", "content": "test"}])


@pytest.mark.asyncio
async def test_anthropic_provider_http_error_raises():
    """HTTP hata yanıtında raise_for_status çağrılmalı."""
    mock_response = MagicMock()
    mock_response.is_success = False
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=mock_response
    )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    from backend.adapters.llm.anthropic_provider import AnthropicProvider
    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider._api_key = "test-key"
    provider._default_model = "test"
    provider._timeout = 60.0

    with patch("backend.adapters.llm.anthropic_provider.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(httpx.HTTPStatusError):
            await provider.complete([{"role": "user", "content": "test"}])


# ── OllamaProvider.complete() ─────────────────────────────────────

@pytest.mark.asyncio
async def test_ollama_provider_complete_happy_path():
    """Başarılı Ollama yanıtında metin döndürmeli."""
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {"message": {"content": "Ollama yanıtı"}}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_settings = MagicMock()
    mock_settings.ollama_base_url = "http://localhost:11434"
    mock_settings.ollama_model = "llama3"

    with patch("backend.adapters.llm.ollama_provider.settings", mock_settings):
        from backend.adapters.llm.ollama_provider import OllamaProvider
        provider = OllamaProvider(base_url="http://localhost:11434", default_model="llama3")

    with patch("backend.adapters.llm.ollama_provider.httpx.AsyncClient", return_value=mock_client):
        result = await provider.complete([{"role": "user", "content": "test"}])

    assert result.text == "Ollama yanıtı"
    assert result.backend == "ollama"
    assert result.model_name == "Ollama/llama3"


@pytest.mark.asyncio
async def test_ollama_provider_parse_error_raises():
    """Beklenen anahtar yoksa RuntimeError fırlatmalı."""
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {"unexpected": "format"}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_settings = MagicMock()
    mock_settings.ollama_base_url = "http://localhost:11434"
    mock_settings.ollama_model = "llama3"

    with patch("backend.adapters.llm.ollama_provider.settings", mock_settings):
        from backend.adapters.llm.ollama_provider import OllamaProvider
        provider = OllamaProvider(base_url="http://localhost:11434", default_model="llama3")

    with patch("backend.adapters.llm.ollama_provider.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(RuntimeError, match="parse hatası"):
            await provider.complete([{"role": "user", "content": "test"}])


# ── GeminiProvider.complete() ─────────────────────────────────────

@pytest.mark.asyncio
async def test_gemini_provider_complete_happy_path():
    """Başarılı Gemini yanıtında metin döndürmeli."""
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "Gemini yanıtı"}]}}]
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_settings = MagicMock()
    mock_settings.gemini_api_key.get_secret_value.return_value = "test-gemini-key"
    mock_settings.gemini_model = "gemini-2.0-flash"

    with patch("backend.adapters.llm.gemini_provider.settings", mock_settings):
        from backend.adapters.llm.gemini_provider import GeminiProvider
        provider = GeminiProvider(api_key="test-gemini-key", default_model="gemini-2.0-flash")

    with patch("backend.adapters.llm.gemini_provider.httpx.AsyncClient", return_value=mock_client):
        result = await provider.complete([{"role": "user", "content": "Merhaba"}])

    assert result.text == "Gemini yanıtı"
    assert result.backend == "gemini"
    assert result.model_name == "Gemini 2.0 Flash"


@pytest.mark.asyncio
async def test_gemini_provider_role_conversion():
    """assistant role → model role'e dönüştürülmeli."""
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "ok"}]}}]
    }

    captured_payload = {}

    async def fake_post(url, json, headers):
        captured_payload.update(json)
        return mock_response

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(side_effect=fake_post)

    mock_settings = MagicMock()
    mock_settings.gemini_api_key.get_secret_value.return_value = "test-key"
    mock_settings.gemini_model = "gemini-2.0-flash"

    with patch("backend.adapters.llm.gemini_provider.settings", mock_settings):
        from backend.adapters.llm.gemini_provider import GeminiProvider
        provider = GeminiProvider(api_key="test-key", default_model="gemini-2.0-flash")

    with patch("backend.adapters.llm.gemini_provider.httpx.AsyncClient", return_value=mock_client):
        await provider.complete([
            {"role": "user", "content": "Soru"},
            {"role": "assistant", "content": "Yanıt"},
        ])

    roles = [c["role"] for c in captured_payload.get("contents", [])]
    assert "model" in roles
    assert "assistant" not in roles


@pytest.mark.asyncio
async def test_gemini_provider_no_api_key_raises():
    """API key yoksa RuntimeError fırlatmalı."""
    mock_settings = MagicMock()
    mock_settings.gemini_api_key.get_secret_value.return_value = ""
    mock_settings.gemini_model = "gemini-2.0-flash"

    with patch("backend.adapters.llm.gemini_provider.settings", mock_settings):
        from backend.adapters.llm.gemini_provider import GeminiProvider
        provider = GeminiProvider(api_key="", default_model="gemini-2.0-flash")

    with pytest.raises(RuntimeError, match="API anahtarı"):
        await provider.complete([{"role": "user", "content": "test"}])


# ── CompletionResult dataclass ────────────────────────────────────

def test_completion_result_fields():
    """CompletionResult tüm alanları erişilebilir olmalı."""
    from backend.adapters.llm.result import CompletionResult
    r = CompletionResult(
        text="merhaba",
        model_id="claude-3-5-haiku-20241022",
        model_name="Haiku 4.5",
        backend="anthropic",
        input_tokens=100,
        output_tokens=50,
    )
    assert r.text == "merhaba"
    assert r.model_id == "claude-3-5-haiku-20241022"
    assert r.model_name == "Haiku 4.5"
    assert r.backend == "anthropic"
    assert r.input_tokens == 100
    assert r.output_tokens == 50


def test_completion_result_immutable():
    """CompletionResult frozen=True olduğu için atama hata vermeli."""
    from backend.adapters.llm.result import CompletionResult
    r = CompletionResult("t", "mid", "mname", "anthropic", 0, 0)
    with pytest.raises(Exception):
        r.text = "değişti"  # type: ignore[misc]


# ── Token sayıları API yanıtından doğru okunmalı ──────────────────

@pytest.mark.asyncio
async def test_anthropic_token_counts_parsed():
    """Anthropic API yanıtındaki usage.input_tokens/output_tokens CompletionResult'a yansımalı."""
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {
        "content": [{"text": "yanıt"}],
        "usage": {"input_tokens": 123, "output_tokens": 45},
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_settings = MagicMock()
    mock_settings.anthropic_api_key.get_secret_value.return_value = "k"
    mock_settings.default_model = "claude-3-5-haiku-20241022"

    with patch("backend.adapters.llm.anthropic_provider.settings", mock_settings):
        from backend.adapters.llm.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider(api_key="k", default_model="claude-3-5-haiku-20241022")

    with patch("backend.adapters.llm.anthropic_provider.httpx.AsyncClient", return_value=mock_client):
        result = await provider.complete([{"role": "user", "content": "test"}])

    assert result.input_tokens == 123
    assert result.output_tokens == 45
    assert result.model_name == "Haiku 4.5"


@pytest.mark.asyncio
async def test_anthropic_missing_usage_defaults_to_zero():
    """Anthropic yanıtında usage alanı yoksa token sayıları 0 olmalı."""
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {"content": [{"text": "ok"}]}  # usage yok

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_settings = MagicMock()
    mock_settings.anthropic_api_key.get_secret_value.return_value = "k"
    mock_settings.default_model = "claude-3-5-haiku-20241022"

    with patch("backend.adapters.llm.anthropic_provider.settings", mock_settings):
        from backend.adapters.llm.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider(api_key="k", default_model="claude-3-5-haiku-20241022")

    with patch("backend.adapters.llm.anthropic_provider.httpx.AsyncClient", return_value=mock_client):
        result = await provider.complete([{"role": "user", "content": "test"}])

    assert result.input_tokens == 0
    assert result.output_tokens == 0


@pytest.mark.asyncio
async def test_gemini_token_counts_parsed():
    """Gemini usageMetadata.promptTokenCount/candidatesTokenCount CompletionResult'a yansımalı."""
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "gemini yanıtı"}]}}],
        "usageMetadata": {"promptTokenCount": 200, "candidatesTokenCount": 75},
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_settings = MagicMock()
    mock_settings.gemini_api_key.get_secret_value.return_value = "k"
    mock_settings.gemini_model = "gemini-2.0-flash"

    with patch("backend.adapters.llm.gemini_provider.settings", mock_settings):
        from backend.adapters.llm.gemini_provider import GeminiProvider
        provider = GeminiProvider(api_key="k", default_model="gemini-2.0-flash")

    with patch("backend.adapters.llm.gemini_provider.httpx.AsyncClient", return_value=mock_client):
        result = await provider.complete([{"role": "user", "content": "test"}])

    assert result.input_tokens == 200
    assert result.output_tokens == 75
    assert result.backend == "gemini"
    assert result.model_name == "Gemini 2.0 Flash"


@pytest.mark.asyncio
async def test_ollama_token_counts_parsed():
    """Ollama prompt_eval_count/eval_count CompletionResult'a yansımalı."""
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {
        "message": {"content": "ollama yanıtı"},
        "prompt_eval_count": 88,
        "eval_count": 33,
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_settings = MagicMock()
    mock_settings.ollama_base_url = "http://localhost:11434"
    mock_settings.ollama_model = "llama3"

    with patch("backend.adapters.llm.ollama_provider.settings", mock_settings):
        from backend.adapters.llm.ollama_provider import OllamaProvider
        provider = OllamaProvider(base_url="http://localhost:11434", default_model="llama3")

    with patch("backend.adapters.llm.ollama_provider.httpx.AsyncClient", return_value=mock_client):
        result = await provider.complete([{"role": "user", "content": "test"}])

    assert result.input_tokens == 88
    assert result.output_tokens == 33
    assert result.backend == "ollama"
    assert result.model_name == "Ollama/llama3"


@pytest.mark.asyncio
async def test_ollama_missing_token_counts_default_zero():
    """Ollama yanıtında eval sayaçları yoksa 0 olmalı."""
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = {"message": {"content": "ok"}}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_settings = MagicMock()
    mock_settings.ollama_base_url = "http://localhost:11434"
    mock_settings.ollama_model = "llama3"

    with patch("backend.adapters.llm.ollama_provider.settings", mock_settings):
        from backend.adapters.llm.ollama_provider import OllamaProvider
        provider = OllamaProvider(base_url="http://localhost:11434", default_model="llama3")

    with patch("backend.adapters.llm.ollama_provider.httpx.AsyncClient", return_value=mock_client):
        result = await provider.complete([{"role": "user", "content": "test"}])

    assert result.input_tokens == 0
    assert result.output_tokens == 0


def test_anthropic_unknown_model_uses_model_id_as_name():
    """Bilinmeyen model ID, model_name olarak model_id'yi kullanmalı."""
    from backend.adapters.llm.anthropic_provider import _MODEL_NAMES
    unknown = "claude-future-model-99"
    assert unknown not in _MODEL_NAMES  # önceden kayıtlı olmamalı


def test_anthropic_known_models_have_friendly_names():
    """Bilinen Anthropic modellerin insan okunur isimleri olmalı."""
    from backend.adapters.llm.anthropic_provider import _MODEL_NAMES
    assert _MODEL_NAMES["claude-3-5-haiku-20241022"] == "Haiku 4.5"
    assert _MODEL_NAMES["claude-3-5-sonnet-20241022"] == "Sonnet 4.6"
    assert _MODEL_NAMES["claude-opus-4-6"] == "Opus 4.6"


def test_gemini_known_models_have_friendly_names():
    """Bilinen Gemini modellerin insan okunur isimleri olmalı."""
    from backend.adapters.llm.gemini_provider import _MODEL_NAMES
    assert _MODEL_NAMES["gemini-2.0-flash"] == "Gemini 2.0 Flash"
    assert _MODEL_NAMES["gemini-2.5-flash-latest"] == "Gemini 2.5 Flash"
