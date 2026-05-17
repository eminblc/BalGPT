"""Findings reviewer — accepted/rejected/duplicate kararları."""
import json
import logging
import uuid
from pathlib import Path

from .models import ScanConfig, ScanFinding, ReviewedFinding

logger = logging.getLogger(__name__)

_REVIEWER_PROMPT = """\
Sen bir kod güvenlik uzmanısın. Aşağıdaki tarama bulgularını incele.

## Değerlendirme Kriterleri
{reviewer_prompt}

## Mevcut BACKLOG (duplicate kontrolü için)
{backlog_summary}

## Bulgular (JSON)
{findings_json}

## Çıktı Formatı (YALNIZCA bu JSON array — başka hiçbir şey yazma)
[
  {{"id":"bulgu_id","verdict":"accepted","reason":"Neden kabul edildi (max 100 karakter)","backlog_id":null}},
  {{"id":"bulgu_id","verdict":"rejected","reason":"False positive — neden reddedildi"}},
  {{"id":"bulgu_id","verdict":"duplicate","reason":"BACKLOG'da {prefix}-XXX olarak var"}}
]

Kural:
- accepted: Gerçek sorun, mevcut BACKLOG'da yok, düzeltilmesi gerekiyor
- rejected: False positive, kapsam dışı, veya kod zaten doğru çalışıyor
- duplicate: BACKLOG'da veya bu taramada başka bir ID ile zaten var
Her bulguya MUTLAKA bir karar ver.
"""


class FindingReviewer:
    """SRP: findings review + BACKLOG yazma."""

    def __init__(self, output_dir: Path, backlog_path: Path) -> None:
        self._output_dir = output_dir
        self._backlog_path = backlog_path

    def build_reviewer_prompt(
        self,
        config: ScanConfig,
        findings: list[ScanFinding],
    ) -> str:
        """Reviewer agent için minimal prompt üret."""
        # BACKLOG'dan ilgili satırları çek (ilk 100 satır yeterli — tam dosya değil)
        backlog_summary = self._extract_backlog_summary(config["backlog_prefix"])

        return _REVIEWER_PROMPT.format(
            reviewer_prompt=config["reviewer_prompt"],
            backlog_summary=backlog_summary,
            findings_json=json.dumps(findings, ensure_ascii=False, indent=2),
            prefix=config["backlog_prefix"],
        )

    def _extract_backlog_summary(self, prefix: str) -> str:
        """BACKLOG'dan prefix'e ait satırları çek — token tasarrufu."""
        if not self._backlog_path.exists():
            return "(BACKLOG bulunamadı)"
        lines = self._backlog_path.read_text(encoding="utf-8").splitlines()
        relevant = [l for l in lines if prefix in l][:50]
        return "\n".join(relevant) if relevant else f"({prefix} ile başlayan madde yok)"

    def parse_review_output(
        self,
        raw_output: str,
        findings: list[ScanFinding],
    ) -> list[ReviewedFinding]:
        """Agent çıktısını parse et, ScanFinding ile birleştir."""
        try:
            # JSON array çıkar — agent bazen açıklama eklemiş olabilir
            start = raw_output.find("[")
            end = raw_output.rfind("]") + 1
            data = json.loads(raw_output[start:end])
        except Exception as e:
            logger.error("Review output parse hatası: %s", e)
            return []

        findings_by_id = {f["id"]: f for f in findings}
        reviewed: list[ReviewedFinding] = []
        for item in data:
            fid = item.get("id", "")
            reviewed.append({
                "id": fid,
                "verdict": item.get("verdict", "rejected"),
                "reason": item.get("reason", ""),
                "backlog_id": item.get("backlog_id"),
                "finding": findings_by_id.get(fid, {}),
            })
        return reviewed

    def write_review(self, reviewed: list[ReviewedFinding]) -> None:
        """Review sonuçlarını dosyaya yaz."""
        out = self._output_dir / "review.jsonl"
        out.write_text(
            json.dumps(reviewed, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def generate_backlog_entries(
        self,
        reviewed: list[ReviewedFinding],
        config: ScanConfig,
        existing_count: int = 0,
    ) -> list[str]:
        """Accepted findings'den BACKLOG satırı üret."""
        prefix = config["backlog_prefix"]
        severity_emoji = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🟢",
            "info": "⚪",
        }
        entries: list[str] = []
        counter = existing_count + 1
        for r in reviewed:
            if r["verdict"] != "accepted":
                continue
            f = r.get("finding", {})
            sev = f.get("severity", "medium")
            emoji = severity_emoji.get(sev, "🟡")
            bid = f"{prefix}-{counter:03d}"
            r["backlog_id"] = bid
            file_ref = f.get("file", "")
            line_ref = f":{f['line']}" if f.get("line") else ""
            entries.append(
                f"- [ ] [{bid}] `{file_ref}{line_ref}` — {f.get('title', r['reason'])} {emoji}"
            )
            counter += 1
        return entries

    def append_to_backlog(
        self,
        entries: list[str],
        config: ScanConfig,
        scan_run_id: str,
    ) -> None:
        """Accepted findings'i BACKLOG.md'ye ekle."""
        if not entries or not self._backlog_path.exists():
            return

        content = self._backlog_path.read_text(encoding="utf-8")
        section_header = f"\n## {config['name']} Taraması ({scan_run_id[:8]})\n"
        new_content = content.rstrip() + "\n" + section_header + "\n".join(entries) + "\n"
        self._backlog_path.write_text(new_content, encoding="utf-8")
        logger.info("BACKLOG güncellendi: %d madde eklendi", len(entries))
