"""BacklogFormat stratejileri — checkbox ve table format için parse/update implementasyonları.

Desteklenen formatlar
---------------------
CheckboxFormat  : - [ ] ITEM-001 Açıklama   (my-project ve legacy 99-root)
TableFormat     : | ITEM-001 | Başlık | ...  (99-root güncel formatı)

OCP: Yeni format → yeni Strategy sınıfı; mevcut sınıflar değişmez.
SRP: Format algılama, parse, write — her biri ayrı sorumlulukta.
DIP: BacklogParser somut sınıflara değil, bu modülün factory'sine bağımlıdır.
"""
from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ortak tipler
# ---------------------------------------------------------------------------

class BacklogItem(TypedDict):
    item_id: str    # "SEC-001", "SCAN-DEPTH-1", "BUG-BE-007" gibi
    text: str       # tam satır metni
    line_no: int    # 0-based satır numarası
    prefix: str     # "SEC", "SCAN", "BUG" vb. (ilk segment)


# ---------------------------------------------------------------------------
# Regex sabitleri
# ---------------------------------------------------------------------------

# Multi-segment ID: en az iki tire-ayrılmış parça; en az bir rakam içermeli.
# Eşleşenler: SEC-001, SCAN-DEPTH-1, BUG-BE-007, LOG-B001, UIGAP-001, VAL-MEDIA-1
_ITEM_ID_RE = re.compile(r"\b([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\b")

# Checkbox format satırları: - [ ] / - [~] / - [x] / - [!]
# [!] = max retry'a ulaşıp kilitlenmiş (artık denemenez)
_CHECKBOX_RE = re.compile(r"^- \[[ x~!]\]", re.MULTILINE)

# Retry limit — bu kadar denemeden sonra item [!] ile kilitlenir.
MAX_RETRIES = 3

# Retry sayacı satır sonuna eklenir: " (1/3 başarısız)"
_RETRY_RE = re.compile(r"\s*\((\d+)/\d+\s*başarısız\)")

# Table format satırları: | [🔄]ID | ...
# re.MULTILINE: ^ her satır başına eşleşir; search() ile çok satırlı içerikte de çalışır.
_IN_PROGRESS_MARKER = "🔄"
_TABLE_ROW_RE = re.compile(
    r"^\|\s*(" + re.escape(_IN_PROGRESS_MARKER) + r")?([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\s*\|",
    re.MULTILINE,
)

