"""Paralel scanner agent orkestratörü."""
import json
import logging
from pathlib import Path

from .models import ScanConfig, ScanFinding
from .file_resolver import FileResolver

logger = logging.getLogger(__name__)

# Minimal prompt şablonu — token bütçesi sıkı, CLAUDE.md/conv history yok.
# Sadece kriterler + JSON kuralı. Dosya listesi ve içerikleri runtime'da eklenir.
_SCANNER_AGENT_PROMPT = """\
{scanner_prompt}

Sadece JSON array dön (markdown/açıklama yok). Şema:
{{"id":str8,"file":str,"line":int,"severity":"critical|high|medium|low|info","category":str,"title":str,"description":str,"snippet":str}}
Yoksa []. Max {max_findings}.
"""


class ScannerOrchestrator:
    """Paralel sub-scanner agent'ları yönetir, findings toplar."""

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir
        self._resolver = FileResolver()

    async def run(
        self,
        config: ScanConfig,
        project_path: str,
    ) -> list[ScanFinding]:
        """
        1. Dosyaları chunk'lara böl
        2. Her chunk için Agent tool ile sub-agent başlat (paralel)
        3. Findings'leri topla, output_dir'e yaz
        4. Birleşik liste döndür
        """
        files = self._resolver.resolve(
            project_path,
            config["target_patterns"],
            config["exclude_patterns"],
        )
        if not files:
            logger.warning("ScannerOrchestrator: taranacak dosya bulunamadı")
            return []

        chunks = self._resolver.split_into_chunks(
            files, chunk_size=config.get("chunk_size", 5)
        )
        logger.info(
            "ScannerOrchestrator: %d dosya → %d chunk → paralel agent",
            len(files), len(chunks),
        )

        findings_dir = self._output_dir / "findings"
        findings_dir.mkdir(parents=True, exist_ok=True)

        # Paralel agent çalıştırma — Agent tool bu context'te mevcut değil;
        # bu metod orchestrator bağlamında (Claude Code CLI içinde) çağrılır.
        # Her chunk için prompt üretip döndür — çağıran taraf Agent tool ile başlatır.
        prompts = self._build_prompts(chunks, config, project_path)
        return prompts  # pipeline.py Agent tool ile bunları başlatır

    def _build_prompts(
        self,
        chunks: list[list[str]],
        config: ScanConfig,
        project_path: str,
    ) -> list[dict]:
        """Her chunk için agent prompt dict üret."""
        result = []
        for i, chunk in enumerate(chunks):
            prompt = _SCANNER_AGENT_PROMPT.format(
                scanner_prompt=config["scanner_prompt"],
                max_findings=config.get("max_findings_per_agent", 50),
            )
            result.append({
                "chunk_index": i,
                "files": chunk,
                "project_path": project_path,
                "prompt": prompt,
                "output_file": str(self._output_dir / "findings" / f"chunk_{i:03d}.jsonl"),
            })
        return result

    def collect_findings(self) -> list[ScanFinding]:
        """output_dir/findings/*.jsonl dosyalarını oku, birleştir."""
        findings: list[ScanFinding] = []
        findings_dir = self._output_dir / "findings"
        if not findings_dir.exists():
            return []
        chunk_files = sorted(findings_dir.glob("chunk_*.jsonl"))
        logger.info(
            "ScannerOrchestrator: %d chunk dosyası okunuyor (run_dir=%s)",
            len(chunk_files), self._output_dir,
        )
        for f in chunk_files:
            try:
                raw = f.read_text(encoding="utf-8")
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    # LLM markdown fence içine sarmışsa ilk [ … son ] al
                    start = raw.find("[")
                    end = raw.rfind("]") + 1
                    data = json.loads(raw[start:end]) if start != -1 and end > start else []
                if isinstance(data, list):
                    findings.extend(data)
            except Exception as e:
                logger.warning("Findings okuma hatası %s: %s", f, e)
        logger.info(
            "ScannerOrchestrator: %d chunk dosyasından %d bulgu toplandı",
            len(chunk_files), len(findings),
        )
        return findings

    def write_findings(self, chunk_index: int, findings: list[ScanFinding]) -> None:
        """Tek chunk findings'ini dosyaya yaz."""
        findings_dir = self._output_dir / "findings"
        findings_dir.mkdir(parents=True, exist_ok=True)
        out = findings_dir / f"chunk_{chunk_index:03d}.jsonl"
        out.write_text(json.dumps(findings, ensure_ascii=False), encoding="utf-8")
