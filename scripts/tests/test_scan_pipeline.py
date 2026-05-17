"""scan_pipeline paketi unit testleri — tmp_path + in-memory data."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Yardımcı sabit veriler ──────────────────────────────────────────────────

_MINIMAL_CONFIG = {
    "type": "security",
    "name": "Test Taraması",
    "scanner_prompt": "SQL injection ara",
    "target_patterns": ["**/*.py"],
    "exclude_patterns": ["*.test.py"],
    "reviewer_prompt": "Her bulguyu değerlendir",
    "backlog_prefix": "SEC",
    "max_findings_per_agent": 10,
}

_SAMPLE_FINDING: dict = {
    "id": "abc12345",
    "file": "app/main.py",
    "line": 42,
    "severity": "high",
    "category": "injection",
    "title": "SQL Injection riski",
    "description": "Ham string interpolation kullanılıyor.",
    "snippet": "query = f'SELECT * FROM users WHERE id={user_id}'",
}

_SAMPLE_FINDING_2: dict = {
    "id": "def67890",
    "file": "app/auth.py",
    "line": 10,
    "severity": "critical",
    "category": "auth",
    "title": "Auth bypass",
    "description": "Token doğrulaması eksik.",
    "snippet": "if token:  # always true",
}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. MODELS — TypedDict construction
# ═══════════════════════════════════════════════════════════════════════════════

class TestModels:
    """ScanFinding, ReviewedFinding, ScanResult TypedDicts oluşturulabilir."""

    def test_scan_finding_construction(self):
        from backend.features.scan_pipeline.models import ScanFinding
        f: ScanFinding = {
            "id": "abc12345",
            "file": "app/main.py",
            "line": 42,
            "severity": "high",
            "category": "injection",
            "title": "SQL Injection",
            "description": "Risk.",
            "snippet": "code snippet",
        }
        assert f["id"] == "abc12345"
        assert f["severity"] == "high"

    def test_reviewed_finding_construction(self):
        from backend.features.scan_pipeline.models import ReviewedFinding
        r: ReviewedFinding = {
            "id": "abc12345",
            "verdict": "accepted",
            "reason": "Gerçek sorun",
            "backlog_id": "SEC-001",
            "finding": _SAMPLE_FINDING,
        }
        assert r["verdict"] == "accepted"
        assert r["backlog_id"] == "SEC-001"

    def test_scan_result_construction(self):
        import time
        from backend.features.scan_pipeline.models import ScanResult
        now = time.time()
        result: ScanResult = {
            "run_id": "run-001",
            "scan_type": "security",
            "project_id": "proj-1",
            "project_path": "/tmp/proj",
            "started_at": now,
            "completed_at": now + 10,
            "status": "completed",
            "total_findings": 5,
            "accepted": 3,
            "rejected": 1,
            "duplicate": 1,
            "output_dir": "/tmp/scan_runs/run-001",
        }
        assert result["status"] == "completed"
        assert result["accepted"] == 3

    def test_scan_config_construction(self):
        from backend.features.scan_pipeline.models import ScanConfig
        cfg: ScanConfig = dict(_MINIMAL_CONFIG)  # type: ignore[assignment]
        assert cfg["backlog_prefix"] == "SEC"
        assert cfg["max_findings_per_agent"] == 10


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ScanConfigLoader
# ═══════════════════════════════════════════════════════════════════════════════

class TestScanConfigLoader:
    """Config yükleyici testleri — tmp_path ile gerçek dosyalar."""

    def _make_loader_with_dir(self, configs_dir: Path):
        """_CONFIGS_DIR patch'li loader döndür."""
        from backend.features.scan_pipeline import config_loader as cl_module
        with patch.object(cl_module, "_CONFIGS_DIR", configs_dir):
            from backend.features.scan_pipeline.config_loader import ScanConfigLoader
            return ScanConfigLoader(), cl_module

    def test_load_raises_when_file_missing(self, tmp_path):
        from backend.features.scan_pipeline import config_loader as cl_module
        from backend.features.scan_pipeline.config_loader import ScanConfigLoader

        with patch.object(cl_module, "_CONFIGS_DIR", tmp_path):
            loader = ScanConfigLoader()
            with pytest.raises(FileNotFoundError):
                loader.load("nonexistent_type")

    def test_load_returns_correct_config(self, tmp_path):
        from backend.features.scan_pipeline import config_loader as cl_module
        from backend.features.scan_pipeline.config_loader import ScanConfigLoader

        cfg_file = tmp_path / "security.json"
        cfg_file.write_text(json.dumps(_MINIMAL_CONFIG), encoding="utf-8")

        with patch.object(cl_module, "_CONFIGS_DIR", tmp_path):
            loader = ScanConfigLoader()
            result = loader.load("security")

        assert result["type"] == "security"
        assert result["backlog_prefix"] == "SEC"
        assert result["max_findings_per_agent"] == 10
        assert "SQL injection" in result["scanner_prompt"]

    def test_load_returns_all_required_fields(self, tmp_path):
        from backend.features.scan_pipeline import config_loader as cl_module
        from backend.features.scan_pipeline.config_loader import ScanConfigLoader

        cfg_file = tmp_path / "bugfix.json"
        bugfix_cfg = {**_MINIMAL_CONFIG, "type": "bugfix", "backlog_prefix": "BUG"}
        cfg_file.write_text(json.dumps(bugfix_cfg), encoding="utf-8")

        with patch.object(cl_module, "_CONFIGS_DIR", tmp_path):
            loader = ScanConfigLoader()
            result = loader.load("bugfix")

        assert result["type"] == "bugfix"
        assert result["backlog_prefix"] == "BUG"

    def test_list_available_returns_scan_types(self, tmp_path):
        from backend.features.scan_pipeline import config_loader as cl_module
        from backend.features.scan_pipeline.config_loader import ScanConfigLoader

        (tmp_path / "security.json").write_text("{}", encoding="utf-8")
        (tmp_path / "bugfix.json").write_text("{}", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")

        with patch.object(cl_module, "_CONFIGS_DIR", tmp_path):
            loader = ScanConfigLoader()
            available = loader.list_available()

        assert set(available) == {"security", "bugfix"}

    def test_list_available_empty_when_dir_missing(self, tmp_path):
        from backend.features.scan_pipeline import config_loader as cl_module
        from backend.features.scan_pipeline.config_loader import ScanConfigLoader

        missing_dir = tmp_path / "does_not_exist"
        with patch.object(cl_module, "_CONFIGS_DIR", missing_dir):
            loader = ScanConfigLoader()
            assert loader.list_available() == []

    def test_list_available_empty_dir(self, tmp_path):
        from backend.features.scan_pipeline import config_loader as cl_module
        from backend.features.scan_pipeline.config_loader import ScanConfigLoader

        empty_dir = tmp_path / "configs"
        empty_dir.mkdir()

        with patch.object(cl_module, "_CONFIGS_DIR", empty_dir):
            loader = ScanConfigLoader()
            assert loader.list_available() == []


# ═══════════════════════════════════════════════════════════════════════════════
# 3. FileResolver
# ═══════════════════════════════════════════════════════════════════════════════

class TestFileResolver:
    """Glob pattern çözümleme + chunk testleri — tmp_path ile gerçek dosyalar."""

    def _make_resolver(self):
        from backend.features.scan_pipeline.file_resolver import FileResolver
        return FileResolver()

    def test_resolve_returns_matching_files(self, tmp_path):
        resolver = self._make_resolver()
        (tmp_path / "a.py").write_text("# code", encoding="utf-8")
        (tmp_path / "b.py").write_text("# code", encoding="utf-8")
        (tmp_path / "c.txt").write_text("text", encoding="utf-8")

        result = resolver.resolve(str(tmp_path), ["*.py"], [])
        assert set(result) == {"a.py", "b.py"}

    def test_resolve_returns_sorted_list(self, tmp_path):
        resolver = self._make_resolver()
        (tmp_path / "z.py").write_text("", encoding="utf-8")
        (tmp_path / "a.py").write_text("", encoding="utf-8")
        (tmp_path / "m.py").write_text("", encoding="utf-8")

        result = resolver.resolve(str(tmp_path), ["*.py"], [])
        assert result == sorted(result)

    def test_resolve_excludes_patterns(self, tmp_path):
        resolver = self._make_resolver()
        (tmp_path / "main.py").write_text("", encoding="utf-8")
        (tmp_path / "main.test.py").write_text("", encoding="utf-8")
        (tmp_path / "utils.py").write_text("", encoding="utf-8")

        result = resolver.resolve(str(tmp_path), ["*.py"], ["*.test.py"])
        assert "main.test.py" not in result
        assert "main.py" in result
        assert "utils.py" in result

    def test_resolve_recursive_glob(self, tmp_path):
        resolver = self._make_resolver()
        sub = tmp_path / "src" / "app"
        sub.mkdir(parents=True)
        (sub / "main.py").write_text("", encoding="utf-8")
        (tmp_path / "root.py").write_text("", encoding="utf-8")

        result = resolver.resolve(str(tmp_path), ["**/*.py"], [])
        # Hem root hem de alt dizin dosyaları döner
        assert any("main.py" in r for r in result)
        assert "root.py" in result

    def test_resolve_returns_relative_paths(self, tmp_path):
        resolver = self._make_resolver()
        sub = tmp_path / "pkg"
        sub.mkdir()
        (sub / "mod.py").write_text("", encoding="utf-8")

        result = resolver.resolve(str(tmp_path), ["**/*.py"], [])
        # Tüm sonuçlar göreceli olmalı (tmp_path ile başlamamalı)
        for r in result:
            assert not r.startswith(str(tmp_path))

    def test_resolve_empty_when_no_match(self, tmp_path):
        resolver = self._make_resolver()
        (tmp_path / "file.txt").write_text("", encoding="utf-8")

        result = resolver.resolve(str(tmp_path), ["*.py"], [])
        assert result == []

    def test_resolve_skips_directories(self, tmp_path):
        resolver = self._make_resolver()
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (tmp_path / "real.py").write_text("", encoding="utf-8")

        result = resolver.resolve(str(tmp_path), ["*"], [])
        # Dizinler sonuçta yer almaz
        assert "subdir" not in result

    def test_split_into_chunks_correct_size(self):
        resolver = self._make_resolver()
        files = [f"file_{i}.py" for i in range(7)]
        chunks = resolver.split_into_chunks(files, chunk_size=3)
        assert len(chunks) == 3
        assert chunks[0] == ["file_0.py", "file_1.py", "file_2.py"]
        assert chunks[1] == ["file_3.py", "file_4.py", "file_5.py"]
        assert chunks[2] == ["file_6.py"]

    def test_split_into_chunks_exact_divisible(self):
        resolver = self._make_resolver()
        files = [f"f{i}.py" for i in range(6)]
        chunks = resolver.split_into_chunks(files, chunk_size=2)
        assert len(chunks) == 3
        for chunk in chunks:
            assert len(chunk) == 2

    def test_split_into_chunks_single_chunk(self):
        resolver = self._make_resolver()
        files = ["a.py", "b.py"]
        chunks = resolver.split_into_chunks(files, chunk_size=10)
        assert len(chunks) == 1
        assert chunks[0] == ["a.py", "b.py"]

    def test_split_into_chunks_empty_list(self):
        resolver = self._make_resolver()
        chunks = resolver.split_into_chunks([], chunk_size=5)
        assert chunks == []

    def test_split_into_chunks_default_size(self):
        resolver = self._make_resolver()
        files = [f"f{i}.py" for i in range(20)]
        chunks = resolver.split_into_chunks(files)
        # default chunk_size=15
        assert len(chunks) == 2
        assert len(chunks[0]) == 15
        assert len(chunks[1]) == 5


# ═══════════════════════════════════════════════════════════════════════════════
# 4. ScannerOrchestrator
# ═══════════════════════════════════════════════════════════════════════════════

class TestScannerOrchestrator:
    """Scanner prompt üretimi ve findings toplama testleri."""

    def _make_orchestrator(self, output_dir: Path):
        from backend.features.scan_pipeline.scanner import ScannerOrchestrator
        return ScannerOrchestrator(output_dir)

    # ── build_prompts ────────────────────────────────────────────────────────

    def test_build_prompts_returns_correct_count(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        chunks = [["a.py", "b.py"], ["c.py"]]
        prompts = orch._build_prompts(chunks, _MINIMAL_CONFIG, "/tmp/proj")
        assert len(prompts) == 2

    def test_build_prompts_contains_scanner_prompt_text(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        chunks = [["main.py"]]
        prompts = orch._build_prompts(chunks, _MINIMAL_CONFIG, "/tmp/proj")
        # scanner_prompt içeriği prompt'a dahil edilmeli
        assert "SQL injection" in prompts[0]["prompt"]

    def test_build_prompts_contains_project_path(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        chunks = [["main.py"]]
        prompts = orch._build_prompts(chunks, _MINIMAL_CONFIG, "/tmp/myproject")
        assert "/tmp/myproject" in prompts[0]["prompt"]

    def test_build_prompts_contains_file_names(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        chunks = [["src/auth.py", "src/db.py"]]
        prompts = orch._build_prompts(chunks, _MINIMAL_CONFIG, "/tmp/proj")
        assert "src/auth.py" in prompts[0]["prompt"]
        assert "src/db.py" in prompts[0]["prompt"]

    def test_build_prompts_chunk_index_set(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        chunks = [["a.py"], ["b.py"], ["c.py"]]
        prompts = orch._build_prompts(chunks, _MINIMAL_CONFIG, "/tmp/proj")
        for i, p in enumerate(prompts):
            assert p["chunk_index"] == i

    def test_build_prompts_output_file_path(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        chunks = [["a.py"]]
        prompts = orch._build_prompts(chunks, _MINIMAL_CONFIG, "/tmp/proj")
        assert "chunk_000.jsonl" in prompts[0]["output_file"]

    def test_build_prompts_files_key_populated(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        chunk_files = ["x.py", "y.py"]
        prompts = orch._build_prompts([chunk_files], _MINIMAL_CONFIG, "/tmp/proj")
        assert prompts[0]["files"] == chunk_files

    def test_build_prompts_empty_chunks_returns_empty(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        prompts = orch._build_prompts([], _MINIMAL_CONFIG, "/tmp/proj")
        assert prompts == []

    # ── collect_findings ────────────────────────────────────────────────────

    def test_collect_findings_empty_when_no_jsonl(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        # findings/ dizini bile yok
        result = orch.collect_findings()
        assert result == []

    def test_collect_findings_empty_when_dir_empty(self, tmp_path):
        findings_dir = tmp_path / "findings"
        findings_dir.mkdir()
        orch = self._make_orchestrator(tmp_path)
        result = orch.collect_findings()
        assert result == []

    def test_collect_findings_parses_valid_jsonl(self, tmp_path):
        findings_dir = tmp_path / "findings"
        findings_dir.mkdir()
        findings = [_SAMPLE_FINDING, _SAMPLE_FINDING_2]
        (findings_dir / "chunk_000.jsonl").write_text(
            json.dumps(findings), encoding="utf-8"
        )

        orch = self._make_orchestrator(tmp_path)
        result = orch.collect_findings()
        assert len(result) == 2
        assert result[0]["id"] == "abc12345"
        assert result[1]["id"] == "def67890"

    def test_collect_findings_merges_multiple_jsonl(self, tmp_path):
        findings_dir = tmp_path / "findings"
        findings_dir.mkdir()
        (findings_dir / "chunk_000.jsonl").write_text(
            json.dumps([_SAMPLE_FINDING]), encoding="utf-8"
        )
        (findings_dir / "chunk_001.jsonl").write_text(
            json.dumps([_SAMPLE_FINDING_2]), encoding="utf-8"
        )

        orch = self._make_orchestrator(tmp_path)
        result = orch.collect_findings()
        assert len(result) == 2

    def test_collect_findings_skips_invalid_json(self, tmp_path):
        findings_dir = tmp_path / "findings"
        findings_dir.mkdir()
        (findings_dir / "chunk_000.jsonl").write_text(
            "NOT VALID JSON", encoding="utf-8"
        )
        (findings_dir / "chunk_001.jsonl").write_text(
            json.dumps([_SAMPLE_FINDING]), encoding="utf-8"
        )

        orch = self._make_orchestrator(tmp_path)
        # Hatalı dosya atlanır, geçerli dosya okunur
        result = orch.collect_findings()
        assert len(result) == 1
        assert result[0]["id"] == "abc12345"

    def test_collect_findings_skips_non_list_json(self, tmp_path):
        findings_dir = tmp_path / "findings"
        findings_dir.mkdir()
        (findings_dir / "chunk_000.jsonl").write_text(
            json.dumps({"key": "value"}), encoding="utf-8"
        )

        orch = self._make_orchestrator(tmp_path)
        result = orch.collect_findings()
        assert result == []

    # ── write_findings ───────────────────────────────────────────────────────

    def test_write_findings_creates_file(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        orch.write_findings(0, [_SAMPLE_FINDING])
        out = tmp_path / "findings" / "chunk_000.jsonl"
        assert out.exists()

    def test_write_findings_content_readable(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        orch.write_findings(1, [_SAMPLE_FINDING_2])
        out = tmp_path / "findings" / "chunk_001.jsonl"
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data[0]["id"] == "def67890"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. FindingReviewer
# ═══════════════════════════════════════════════════════════════════════════════

class TestFindingReviewer:
    """Reviewer prompt üretimi, parse ve backlog yazma testleri."""

    def _make_reviewer(self, output_dir: Path, backlog_path: Path):
        from backend.features.scan_pipeline.reviewer import FindingReviewer
        return FindingReviewer(output_dir, backlog_path)

    # ── build_reviewer_prompt ────────────────────────────────────────────────

    def test_build_reviewer_prompt_not_empty(self, tmp_path):
        backlog = tmp_path / "BACKLOG.md"
        backlog.write_text("", encoding="utf-8")
        reviewer = self._make_reviewer(tmp_path, backlog)
        prompt = reviewer.build_reviewer_prompt(_MINIMAL_CONFIG, [_SAMPLE_FINDING])
        assert len(prompt) > 0

    def test_build_reviewer_prompt_contains_reviewer_text(self, tmp_path):
        backlog = tmp_path / "BACKLOG.md"
        backlog.write_text("", encoding="utf-8")
        reviewer = self._make_reviewer(tmp_path, backlog)
        prompt = reviewer.build_reviewer_prompt(_MINIMAL_CONFIG, [_SAMPLE_FINDING])
        assert "değerlendir" in prompt

    def test_build_reviewer_prompt_contains_findings_json(self, tmp_path):
        backlog = tmp_path / "BACKLOG.md"
        backlog.write_text("", encoding="utf-8")
        reviewer = self._make_reviewer(tmp_path, backlog)
        prompt = reviewer.build_reviewer_prompt(_MINIMAL_CONFIG, [_SAMPLE_FINDING])
        assert "abc12345" in prompt
        assert "SQL Injection riski" in prompt

    def test_build_reviewer_prompt_uses_backlog_summary(self, tmp_path):
        backlog = tmp_path / "BACKLOG.md"
        backlog.write_text("- [SEC-001] Existing issue\n- [BUG-001] Bug\n", encoding="utf-8")
        reviewer = self._make_reviewer(tmp_path, backlog)
        prompt = reviewer.build_reviewer_prompt(_MINIMAL_CONFIG, [_SAMPLE_FINDING])
        assert "SEC-001" in prompt

    def test_build_reviewer_prompt_backlog_missing(self, tmp_path):
        backlog = tmp_path / "BACKLOG.md"  # var olmayan dosya
        reviewer = self._make_reviewer(tmp_path, backlog)
        prompt = reviewer.build_reviewer_prompt(_MINIMAL_CONFIG, [_SAMPLE_FINDING])
        # BACKLOG yoksa placeholder gösterilmeli, hata fırlatmamalı
        assert "BACKLOG bulunamadı" in prompt

    def test_build_reviewer_prompt_no_findings(self, tmp_path):
        backlog = tmp_path / "BACKLOG.md"
        backlog.write_text("", encoding="utf-8")
        reviewer = self._make_reviewer(tmp_path, backlog)
        prompt = reviewer.build_reviewer_prompt(_MINIMAL_CONFIG, [])
        # Boş findings listesi ile de prompt üretilmeli
        assert len(prompt) > 0

    # ── parse_review_output ──────────────────────────────────────────────────

    def test_parse_review_output_empty_when_no_json(self, tmp_path):
        reviewer = self._make_reviewer(tmp_path, tmp_path / "BACKLOG.md")
        result = reviewer.parse_review_output("Bu bir açıklama metnidir.", [])
        assert result == []

    def test_parse_review_output_returns_empty_on_invalid_json(self, tmp_path):
        reviewer = self._make_reviewer(tmp_path, tmp_path / "BACKLOG.md")
        result = reviewer.parse_review_output("[INVALID JSON", [])
        assert result == []

    def test_parse_review_output_parses_accepted(self, tmp_path):
        findings = [_SAMPLE_FINDING]
        raw = json.dumps([
            {"id": "abc12345", "verdict": "accepted", "reason": "Gerçek sorun", "backlog_id": None}
        ])
        reviewer = self._make_reviewer(tmp_path, tmp_path / "BACKLOG.md")
        result = reviewer.parse_review_output(raw, findings)
        assert len(result) == 1
        assert result[0]["verdict"] == "accepted"
        assert result[0]["id"] == "abc12345"

    def test_parse_review_output_parses_rejected(self, tmp_path):
        findings = [_SAMPLE_FINDING]
        raw = json.dumps([
            {"id": "abc12345", "verdict": "rejected", "reason": "False positive"}
        ])
        reviewer = self._make_reviewer(tmp_path, tmp_path / "BACKLOG.md")
        result = reviewer.parse_review_output(raw, findings)
        assert result[0]["verdict"] == "rejected"

    def test_parse_review_output_parses_duplicate(self, tmp_path):
        findings = [_SAMPLE_FINDING]
        raw = json.dumps([
            {"id": "abc12345", "verdict": "duplicate", "reason": "SEC-001'de var"}
        ])
        reviewer = self._make_reviewer(tmp_path, tmp_path / "BACKLOG.md")
        result = reviewer.parse_review_output(raw, findings)
        assert result[0]["verdict"] == "duplicate"

    def test_parse_review_output_links_finding(self, tmp_path):
        """parse_review_output, ReviewedFinding'e ilgili ScanFinding'i bağlar."""
        findings = [_SAMPLE_FINDING, _SAMPLE_FINDING_2]
        raw = json.dumps([
            {"id": "abc12345", "verdict": "accepted", "reason": "ok"},
            {"id": "def67890", "verdict": "rejected", "reason": "fp"},
        ])
        reviewer = self._make_reviewer(tmp_path, tmp_path / "BACKLOG.md")
        result = reviewer.parse_review_output(raw, findings)
        accepted = next(r for r in result if r["id"] == "abc12345")
        assert accepted["finding"]["title"] == "SQL Injection riski"

    def test_parse_review_output_with_surrounding_text(self, tmp_path):
        """Agent bazen JSON çevresine açıklama ekler — tolere edilmeli."""
        findings = [_SAMPLE_FINDING]
        json_part = json.dumps([
            {"id": "abc12345", "verdict": "accepted", "reason": "valid"}
        ])
        raw = f"İşte değerlendirmem:\n{json_part}\nUmarım yardımcı olur."
        reviewer = self._make_reviewer(tmp_path, tmp_path / "BACKLOG.md")
        result = reviewer.parse_review_output(raw, findings)
        assert len(result) == 1
        assert result[0]["verdict"] == "accepted"

    # ── generate_backlog_entries ─────────────────────────────────────────────

    def test_generate_backlog_entries_accepted_only(self, tmp_path):
        reviewed = [
            {"id": "a1", "verdict": "accepted", "reason": "ok", "backlog_id": None, "finding": _SAMPLE_FINDING},
            {"id": "a2", "verdict": "rejected", "reason": "fp", "backlog_id": None, "finding": _SAMPLE_FINDING_2},
        ]
        reviewer = self._make_reviewer(tmp_path, tmp_path / "BACKLOG.md")
        entries = reviewer.generate_backlog_entries(reviewed, _MINIMAL_CONFIG, existing_count=0)
        assert len(entries) == 1
        assert "SEC-001" in entries[0]

    def test_generate_backlog_entries_skips_rejected(self, tmp_path):
        reviewed = [
            {"id": "r1", "verdict": "rejected", "reason": "fp", "backlog_id": None, "finding": _SAMPLE_FINDING},
            {"id": "r2", "verdict": "duplicate", "reason": "dup", "backlog_id": None, "finding": _SAMPLE_FINDING_2},
        ]
        reviewer = self._make_reviewer(tmp_path, tmp_path / "BACKLOG.md")
        entries = reviewer.generate_backlog_entries(reviewed, _MINIMAL_CONFIG, existing_count=0)
        assert entries == []

    def test_generate_backlog_entries_sequential_ids(self, tmp_path):
        reviewed = [
            {"id": "a1", "verdict": "accepted", "reason": "ok", "backlog_id": None, "finding": _SAMPLE_FINDING},
            {"id": "a2", "verdict": "accepted", "reason": "ok", "backlog_id": None, "finding": _SAMPLE_FINDING_2},
        ]
        reviewer = self._make_reviewer(tmp_path, tmp_path / "BACKLOG.md")
        entries = reviewer.generate_backlog_entries(reviewed, _MINIMAL_CONFIG, existing_count=0)
        assert len(entries) == 2
        assert "SEC-001" in entries[0]
        assert "SEC-002" in entries[1]

    def test_generate_backlog_entries_existing_count_offset(self, tmp_path):
        reviewed = [
            {"id": "a1", "verdict": "accepted", "reason": "ok", "backlog_id": None, "finding": _SAMPLE_FINDING},
        ]
        reviewer = self._make_reviewer(tmp_path, tmp_path / "BACKLOG.md")
        entries = reviewer.generate_backlog_entries(reviewed, _MINIMAL_CONFIG, existing_count=5)
        # existing_count=5 → ilk yeni ID SEC-006 olmalı
        assert "SEC-006" in entries[0]

    def test_generate_backlog_entries_contains_file_ref(self, tmp_path):
        reviewed = [
            {"id": "a1", "verdict": "accepted", "reason": "ok", "backlog_id": None, "finding": _SAMPLE_FINDING},
        ]
        reviewer = self._make_reviewer(tmp_path, tmp_path / "BACKLOG.md")
        entries = reviewer.generate_backlog_entries(reviewed, _MINIMAL_CONFIG)
        assert "app/main.py" in entries[0]

    def test_generate_backlog_entries_contains_line_ref(self, tmp_path):
        reviewed = [
            {"id": "a1", "verdict": "accepted", "reason": "ok", "backlog_id": None, "finding": _SAMPLE_FINDING},
        ]
        reviewer = self._make_reviewer(tmp_path, tmp_path / "BACKLOG.md")
        entries = reviewer.generate_backlog_entries(reviewed, _MINIMAL_CONFIG)
        assert ":42" in entries[0]

    def test_generate_backlog_entries_severity_emoji_high(self, tmp_path):
        reviewed = [
            {"id": "a1", "verdict": "accepted", "reason": "ok", "backlog_id": None, "finding": _SAMPLE_FINDING},
        ]
        reviewer = self._make_reviewer(tmp_path, tmp_path / "BACKLOG.md")
        entries = reviewer.generate_backlog_entries(reviewed, _MINIMAL_CONFIG)
        assert "🟠" in entries[0]

    def test_generate_backlog_entries_severity_emoji_critical(self, tmp_path):
        reviewed = [
            {"id": "a1", "verdict": "accepted", "reason": "ok", "backlog_id": None, "finding": _SAMPLE_FINDING_2},
        ]
        reviewer = self._make_reviewer(tmp_path, tmp_path / "BACKLOG.md")
        entries = reviewer.generate_backlog_entries(reviewed, _MINIMAL_CONFIG)
        assert "🔴" in entries[0]

    # ── write_review ─────────────────────────────────────────────────────────

    def test_write_review_creates_file(self, tmp_path):
        reviewed = [
            {"id": "a1", "verdict": "accepted", "reason": "ok", "backlog_id": "SEC-001",
             "finding": _SAMPLE_FINDING}
        ]
        reviewer = self._make_reviewer(tmp_path, tmp_path / "BACKLOG.md")
        reviewer.write_review(reviewed)
        out = tmp_path / "review.jsonl"
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data[0]["id"] == "a1"

    # ── append_to_backlog ────────────────────────────────────────────────────

    def test_append_to_backlog_adds_entries(self, tmp_path):
        backlog = tmp_path / "BACKLOG.md"
        backlog.write_text("# Mevcut BACKLOG\n", encoding="utf-8")
        reviewed = [
            {"id": "a1", "verdict": "accepted", "reason": "ok", "backlog_id": None, "finding": _SAMPLE_FINDING},
        ]
        reviewer = self._make_reviewer(tmp_path, backlog)
        entries = reviewer.generate_backlog_entries(reviewed, _MINIMAL_CONFIG)
        reviewer.append_to_backlog(entries, _MINIMAL_CONFIG, "run-abc123")
        content = backlog.read_text(encoding="utf-8")
        assert "SEC-001" in content
        assert "Test Taraması" in content

    def test_append_to_backlog_noop_when_backlog_missing(self, tmp_path):
        backlog = tmp_path / "BACKLOG.md"  # mevcut değil
        entries = ["- [SEC-001] Something 🟠"]
        reviewer = self._make_reviewer(tmp_path, backlog)
        # Hata fırlatmamalı, sessizce atlanmalı
        reviewer.append_to_backlog(entries, _MINIMAL_CONFIG, "run-001")
        assert not backlog.exists()

    def test_append_to_backlog_noop_when_empty_entries(self, tmp_path):
        backlog = tmp_path / "BACKLOG.md"
        original = "# Mevcut\n"
        backlog.write_text(original, encoding="utf-8")
        reviewer = self._make_reviewer(tmp_path, backlog)
        reviewer.append_to_backlog([], _MINIMAL_CONFIG, "run-001")
        assert backlog.read_text(encoding="utf-8") == original


# ═══════════════════════════════════════════════════════════════════════════════
# 6. ScanPipeline
# ═══════════════════════════════════════════════════════════════════════════════

class TestScanPipeline:
    """Pipeline koordinatör testleri — ScanConfigLoader + FileResolver mock'lanır."""

    def _make_pipeline(self):
        from backend.features.scan_pipeline.pipeline import ScanPipeline
        return ScanPipeline()

    # ── list_scan_types ───────────────────────────────────────────────────────

    def test_list_scan_types_delegates_to_loader(self, tmp_path):
        from backend.features.scan_pipeline import config_loader as cl_module
        from backend.features.scan_pipeline.pipeline import ScanPipeline

        (tmp_path / "security.json").write_text("{}", encoding="utf-8")
        (tmp_path / "bugfix.json").write_text("{}", encoding="utf-8")

        with patch.object(cl_module, "_CONFIGS_DIR", tmp_path):
            pipeline = ScanPipeline()
            types = pipeline.list_scan_types()

        assert set(types) == {"security", "bugfix"}

    def test_list_scan_types_empty_when_no_configs(self, tmp_path):
        from backend.features.scan_pipeline import config_loader as cl_module
        from backend.features.scan_pipeline.pipeline import ScanPipeline

        empty_dir = tmp_path / "configs"
        empty_dir.mkdir()
        with patch.object(cl_module, "_CONFIGS_DIR", empty_dir):
            pipeline = ScanPipeline()
            assert pipeline.list_scan_types() == []

    # ── get_recent_runs ───────────────────────────────────────────────────────

    def test_get_recent_runs_empty_when_runs_dir_missing(self, tmp_path):
        from backend.features.scan_pipeline import pipeline as pl_module
        from backend.features.scan_pipeline.pipeline import ScanPipeline

        missing = tmp_path / "no_runs_dir"
        with patch.object(pl_module, "_RUNS_DIR", missing):
            pipeline = ScanPipeline()
            assert pipeline.get_recent_runs() == []

    def test_get_recent_runs_empty_when_dir_empty(self, tmp_path):
        from backend.features.scan_pipeline import pipeline as pl_module
        from backend.features.scan_pipeline.pipeline import ScanPipeline

        runs_dir = tmp_path / "scan_runs"
        runs_dir.mkdir()
        with patch.object(pl_module, "_RUNS_DIR", runs_dir):
            pipeline = ScanPipeline()
            assert pipeline.get_recent_runs() == []

    def test_get_recent_runs_parses_meta_json(self, tmp_path):
        from backend.features.scan_pipeline import pipeline as pl_module
        from backend.features.scan_pipeline.pipeline import ScanPipeline

        runs_dir = tmp_path / "scan_runs"
        run_a = runs_dir / "run-aaa"
        run_a.mkdir(parents=True)
        meta = {"run_id": "run-aaa", "scan_type": "security", "status": "completed"}
        (run_a / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

        with patch.object(pl_module, "_RUNS_DIR", runs_dir):
            pipeline = ScanPipeline()
            runs = pipeline.get_recent_runs()

        assert len(runs) == 1
        assert runs[0]["run_id"] == "run-aaa"
        assert runs[0]["status"] == "completed"

    def test_get_recent_runs_skips_dirs_without_meta(self, tmp_path):
        from backend.features.scan_pipeline import pipeline as pl_module
        from backend.features.scan_pipeline.pipeline import ScanPipeline

        runs_dir = tmp_path / "scan_runs"
        (runs_dir / "run-with-meta").mkdir(parents=True)
        (runs_dir / "run-with-meta" / "meta.json").write_text(
            json.dumps({"run_id": "run-with-meta"}), encoding="utf-8"
        )
        (runs_dir / "run-no-meta").mkdir()  # meta.json yok

        with patch.object(pl_module, "_RUNS_DIR", runs_dir):
            pipeline = ScanPipeline()
            runs = pipeline.get_recent_runs()

        assert len(runs) == 1
        assert runs[0]["run_id"] == "run-with-meta"

    def test_get_recent_runs_skips_invalid_meta_json(self, tmp_path):
        from backend.features.scan_pipeline import pipeline as pl_module
        from backend.features.scan_pipeline.pipeline import ScanPipeline

        runs_dir = tmp_path / "scan_runs"
        run_bad = runs_dir / "run-bad"
        run_bad.mkdir(parents=True)
        (run_bad / "meta.json").write_text("NOT JSON", encoding="utf-8")

        with patch.object(pl_module, "_RUNS_DIR", runs_dir):
            pipeline = ScanPipeline()
            runs = pipeline.get_recent_runs()

        assert runs == []

    def test_get_recent_runs_respects_limit(self, tmp_path):
        from backend.features.scan_pipeline import pipeline as pl_module
        from backend.features.scan_pipeline.pipeline import ScanPipeline

        runs_dir = tmp_path / "scan_runs"
        for i in range(5):
            run_dir = runs_dir / f"run-{i:03d}"
            run_dir.mkdir(parents=True)
            (run_dir / "meta.json").write_text(
                json.dumps({"run_id": f"run-{i:03d}"}), encoding="utf-8"
            )

        with patch.object(pl_module, "_RUNS_DIR", runs_dir):
            pipeline = ScanPipeline()
            runs = pipeline.get_recent_runs(limit=3)

        assert len(runs) == 3

    # ── build_scanner_prompts ─────────────────────────────────────────────────

    def test_build_scanner_prompts_returns_prompts(self, tmp_path):
        """FileResolver + ScanConfigLoader mock'lu — prompt listesi döner."""
        from backend.features.scan_pipeline import pipeline as pl_module
        from backend.features.scan_pipeline import config_loader as cl_module
        from backend.features.scan_pipeline.pipeline import ScanPipeline

        # 1) Config dosyasını tmp_path'e yaz
        cfg_dir = tmp_path / "configs"
        cfg_dir.mkdir()
        (cfg_dir / "security.json").write_text(json.dumps(_MINIMAL_CONFIG), encoding="utf-8")

        # 2) Proje kökünde taranacak dosya yarat
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "main.py").write_text("code", encoding="utf-8")

        runs_dir = tmp_path / "scan_runs"

        config_to_use = {**_MINIMAL_CONFIG, "target_patterns": ["*.py"], "exclude_patterns": []}

        with patch.object(cl_module, "_CONFIGS_DIR", cfg_dir), \
             patch.object(pl_module, "_RUNS_DIR", runs_dir):
            pipeline = ScanPipeline()
            # load() gerçek dosyadan döner ama target_patterns *.py ile proj'u tarar
            with patch.object(pipeline._config_loader, "load", return_value=config_to_use):
                cfg, prompts, run_dir = pipeline.build_scanner_prompts(
                    "security", str(proj), "run-test-001"
                )

        assert isinstance(prompts, list)
        assert len(prompts) >= 1
        assert "chunk_index" in prompts[0]
        assert "prompt" in prompts[0]

    def test_build_scanner_prompts_no_files_returns_empty(self, tmp_path):
        """Dosya yoksa chunk listesi boş — prompt listesi de boş."""
        from backend.features.scan_pipeline import pipeline as pl_module
        from backend.features.scan_pipeline.pipeline import ScanPipeline

        runs_dir = tmp_path / "scan_runs"
        proj = tmp_path / "empty_proj"
        proj.mkdir()

        config_no_match = {**_MINIMAL_CONFIG, "target_patterns": ["*.ts"], "exclude_patterns": []}

        with patch.object(pl_module, "_RUNS_DIR", runs_dir):
            pipeline = ScanPipeline()
            with patch.object(pipeline._config_loader, "load", return_value=config_no_match):
                cfg, prompts, run_dir = pipeline.build_scanner_prompts(
                    "security", str(proj), "run-empty-001"
                )

        assert prompts == []

    # ── get_run_dir ───────────────────────────────────────────────────────────

    def test_get_run_dir_returns_path(self, tmp_path):
        from backend.features.scan_pipeline import pipeline as pl_module
        from backend.features.scan_pipeline.pipeline import ScanPipeline

        runs_dir = tmp_path / "scan_runs"
        with patch.object(pl_module, "_RUNS_DIR", runs_dir):
            pipeline = ScanPipeline()
            run_dir = pipeline.get_run_dir("my-run-id")

        assert str(run_dir).endswith("my-run-id")
        assert isinstance(run_dir, Path)

    # ── finalize ───────────────────────────────────────────────────────────────

    def test_finalize_returns_scan_result(self, tmp_path):
        """finalize() ScanResult TypedDict döndürür."""
        import time
        from backend.features.scan_pipeline import pipeline as pl_module
        from backend.features.scan_pipeline.pipeline import ScanPipeline

        runs_dir = tmp_path / "scan_runs"
        run_dir = runs_dir / "run-fin-001"
        run_dir.mkdir(parents=True)
        backlog = tmp_path / "BACKLOG.md"
        backlog.write_text("", encoding="utf-8")

        reviewer_json = json.dumps([
            {"id": "abc12345", "verdict": "accepted", "reason": "ok", "backlog_id": None},
            {"id": "def67890", "verdict": "rejected", "reason": "fp"},
        ])

        with patch.object(pl_module, "_RUNS_DIR", runs_dir):
            pipeline = ScanPipeline()
            result = pipeline.finalize(
                config=_MINIMAL_CONFIG,
                run_dir=run_dir,
                findings=[_SAMPLE_FINDING, _SAMPLE_FINDING_2],
                reviewer_output=reviewer_json,
                backlog_path=backlog,
                run_id="run-fin-001",
                project_id="proj-test",
                project_path="/tmp/proj",
                started_at=time.time() - 5,
                dry_run=True,  # BACKLOG'a yazma
            )

        assert result["run_id"] == "run-fin-001"
        assert result["status"] == "completed"
        assert result["total_findings"] == 2
        assert result["accepted"] == 1
        assert result["rejected"] == 1
        assert result["duplicate"] == 0

    def test_finalize_writes_meta_json(self, tmp_path):
        """finalize() run_dir/meta.json yazar."""
        import time
        from backend.features.scan_pipeline import pipeline as pl_module
        from backend.features.scan_pipeline.pipeline import ScanPipeline

        runs_dir = tmp_path / "scan_runs"
        run_dir = runs_dir / "run-meta-001"
        run_dir.mkdir(parents=True)
        backlog = tmp_path / "BACKLOG.md"
        backlog.write_text("", encoding="utf-8")

        with patch.object(pl_module, "_RUNS_DIR", runs_dir):
            pipeline = ScanPipeline()
            pipeline.finalize(
                config=_MINIMAL_CONFIG,
                run_dir=run_dir,
                findings=[],
                reviewer_output="[]",
                backlog_path=backlog,
                run_id="run-meta-001",
                project_id="proj-x",
                project_path="/tmp/px",
                started_at=time.time(),
                dry_run=True,
            )

        meta_file = run_dir / "meta.json"
        assert meta_file.exists()
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert meta["run_id"] == "run-meta-001"

    # ── _count_existing ───────────────────────────────────────────────────────

    def test_count_existing_returns_zero_when_no_backlog(self, tmp_path):
        from backend.features.scan_pipeline.pipeline import ScanPipeline
        pipeline = ScanPipeline()
        count = pipeline._count_existing(tmp_path / "BACKLOG.md", "SEC")
        assert count == 0

    def test_count_existing_counts_prefix_occurrences(self, tmp_path):
        from backend.features.scan_pipeline.pipeline import ScanPipeline
        backlog = tmp_path / "BACKLOG.md"
        backlog.write_text(
            "- [SEC-001] Issue one\n- [SEC-002] Issue two\n- [BUG-001] Bug\n",
            encoding="utf-8",
        )
        pipeline = ScanPipeline()
        assert pipeline._count_existing(backlog, "SEC") == 2
        assert pipeline._count_existing(backlog, "BUG") == 1
        assert pipeline._count_existing(backlog, "HT") == 0
