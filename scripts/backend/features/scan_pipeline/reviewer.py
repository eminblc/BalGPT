"""Findings reviewer — accepted/rejected/duplicate kararları."""
import datetime
import fcntl
import json
import logging
import re
from pathlib import Path

from .models import ScanConfig, ScanFinding, ReviewedFinding

logger = logging.getLogger(__name__)

# Markdown fallback için verdict regex'leri (modül seviyesi — bir kez derlenir)
_VERDICT_RE = re.compile(
    r"\b(ACCEPTED|REJECTED|DUPLICATE|KABUL|REDDED[İI]LD[İI]|REDDED[İI]LME|"
    r"REDDET|YİNELENDİ|YINELENDI|TEKRAR|DUPLIKAT)\b",
    re.IGNORECASE,
)
_VERDICT_NORMALIZE: dict[str, str] = {
    "accepted": "accepted",
    "kabul": "accepted",
    "rejected": "rejected",
    "reddedildi": "rejected",
    "reddedildi̇": "rejected",
    "reddedilme": "rejected",
    "reddet": "rejected",
    "duplicate": "duplicate",
    "yinelendi": "duplicate",
    "yinelendi̇": "duplicate",
    "tekrar": "duplicate",
    "duplikat": "duplicate",
}
_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*\n?(.*?)```", re.DOTALL)

# Parse hatası log dosyası: outputs/logs/reviewer_parse_errors.log
_PARSE_ERROR_LOG = Path(__file__).parents[4] / "outputs" / "logs" / "reviewer_parse_errors.log"

# Batch'ler arasında DEĞİŞMEYEN kısım — system role'e taşınır ve
# cache_system=True ile ephemeral prompt cache'ten yararlanır (ilk batch cache
# yazar, sonraki batch'ler %10 input fiyatı öder). BACKLOG özeti 60K karaktere
# kadar çıkabildiği için bu ayrım batch başına ciddi token tasarrufu sağlar.
_REVIEWER_SYSTEM_PROMPT = """\
Tarama bulgularını incele. Kriterler:
{reviewer_prompt}

BACKLOG (duplicate kontrolü):
{backlog_summary}

Kullanıcı mesajında bulgular JSON array olarak gelir.
Sadece JSON array dön (markdown/fence/açıklama yok). Her bulguya karar ver:
[{{"id":"...","verdict":"accepted|rejected|duplicate","reason":"≤120ch","backlog_id":null}}]

Kurallar:
- accepted: gerçek sorun, BACKLOG'da yok. low/info dahil tüm şiddetler — düşük şiddet ≠ false positive.
- rejected: false positive, scope dışı, kod zaten doğru.
- duplicate: BACKLOG'da veya bu batch'te aynı sorun var (prefix: {prefix}).
"""

# Batch başına DEĞİŞEN kısım — user role'de kalır, cache'i kırmaz.
_REVIEWER_USER_PROMPT = """\
{already_accepted_section}Bulgular:
{findings_json}
"""


class FindingReviewer:
    """SRP: findings review + BACKLOG yazma."""

    def __init__(self, output_dir: Path, backlog_path: Path) -> None:
        self._output_dir = output_dir
        self._backlog_path = backlog_path

    def build_reviewer_system_prompt(self, config: ScanConfig) -> str:
        """Batch'ler arasında sabit kalan system prompt'u üret.

        Kriterler + BACKLOG özeti + karar kuralları içerir. Aynı run içinde
        her batch için byte-byte aynı döner (BACKLOG finalize'a kadar
        değişmez) → cache_system=True ile prompt cache hit garantilenir.
        Caller (ReviewerAgent) bunu döngü öncesi bir kez üretip yeniden kullanır.
        """
        backlog_summary = self._extract_backlog_summary(config["backlog_prefix"])
        return _REVIEWER_SYSTEM_PROMPT.format(
            reviewer_prompt=config["reviewer_prompt"],
            backlog_summary=backlog_summary,
            prefix=config["backlog_prefix"],
        )

    @staticmethod
    def build_reviewer_user_prompt(
        findings: list[ScanFinding],
        already_accepted: list[tuple[str, str]] | None = None,
    ) -> str:
        """Batch'e özgü user prompt'u üret (önceki kabul listesi + bulgular JSON).

        Args:
            findings:         Bu batch'teki bulgular.
            already_accepted: Önceki batch'lerde kabul edilen (file, title) çiftleri.
                              Aynı (file, title) bulgu bu batch'te "duplicate" olarak işaretlenmeli.
        """
        if already_accepted:
            lines = "\n".join(
                f"  - file: {f}, title: {t}" for f, t in already_accepted
            )
            already_accepted_section = (
                f"## Bu Taramada Önceki Batch'lerde Kabul Edilenler "
                f"(aynı file+title → duplicate)\n{lines}\n\n"
            )
        else:
            already_accepted_section = ""

        # snippet alanı reviewer kararı için gereksiz — token tasarrufu için çıkar
        compact_findings = [
            {k: v for k, v in f.items() if k != "snippet"}
            for f in findings
        ]
        return _REVIEWER_USER_PROMPT.format(
            already_accepted_section=already_accepted_section,
            findings_json=json.dumps(compact_findings, ensure_ascii=False, indent=2),
        )

    def build_reviewer_prompt(
        self,
        config: ScanConfig,
        findings: list[ScanFinding],
        already_accepted: list[tuple[str, str]] | None = None,
    ) -> str:
        """Tek parça reviewer prompt (system + user birleşik).

        Legacy tek-çağrı akışı (ScanRunner / pipeline.collect_and_build_reviewer_prompt)
        için korunur; batch akışı system/user parçalarını ayrı kullanır.
        """
        return (
            self.build_reviewer_system_prompt(config)
            + "\n"
            + self.build_reviewer_user_prompt(findings, already_accepted)
        )

    def _extract_backlog_summary(self, prefix: str) -> str:
        """BACKLOG'dan aktif item satırlarını kompakt formatta çek.

        Önce mevcut scan prefix'ine ait tüm satırları (sınırsız) alır, ardından
        diğer prefix'lerden en fazla 200 satır ekler — cross-prefix duplicate
        tespiti için. Toplam çıktı 60 000 karakteri aşarsa kesilir.
        """
        if not self._backlog_path.exists():
            return "(BACKLOG bulunamadı)"

        item_re = re.compile(
            r"^\s*-\s*"
            r"(?:\[[ x~!]\]\s+)?"
            r"\[?([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\]?\s*"
            r"(.{0,80})"
        )

        same_prefix: list[str] = []
        other_prefix: list[str] = []

        for line in self._backlog_path.read_text(encoding="utf-8").splitlines():
            m = item_re.match(line)
            if not m:
                continue
            item_id = m.group(1)
            title = m.group(2).strip().rstrip("—-* ").rstrip("*").strip().replace("**", "")
            entry = f"{item_id}: {title}"
            if item_id.startswith(f"{prefix}-"):
                same_prefix.append(entry)
            elif len(other_prefix) < 200:
                other_prefix.append(entry)

        lines = same_prefix + other_prefix
        result = "\n".join(lines)
        if len(result) > 60_000:
            result = result[:60_000] + "\n... (kesildi)"
        return result if result else "(BACKLOG'da aktif item yok)"

    def parse_review_output(
        self,
        raw_output: str,
        findings: list[ScanFinding],
    ) -> list[ReviewedFinding]:
        """Agent çıktısını parse et, ScanFinding ile birleştir.

        Strateji (sıralı):
        1. **JSON kandidatları**: ``` ```json...``` ``` fence → balanced-bracket scan →
           find/rfind fallback. İlk başarılı parse kullanılır.
        2. **Markdown prose fallback**: Bridge bazen JSON yerine markdown döndürür.
           Her bulgu ID'sinin tüm geçişlerini tarar; en yakın verdict kelimesini
           (bold/plain/TR/EN) seçer.
        """
        findings_by_id = {f["id"]: f for f in findings}

        # --- Yol 1: JSON kandidatları ---
        # İlk parse-edilebilir JSON array kazanır (boş [] da geçerli yanıttır).
        for candidate in self._iter_json_candidates(raw_output):
            try:
                data = json.loads(candidate)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(data, list):
                continue
            reviewed: list[ReviewedFinding] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                fid = item.get("id", "")
                # "verdict" veya "decision" anahtarını tolere et
                verdict = item.get("verdict") or item.get("decision")
                if verdict is None:
                    logger.warning(
                        "FindingReviewer: id=%r için 'verdict'/'decision' anahtarı yok"
                        " — 'needs_review' atandı",
                        fid,
                    )
                    verdict = "needs_review"
                reviewed.append({
                    "id": fid,
                    "verdict": verdict,
                    "reason": item.get("reason", ""),
                    "backlog_id": item.get("backlog_id"),
                    "finding": findings_by_id.get(fid, {}),
                })
            return reviewed

        # --- Yol 2: Markdown prose fallback ---
        # Tüm JSON kandidatları parse edilemedi — uyarı + hata log dosyasına yaz
        logger.warning(
            "FindingReviewer: JSON parse tamamen başarısız — markdown fallback devreye girdi."
            " Ham LLM çıktısı reviewer_parse_errors.log'a yazılıyor."
        )
        self._log_parse_error(raw_output)

        if not findings:
            return []

        reviewed_md: list[ReviewedFinding] = []
        unparsed_count = 0
        for finding in findings:
            verdict_str, reason = self._extract_verdict_from_markdown(
                raw_output, finding["id"]
            )
            if reason == "(parse edilemedi)":
                unparsed_count += 1
            reviewed_md.append({
                "id": finding["id"],
                "verdict": verdict_str,
                "reason": reason,
                "backlog_id": None,
                "finding": finding,
            })

        if reviewed_md:
            logger.info(
                "FindingReviewer: markdown prose parse — %d verdict, %d parse edilemedi",
                len(reviewed_md), unparsed_count,
            )
            return reviewed_md

        logger.error("Review output parse hatası — JSON ve markdown parse başarısız")
        return []

    # ── JSON kandidat çıkartımı ─────────────────────────────────────────────

    @staticmethod
    def _iter_json_candidates(raw: str):
        """JSON adaylarını öncelik sırasıyla üret.

        Sıra:
        1. ```json ... ``` veya ``` ... ``` fence içeriği (içinde `[` varsa)
        2. Balanced-bracket scan: ilk `[` ten itibaren tırnak/escape-aware tarama
        3. Legacy: find('[') ... rfind(']')+1  (geriye uyumluluk)
        """
        seen: set[str] = set()

        def emit(text: str):
            t = text.strip()
            if t and t not in seen and t.startswith("["):
                seen.add(t)
                yield t

        # 1) Fenced kod blokları
        for m in _FENCE_RE.finditer(raw):
            body = m.group(1)
            if "[" in body and "]" in body:
                yield from emit(body)

        # 2) Balanced-bracket scan — tüm top-level [...] blokları
        for balanced in FindingReviewer._iter_balanced_arrays(raw):
            yield from emit(balanced)

        # 3) Legacy find/rfind fallback
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start != -1 and end > start:
            yield from emit(raw[start:end])

    @staticmethod
    def _iter_balanced_arrays(raw: str):
        """Top-level dengelenmiş `[...]` bloklarını sırayla yield eder.

        Tırnak/escape farkındalıdır — string içindeki `[` `]` sayılmaz.
        İlk başarısız aday parse edilemezse bir sonrakine geçilebilsin diye
        birden çok blok yield edilir.
        """
        i = 0
        n = len(raw)
        while i < n:
            start = raw.find("[", i)
            if start == -1:
                return
            depth = 0
            in_str = False
            escape = False
            closed = -1
            for j in range(start, n):
                ch = raw[j]
                if in_str:
                    if escape:
                        escape = False
                    elif ch == "\\":
                        escape = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                    if depth == 0:
                        closed = j
                        break
            if closed == -1:
                return  # dengelenmemiş açık bracket — daha ileri gitmenin anlamı yok
            yield raw[start: closed + 1]
            i = closed + 1

    # ── Markdown verdict çıkartımı ──────────────────────────────────────────

    @staticmethod
    def _extract_verdict_from_markdown(
        raw: str, fid: str
    ) -> tuple[str, str]:
        """ID için markdown çıktısından (verdict, reason) tahmin et.

        - ID'nin tüm geçişleri taranır.
        - Her geçiş için ileri 600 karakterlik pencerede verdict aranır.
        - En yakın verdict (mesafe) kazanır.
        - Verdict bulunamazsa ('rejected', '(parse edilemedi)') döner.
        """
        positions: list[int] = []
        cursor = 0
        while True:
            p = raw.find(fid, cursor)
            if p == -1:
                break
            positions.append(p)
            cursor = p + len(fid)
            if len(positions) >= 10:  # absurd guard
                break

        best: tuple[int, str, str] | None = None  # (distance, verdict, reason)
        for pos in positions:
            window = raw[pos: pos + 600]
            m = _VERDICT_RE.search(window)
            if not m:
                continue
            word = m.group(1).lower()
            verdict = _VERDICT_NORMALIZE.get(word, "rejected")
            after = window[m.end():].lstrip(" \t:—-*_`\n")
            # İlk anlamlı satırı reason yap
            first_line = ""
            for line in after.splitlines():
                stripped = line.strip(" \t*_`>#")
                if stripped:
                    first_line = stripped[:120]
                    break
            distance = m.start()
            if best is None or distance < best[0]:
                best = (distance, verdict, first_line)

        if best is None:
            logger.warning(
                "FindingReviewer: id=%r için markdown'da verdict bulunamadı"
                " — 'needs_review' atandı",
                fid,
            )
            return ("needs_review", "(parse edilemedi)")
        return (best[1], best[2] or "(verdict bulundu, gerekçe yok)")

    @staticmethod
    def _log_parse_error(raw_output: str) -> None:
        """Parse edilemeyen ham LLM çıktısını reviewer_parse_errors.log'a ekle."""
        try:
            _PARSE_ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
            sep = "=" * 60
            timestamp = datetime.datetime.now().isoformat(timespec="seconds")
            with _PARSE_ERROR_LOG.open("a", encoding="utf-8") as f:
                f.write(f"\n{sep}\n{timestamp}\n{sep}\n{raw_output}\n")
        except OSError as exc:
            logger.warning("reviewer_parse_errors.log yazılamadı: %s", exc)

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

    def append_reviewed_to_backlog(
        self,
        reviewed: list[ReviewedFinding],
        config: ScanConfig,
        scan_run_id: str,
    ) -> None:
        """Kabul edilen bulguları atomik olarak BACKLOG'a ekle.

        _count_existing → generate_backlog_entries → append_to_backlog üçlüsü
        tek dosya kilidi altında çalışır; paralel scan yazımlarında ID çakışması
        ve duplicate yazma önlenir.
        """
        if not self._backlog_path.exists():
            return
        accepted = [r for r in reviewed if r["verdict"] == "accepted"]
        if not accepted:
            return

        lock_path = self._backlog_path.with_suffix(".lock")
        with lock_path.open("a") as lock_fh:
            fcntl.flock(lock_fh, fcntl.LOCK_EX)
            try:
                content = self._backlog_path.read_text(encoding="utf-8")
                prefix = config["backlog_prefix"]
                existing_count = sum(1 for l in content.splitlines() if f"[{prefix}-" in l)
                entries = self.generate_backlog_entries(reviewed, config, existing_count)
                new_entries = self._filter_existing(entries, content)
                if not new_entries:
                    logger.info(
                        "BACKLOG güncellenmedi: tüm %d madde zaten mevcut", len(entries)
                    )
                    return
                section_header = f"\n## {config['name']} Taraması ({scan_run_id[:8]})\n"
                new_content = (
                    content.rstrip()
                    + "\n"
                    + section_header
                    + "\n".join(new_entries)
                    + "\n"
                )
                self._backlog_path.write_text(new_content, encoding="utf-8")
                skipped = len(entries) - len(new_entries)
                logger.info(
                    "BACKLOG güncellendi: %d madde eklendi, %d duplicate atlandı",
                    len(new_entries),
                    skipped,
                )
            finally:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)

    # `` `file:line` `` veya `` `file` `` backtick referansını yakala
    _FILE_REF_RE = re.compile(r"`([^`]+)`")

    def append_to_backlog(
        self,
        entries: list[str],
        config: ScanConfig,
        scan_run_id: str,
    ) -> None:
        """Accepted findings'i BACKLOG.md'ye ekle.

        Dosya kilidi (fcntl) ile concurrent write race'i önlenir.
        Her entry için backtick içindeki file:line referansı BACKLOG'da
        zaten varsa o entry atlanır — LLM reviewer'ın kaçırdığı
        duplicate'lere karşı son savunma hattı.
        """
        if not entries or not self._backlog_path.exists():
            return

        lock_path = self._backlog_path.with_suffix(".lock")
        with lock_path.open("a") as lock_fh:
            fcntl.flock(lock_fh, fcntl.LOCK_EX)
            try:
                content = self._backlog_path.read_text(encoding="utf-8")
                new_entries = self._filter_existing(entries, content)
                if not new_entries:
                    logger.info(
                        "BACKLOG güncellenmedi: tüm %d madde zaten mevcut", len(entries)
                    )
                    return
                section_header = f"\n## {config['name']} Taraması ({scan_run_id[:8]})\n"
                new_content = (
                    content.rstrip()
                    + "\n"
                    + section_header
                    + "\n".join(new_entries)
                    + "\n"
                )
                self._backlog_path.write_text(new_content, encoding="utf-8")
                skipped = len(entries) - len(new_entries)
                logger.info(
                    "BACKLOG güncellendi: %d madde eklendi, %d duplicate atlandı",
                    len(new_entries),
                    skipped,
                )
            finally:
                fcntl.flock(lock_fh, fcntl.LOCK_UN)

    def _filter_existing(self, entries: list[str], backlog_content: str) -> list[str]:
        """BACKLOG'da zaten var olan file:line referansına sahip entry'leri filtrele."""
        new: list[str] = []
        for entry in entries:
            m = self._FILE_REF_RE.search(entry)
            if m and m.group(1) in backlog_content:
                logger.debug("BACKLOG dedup: atlandı — zaten mevcut: %s", m.group(1))
                continue
            new.append(entry)
        return new
