"""BacklogParser — BACKLOG.md dosyasından görev item'larını okur ve günceller.

Markdown formatı:
  - [ ] SEC-001 Açıklama metni         → pending
  - [~] SEC-002 Açıklama metni         → in_progress (işleniyor)
  - [x] SEC-003 Açıklama metni         → done

SRP: Yalnızca parse ve güncelleme — çalıştırma mantığı runner.py'de.
"""
from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

_ITEM_ID_RE = re.compile(r"\b([A-Z]+-\d+)\b")


class BacklogItem(TypedDict):
    item_id: str      # "SEC-001" gibi prefix+sayı
    text: str         # tam satır metni (prefix dahil)
    line_no: int      # 0-based satır numarası
    prefix: str       # "SEC", "BUG" vb.


class BacklogParser:
    """BACKLOG.md dosyasından görev item'larını okur ve durum geçişlerini uygular.

    Tek sorumluluk: parse + atomic write — çalıştırma mantığı runner.py'de.
    """

    def get_pending_items(
        self, backlog_path: Path, prefix: str = ""
    ) -> list[BacklogItem]:
        """Bekleyen (- [ ]) backlog item'larını döndür.

        Args:
            backlog_path: BACKLOG.md dosyasının Path'i.
            prefix:       Opsiyonel prefix filtresi (örn. "SEC"). Boşsa tümü.

        Returns:
            BacklogItem listesi, orijinal dosya sırasıyla.
        """
        lines = backlog_path.read_text(encoding="utf-8").splitlines(keepends=True)
        items: list[BacklogItem] = []
        for line_no, line in enumerate(lines):
            stripped = line.lstrip()
            if not stripped.startswith("- [ ]"):
                continue
            match = _ITEM_ID_RE.search(line)
            if not match:
                continue
            item_id = match.group(1)
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

    def mark_in_progress(self, backlog_path: Path, item_id: str) -> bool:
        """- [ ] içeren satırı - [~] olarak işaretle.

        Args:
            backlog_path: BACKLOG.md dosyasının Path'i.
            item_id:      İşaretlenecek item ID'si (örn. "SEC-001").

        Returns:
            Değişiklik yapıldıysa True, item bulunamazsa False.
        """
        lines = backlog_path.read_text(encoding="utf-8").splitlines(keepends=True)
        changed = False
        for i, line in enumerate(lines):
            if item_id in line and "- [ ]" in line:
                lines[i] = line.replace("- [ ]", "- [~]", 1)
                changed = True
                break
        if changed:
            self._atomic_write(backlog_path, lines)
            logger.debug("BacklogParser.mark_in_progress: %s işaretlendi.", item_id)
        else:
            logger.warning(
                "BacklogParser.mark_in_progress: %s bulunamadı.", item_id
            )
        return changed

    def mark_done(self, backlog_path: Path, item_id: str) -> bool:
        """- [ ] veya - [~] içeren satırı - [x] olarak işaretle.

        Args:
            backlog_path: BACKLOG.md dosyasının Path'i.
            item_id:      Tamamlanan item ID'si.

        Returns:
            Değişiklik yapıldıysa True, item bulunamazsa False.
        """
        lines = backlog_path.read_text(encoding="utf-8").splitlines(keepends=True)
        changed = False
        for i, line in enumerate(lines):
            if item_id not in line:
                continue
            if "- [ ]" in line:
                lines[i] = line.replace("- [ ]", "- [x]", 1)
                changed = True
                break
            if "- [~]" in line:
                lines[i] = line.replace("- [~]", "- [x]", 1)
                changed = True
                break
        if changed:
            self._atomic_write(backlog_path, lines)
            logger.debug("BacklogParser.mark_done: %s tamamlandı.", item_id)
        else:
            logger.warning("BacklogParser.mark_done: %s bulunamadı.", item_id)
        return changed

    def mark_failed(self, backlog_path: Path, item_id: str) -> bool:
        """- [~] satırını - [ ] olarak geri al (yeniden denenebilir).

        Args:
            backlog_path: BACKLOG.md dosyasının Path'i.
            item_id:      Geri alınacak item ID'si.

        Returns:
            Değişiklik yapıldıysa True, item bulunamazsa False.
        """
        lines = backlog_path.read_text(encoding="utf-8").splitlines(keepends=True)
        changed = False
        for i, line in enumerate(lines):
            if item_id in line and "- [~]" in line:
                lines[i] = line.replace("- [~]", "- [ ]", 1)
                changed = True
                break
        if changed:
            self._atomic_write(backlog_path, lines)
            logger.debug(
                "BacklogParser.mark_failed: %s geri alındı (retry edilebilir).", item_id
            )
        else:
            logger.warning(
                "BacklogParser.mark_failed: %s [~] durumunda bulunamadı.", item_id
            )
        return changed

    def _atomic_write(self, path: Path, lines: list[str]) -> None:
        """Dosyayı atomic write ile güncelle (yarım yazma riski yok).

        Args:
            path:  Hedef dosya Path'i.
            lines: Yazılacak satır listesi (satır sonları korunmuş).
        """
        tmp = path.with_suffix(".tmp")
        tmp.write_text("".join(lines), encoding="utf-8")
        tmp.replace(path)
