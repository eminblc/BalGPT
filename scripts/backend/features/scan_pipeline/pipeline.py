"""
ScanPipeline — scanner + reviewer koordinasyonu.

Bu sınıf Claude Code (Claude Agent SDK) bağlamında çalışır.
Scanner ve reviewer agent'larını Agent tool ile başlatır.
Agent tool bu modülü import eden süreçte mevcut olmalıdır.
"""
import json
import logging
import time
import uuid
from pathlib import Path

from .config_loader import ScanConfigLoader
from .file_resolver import FileResolver
from .models import ScanConfig, ScanFinding, ReviewedFinding, ScanResult
from .scanner import ScannerOrchestrator
from .reviewer import FindingReviewer

logger = logging.getLogger(__name__)

_RUNS_DIR = Path(__file__).parent.parent.parent.parent.parent / "data" / "scan_runs"


class ScanPipeline:
    """
    Tam scan pipeline koordinatörü.

    Kullanım (Claude Code context'inde):
        pipeline = ScanPipeline()
        result = await pipeline.run("security", project_id="petekv5")
    """

    def __init__(self) -> None:
        self._config_loader = ScanConfigLoader()

    def list_scan_types(self) -> list[str]:
        """Mevcut scan tiplerini döndür."""
        return self._config_loader.list_available()

    def get_run_dir(self, run_id: str) -> Path:
        """Scan run çıktı dizini."""
        return _RUNS_DIR / run_id

    def get_recent_runs(self, limit: int = 10) -> list[dict]:
        """Son scan run'larını listele (meta.json dosyasından)."""
        if not _RUNS_DIR.exists():
            return []
        runs = []
        for d in sorted(_RUNS_DIR.iterdir(), reverse=True)[:limit]:
            meta_file = d / "meta.json"
            if meta_file.exists():
                try:
                    runs.append(json.loads(meta_file.read_text()))
                except Exception:
                    pass
        return runs

    def _write_meta(self, run_dir: Path, result: ScanResult) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "meta.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def build_scanner_prompts(
        self,
        scan_type: str,
        project_path: str,
        run_id: str,
    ) -> tuple[ScanConfig, list[dict], Path]:
        """
        Phase 1 için prompt listesi üret.
        Döndürür: (config, prompt_list, run_dir)
        prompt_list: [{"chunk_index": N, "files": [...], "prompt": "...", "output_file": "..."}]
        """
        config = self._config_loader.load(scan_type)
        run_dir = self.get_run_dir(run_id)
        orchestrator = ScannerOrchestrator(run_dir)
        prompts = self._build_prompts_sync(orchestrator, config, project_path)
        return config, prompts, run_dir

    def _build_prompts_sync(
        self,
        orchestrator: ScannerOrchestrator,
        config: ScanConfig,
        project_path: str,
    ) -> list[dict]:
        resolver = FileResolver()
        files = resolver.resolve(
            project_path,
            config["target_patterns"],
            config["exclude_patterns"],
        )
        chunks = resolver.split_into_chunks(files, chunk_size=15)
        return orchestrator._build_prompts(chunks, config, project_path)

    def collect_and_build_reviewer_prompt(
        self,
        config: ScanConfig,
        run_dir: Path,
        project_path: str,
        backlog_path: Path,
    ) -> tuple[list[ScanFinding], str]:
        """
        Phase 1 bittikten sonra:
        1. Tüm findings topla
        2. Reviewer prompt üret
        Döndürür: (findings, reviewer_prompt)
        """
        orchestrator = ScannerOrchestrator(run_dir)
        findings = orchestrator.collect_findings()

        reviewer = FindingReviewer(run_dir, backlog_path)
        prompt = reviewer.build_reviewer_prompt(config, findings)
        return findings, prompt

    def finalize(
        self,
        config: ScanConfig,
        run_dir: Path,
        findings: list[ScanFinding],
        reviewer_output: str,
        backlog_path: Path,
        run_id: str,
        project_id: str,
        project_path: str,
        started_at: float,
        dry_run: bool = False,
    ) -> ScanResult:
        """
        Phase 2 bittikten sonra:
        1. Review parse et
        2. BACKLOG'a yaz (dry_run=False ise)
        3. ScanResult döndür
        """
        reviewer = FindingReviewer(run_dir, backlog_path)
        reviewed = reviewer.parse_review_output(reviewer_output, findings)
        reviewer.write_review(reviewed)

        accepted = [r for r in reviewed if r["verdict"] == "accepted"]
        rejected = [r for r in reviewed if r["verdict"] == "rejected"]
        duplicate = [r for r in reviewed if r["verdict"] == "duplicate"]

        if not dry_run and accepted:
            # Mevcut prefix sayısını BACKLOG'dan çek
            existing_count = self._count_existing(backlog_path, config["backlog_prefix"])
            entries = reviewer.generate_backlog_entries(reviewed, config, existing_count)
            reviewer.append_to_backlog(entries, config, run_id)

        result: ScanResult = {
            "run_id": run_id,
            "scan_type": config["type"],
            "project_id": project_id,
            "project_path": project_path,
            "started_at": started_at,
            "completed_at": time.time(),
            "status": "completed",
            "total_findings": len(findings),
            "accepted": len(accepted),
            "rejected": len(rejected),
            "duplicate": len(duplicate),
            "output_dir": str(run_dir),
        }
        self._write_meta(run_dir, result)
        return result

    def _count_existing(self, backlog_path: Path, prefix: str) -> int:
        if not backlog_path.exists():
            return 0
        lines = backlog_path.read_text(encoding="utf-8").splitlines()
        return sum(1 for l in lines if f"[{prefix}-" in l)