# Tamamlandı / ertelenmiş bölüm başlıkları — bu satırdan sonra item aramayı durdur
_COMPLETED_SECTION_RE = re.compile(
    r"^##\s+.*(?:✅|Tamamlandı|Ertelenmiş|Deferred|Kullanıcı)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

def _has_digit(s: str) -> bool:
    """ID'nin en az bir rakam içerdiğini doğrula (false-positive'leri filtreler)."""
    return any(c.isdigit() for c in s)


def _find_id(line: str) -> str | None:
    """Satırdan ilk geçerli item ID'sini döndür; bulunamazsa None."""
    for m in _ITEM_ID_RE.finditer(line):
        candidate = m.group(1)
        if _has_digit(candidate):
            return candidate
    return None


def _line_has_id(line: str, item_id: str) -> bool:
    """Satırda item_id token-sınırlı olarak geçiyor mu?

    Naive ``item_id in line`` substring eşleşmesi yanlış pozitif yaratıyor:
    örn. ``PAY-009`` IDsi başka bir item'ın açıklamasında "PAY-009"
    olarak geçtiğinde mark_done/mark_failed yanlış satırı işaretliyordu.

    Burada ID'nin iki yanı da alfanumerik/tire OLMAYAN sınırlarla
    çerçeveleniyor: ``EXTRAPAY-009``, ``PAY-0091``, ``PAY-009-FIX``
    gibi prefix/suffix uzantıları artık eşleşmiyor.
    """
    pattern = re.compile(
        r"(?<![A-Z0-9\-])" + re.escape(item_id) + r"(?![A-Z0-9\-])"
    )
    return bool(pattern.search(line))


def _atomic_write(path: Path, lines: list[str]) -> None:
    """Dosyayı .tmp aracılığıyla atomik yaz; yarım yazma riski yok."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(lines), encoding="utf-8")
    tmp.replace(path)


def _extract_retry_count(line: str) -> int:
    """Satırdaki retry sayacını döndür; yoksa 0."""
    m = _RETRY_RE.search(line)
    return int(m.group(1)) if m else 0


def _strip_retry_marker(line: str) -> str:
    """Satırdan retry sayacı işaretini (varsa) kaldır."""
    return _RETRY_RE.sub("", line)


def _append_retry_marker(line: str, count: int) -> str:
    """Satırın sonuna retry sayacını ekle; varsa önce mevcut işareti kaldırır.

    Newline'ı korur: ``"- [ ] X\n"`` → ``"- [ ] X (1/3 başarısız)\n"``.
    """
    stripped = _strip_retry_marker(line)
    has_newline = stripped.endswith("\n")
    body = stripped.rstrip("\n").rstrip()
    return f"{body} ({count}/{MAX_RETRIES} başarısız)" + ("\n" if has_newline else "")


# ---------------------------------------------------------------------------
# Format algılama (factory)
# ---------------------------------------------------------------------------

def detect_format(path: Path) -> "CheckboxFormat | TableFormat":
    """BACKLOG.md formatını algıla; uygun strateji nesnesini döndür.

    Öncelik:
      1. Checkbox satırı varsa → CheckboxFormat (my-project + eski 99-root)
      2. Tablo satırı varsa   → TableFormat (güncel 99-root)
      3. Varsayılan           → CheckboxFormat
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return CheckboxFormat()

    if _CHECKBOX_RE.search(content):
        return CheckboxFormat()
    if _TABLE_ROW_RE.search(content):
        return TableFormat()
    return CheckboxFormat()


# ---------------------------------------------------------------------------
# CheckboxFormat strateji
# ---------------------------------------------------------------------------

class CheckboxFormat:
    """Checkbox tabanlı BACKLOG.md formatını işler.

    Desteklenen satırlar:
      - [ ] ITEM-001 Açıklama   → pending
      - [~] ITEM-001 Açıklama   → in_progress
      - [x] ITEM-001 Açıklama   → done

    Legacy formatındaki köşeli parantez ID'leri de desteklenir:
      - [ ] [UIGAP-001] **Başlık** — açıklama
    """

    def get_pending_items(self, path: Path, prefix: str = "") -> list[BacklogItem]:
        """Bekleyen (- [ ]) item'ları döndür.

        Tamamlandı / Ertelenmiş / Deferred / Kullanıcı bölümlerine girilince
        item aramaya devam edilmez — bu bölümlerdeki `- [ ]` satırları
        executor tarafından çalıştırılmamalıdır.
        """
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        items: list[BacklogItem] = []
        in_completed = False

        for line_no, line in enumerate(lines):
            if _COMPLETED_SECTION_RE.match(line):
                in_completed = True
                continue
            if in_completed:
                continue
            if not line.lstrip().startswith("- [ ]"):
                continue
            item_id = _find_id(line)
            if not item_id:
                continue
            item_prefix = item_id.split("-")[0]
            if prefix and item_prefix != prefix.upper():
                continue
            items.append(
                BacklogItem(
                    item_id=item_id,
                    text=line.rstrip("\n"),
                    line_no=line_no,
                    prefix=item_prefix,
                )
            )
        return items

    def mark_in_progress(self, path: Path, item_id: str) -> bool:
        """- [ ] → - [~]."""
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for i, line in enumerate(lines):
            if _line_has_id(line, item_id) and "- [ ]" in line:
                lines[i] = line.replace("- [ ]", "- [~]", 1)
                _atomic_write(path, lines)
                logger.debug("CheckboxFormat.mark_in_progress: %s işaretlendi.", item_id)
                return True
        logger.warning("CheckboxFormat.mark_in_progress: %s bulunamadı.", item_id)
        return False

    def mark_done(self, path: Path, item_id: str) -> bool:
        """- [ ] / - [~] / - [!] → - [x]; varsa retry sayacını da temizler."""
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for i, line in enumerate(lines):
            if not _line_has_id(line, item_id):
                continue
            for marker in ("- [ ]", "- [~]", "- [!]"):
                if marker in line:
                    clean = _strip_retry_marker(line)
                    lines[i] = clean.replace(marker, "- [x]", 1)
                    _atomic_write(path, lines)
                    logger.debug("CheckboxFormat.mark_done: %s tamamlandı.", item_id)
                    return True
        logger.warning("CheckboxFormat.mark_done: %s bulunamadı.", item_id)
        return False

    def mark_failed(self, path: Path, item_id: str) -> bool:
        """- [~] → - [ ] (sayaç+1) veya - [!] (MAX_RETRIES'a ulaşıldıysa kilitle).

        Mevcut sayaç ``" (N/3 başarısız)"`` formatında satır sonuna eklenir.
        Sayaç >= MAX_RETRIES olursa item ``- [!]`` ile kilitlenir; ``get_pending_items``
        bu satırları artık döndürmez, yani tekrar denenmez.
        """
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for i, line in enumerate(lines):
            if not _line_has_id(line, item_id) or "- [~]" not in line:
                continue
            new_count = _extract_retry_count(line) + 1
            clean = _strip_retry_marker(line)
            new_marker = "- [!]" if new_count >= MAX_RETRIES else "- [ ]"
            clean = clean.replace("- [~]", new_marker, 1)
            lines[i] = _append_retry_marker(clean, new_count)
            _atomic_write(path, lines)
            logger.info(
                "CheckboxFormat.mark_failed: %s sayaç=%d/%d %s",
                item_id, new_count, MAX_RETRIES,
                "(kilitlendi)" if new_count >= MAX_RETRIES else "(yeniden denenebilir)",
            )
            return True
        logger.warning("CheckboxFormat.mark_failed: %s [~] durumunda bulunamadı.", item_id)
        return False

    def reset_stranded_items(self, path: Path) -> int:
        """`- [~]` (in_progress) takılı kalan satırları `- [ ]`'a geri çevirir.

        Önceki çalıştırma çökme/iptal sonucu yarıda kestiyse, item'lar `- [~]`
        durumunda kalır ve `get_pending_items` onları görmez (sadece `- [ ]`
        döndürür). Bu metot yeni run() başlangıcında çağrılır → orphan'lar
        yeniden pending listesine girer.

        Returns:
            Geri çevrilen satır sayısı.
        """
        try:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError:
            return 0
        changed = 0
        for i, line in enumerate(lines):
            if "- [~]" in line:
                lines[i] = line.replace("- [~]", "- [ ]", 1)
                changed += 1
        if changed:
            _atomic_write(path, lines)
            logger.info(
                "CheckboxFormat.reset_stranded_items: %d orphan item geri çevrildi (%s).",
                changed, path.name,
            )
        return changed


# ---------------------------------------------------------------------------
# TableFormat strateji
# ---------------------------------------------------------------------------

class TableFormat:
    """Markdown tablo tabanlı BACKLOG.md formatını işler (99-root güncel formatı).

    Satır formatı:
      | ITEM-001 | Başlık | Dosya | Not |

    Durum işaretleme:
      pending     : | ITEM-001 | ...
      in_progress : | 🔄ITEM-001 | ...    (🔄 prefiksi eklenir)
      done        : satır tamamen kaldırılır
      failed      : 🔄 prefiksi geri alınır → pending'e döner
    """

    def get_pending_items(self, path: Path, prefix: str = "") -> list[BacklogItem]:
        """Tablo satırlarından bekleyen item'ları döndür.

        in_progress (🔄 prefiksli) ve completed bölümlerdeki satırlar atlanır.
        """
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        items: list[BacklogItem] = []
        in_completed = False

        for line_no, line in enumerate(lines):
            # Tamamlandı bölümüne girildi mi?
            if _COMPLETED_SECTION_RE.match(line):
                in_completed = True
                continue
            if in_completed:
                continue

            m = _TABLE_ROW_RE.match(line)
            if not m:
                continue

            in_progress_flag = m.group(1)   # "🔄" veya None
            item_id = m.group(2)

            if not _has_digit(item_id):
                continue
            if in_progress_flag:
                # Zaten işleniyor — atla
                continue

            item_prefix = item_id.split("-")[0]
            if prefix and item_prefix != prefix.upper():
                continue

            items.append(
                BacklogItem(
                    item_id=item_id,
                    text=line.rstrip("\n"),
                    line_no=line_no,
                    prefix=item_prefix,
                )
            )
        return items

    def mark_in_progress(self, path: Path, item_id: str) -> bool:
        """ID hücresine 🔄 prefiksi ekle: | ITEM-001 | → | 🔄ITEM-001 |."""
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for i, line in enumerate(lines):
            m = _TABLE_ROW_RE.match(line)
            if not m or m.group(2) != item_id or m.group(1):
                # Yanlış satır, farklı ID, veya zaten in_progress
                continue
            lines[i] = line.replace(f"| {item_id}", f"| {_IN_PROGRESS_MARKER}{item_id}", 1)
            _atomic_write(path, lines)
            logger.debug("TableFormat.mark_in_progress: %s işaretlendi.", item_id)
            return True
        logger.warning("TableFormat.mark_in_progress: %s bulunamadı.", item_id)
        return False

    def mark_done(self, path: Path, item_id: str) -> bool:
        """Satırı tablodan kaldır (done = artık pending listesinde değil)."""
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for i, line in enumerate(lines):
            m = _TABLE_ROW_RE.match(line)
            if not m or m.group(2) != item_id:
                continue
            lines.pop(i)
            _atomic_write(path, lines)
            logger.debug("TableFormat.mark_done: %s satırı kaldırıldı.", item_id)
            return True
        logger.warning("TableFormat.mark_done: %s bulunamadı.", item_id)
        return False

    def mark_failed(self, path: Path, item_id: str) -> bool:
        """🔄 prefiksini kaldır → satır tekrar pending görünür."""
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for i, line in enumerate(lines):
            m = _TABLE_ROW_RE.match(line)
            if not m or m.group(2) != item_id or not m.group(1):
                # Yanlış satır, farklı ID, veya in_progress değil
                continue
            lines[i] = line.replace(
                f"| {_IN_PROGRESS_MARKER}{item_id}",
                f"| {item_id}",
                1,
            )
            _atomic_write(path, lines)
            logger.debug("TableFormat.mark_failed: %s pending'e döndü.", item_id)
            return True
        logger.warning("TableFormat.mark_failed: %s [in_progress] bulunamadı.", item_id)
        return False

    def reset_stranded_items(self, path: Path) -> int:
        """🔄 prefix ile takılı kalan satırları pending'e döndürür.

        Önceki çalıştırma çökme/iptal sonucu yarıda kestiyse, item'lar 🔄
        prefix'i ile kalır ve `get_pending_items` onları atlar. Yeni run()
        başlangıcında çağrılır → orphan'lar yeniden pending'e girer.

        Returns:
            Geri çevrilen satır sayısı.
        """
        try:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError:
            return 0
        changed = 0
        for i, line in enumerate(lines):
            m = _TABLE_ROW_RE.match(line)
            if not m or not m.group(1):
                continue
            item_id = m.group(2)
            lines[i] = line.replace(
                f"| {_IN_PROGRESS_MARKER}{item_id}",
                f"| {item_id}",
                1,
            )
            changed += 1
        if changed:
            _atomic_write(path, lines)
            logger.info(
                "TableFormat.reset_stranded_items: %d orphan item geri çevrildi (%s).",
                changed, path.name,
            )
        return changed
