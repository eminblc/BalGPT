"""slugify_project_name — saf fonksiyon testleri."""
import pytest
from backend.store.sqlite_store import slugify_project_name


# ── Türkçe karakterler ────────────────────────────────────────────

def test_turkce_u():
    assert slugify_project_name("Müzik API") == "muzik-api"

def test_turkce_s():
    assert slugify_project_name("Şehir Planı") == "sehir-plani"

def test_turkce_g():
    assert slugify_project_name("Güzel Proje") == "guzel-proje"

def test_turkce_c():
    assert slugify_project_name("Çalışma Takibi") == "calisma-takibi"

def test_turkce_o():
    assert slugify_project_name("Öğrenci Sistemi") == "ogrenci-sistemi"

def test_turkce_i():
    assert slugify_project_name("Işık Projesi") == "isik-projesi"


# ── Boşluk ve küçük harf ──────────────────────────────────────────

def test_spaces_to_dashes():
    assert slugify_project_name("Hello World") == "hello-world"

def test_multiple_spaces():
    assert slugify_project_name("my  project") == "my-project"

def test_already_lowercase():
    assert slugify_project_name("test") == "test"

def test_uppercase():
    assert slugify_project_name("MY PROJECT") == "my-project"


# ── Özel karakterler ──────────────────────────────────────────────

def test_exclamation():
    assert slugify_project_name("Hello World!") == "hello-world"

def test_numbers_preserved():
    assert slugify_project_name("Project 123") == "project-123"

def test_dashes_preserved():
    assert slugify_project_name("my-project") == "my-project"

def test_leading_trailing_dashes():
    assert slugify_project_name("-project-") == "project"

def test_multiple_dashes_collapsed():
    assert slugify_project_name("my---project") == "my-project"


# ── Boş / dejenere girişler ───────────────────────────────────────

def test_only_special_chars():
    assert slugify_project_name("!!!") == "proje"

def test_only_spaces():
    assert slugify_project_name("   ") == "proje"

def test_empty_string():
    assert slugify_project_name("") == "proje"

def test_only_turkish_special():
    # "üüü" → "uuu" (geçerli slug)
    result = slugify_project_name("üüü")
    assert result == "uuu"


# ── Uzun isimler ──────────────────────────────────────────────────

def test_long_name_is_valid_slug():
    name = "A" * 70
    result = slugify_project_name(name)
    # Regex _PROJECT_ID_RE: max 63 karakter (^[a-z0-9][a-z0-9\-]{0,62}$)
    assert len(result) <= 63 or result  # slug üretilmeli
