"""Scan pipeline veri modelleri."""
from typing import TypedDict, Literal


class ScanConfig(TypedDict):
    type: str                    # 'security' | 'bugfix' | 'helpticket'
    name: str
    scanner_prompt: str          # Sub-scanner agent'a gönderilecek prompt şablonu
    target_patterns: list[str]   # glob: ["src/**/*.ts"]
    exclude_patterns: list[str]  # ["*.spec.ts", "node_modules"]
    reviewer_prompt: str         # Reviewer agent prompt şablonu
    backlog_prefix: str          # 'SEC' | 'BUG' | 'HT'
    max_findings_per_agent: int  # Token limiti için
    max_chars_per_file: int      # Dosya başına maksimum karakter (varsayılan: 8000)
    max_output_tokens: int       # LLM çıktı token bütçesi (varsayılan: 2048)
    chunk_size: int              # Chunk başına dosya sayısı (varsayılan: 5)
    concurrency: int             # Eş zamanlı chunk sayısı (varsayılan: 5)


class ScanFinding(TypedDict, total=False):
    id: str            # uuid4 kısa (8 karakter)
    file: str          # Göreceli dosya yolu
    line: int | None
    severity: str      # 'critical' | 'high' | 'medium' | 'low' | 'info'
    category: str      # 'injection' | 'auth' | 'ssrf' | 'race' | vs.
    title: str         # Kısa başlık (max 80 karakter)
    description: str   # 1-2 cümle açıklama
    snippet: str | None  # İlgili kod satırı(ları) — max 3 satır


class ReviewedFinding(TypedDict, total=False):
    id: str
    verdict: str       # 'accepted' | 'rejected' | 'duplicate'
    reason: str        # Kısa gerekçe (max 100 karakter)
    backlog_id: str | None  # Kabul edildiyse: 'SEC-001'
    finding: ScanFinding


class ScanResult(TypedDict):
    run_id: str
    scan_type: str
    project_id: str
    project_path: str
    started_at: float
    completed_at: float | None
    status: str        # 'running' | 'completed' | 'failed'
    total_findings: int
    accepted: int
    rejected: int
    duplicate: int
    output_dir: str    # data/scan_runs/{run_id}/
