"""ExportTaskRegistry — async export görevi durum takibi.

SRP: Yalnızca in-flight export görevlerinin durumunu saklar.
     Export iş mantığı ExportService'e, HTTP yönlendirme backup_api'ye aittir.

Not: ClassVar dict bilinçli olarak tercih edildi — bu sınıfa özel görev
     durumu, uygulama genelinde paylaşılan runtime state değildir.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, Literal

from ._manifest import BackupManifest


# ---------------------------------------------------------------------------
# ExportTask — tek bir async export görevinin anlık görüntüsü
# ---------------------------------------------------------------------------


@dataclass
class ExportTask:
    """Bir async export görevi için durum ve meta veri — SRP."""

    task_id: str
    status: Literal["running", "done", "error"]
    created_at: str
    manifest: BackupManifest | None = None
    error: str | None = None
    output_path: Path | None = None

    @classmethod
    def new(cls, task_id: str | None = None) -> "ExportTask":
        """Yeni, çalışan durumda bir görev örneği oluşturur."""
        return cls(
            task_id=task_id or str(uuid.uuid4()),
            status="running",
            created_at=datetime.now(timezone.utc).isoformat(),
        )


# ---------------------------------------------------------------------------
# ExportTaskRegistry — görev deposu (bellek içi)
# ---------------------------------------------------------------------------


class ExportTaskRegistry:
    """In-memory export görev durumu deposu.

    OCP: Yeni durum alanları eklenebilir; mevcut metodlar değişmez.
    DIP: backup_api bu sınıfa bağımlıdır, somut ExportService'e değil.
    """

    _tasks: ClassVar[dict[str, ExportTask]] = {}

    @classmethod
    def register(cls, task: ExportTask) -> None:
        """Yeni bir görevi kaydeder."""
        cls._tasks[task.task_id] = task

    @classmethod
    def get(cls, task_id: str) -> ExportTask | None:
        """Görev ID'sine göre görevi döndürür; bulunamazsa None."""
        return cls._tasks.get(task_id)

    @classmethod
    def mark_done(
        cls,
        task_id: str,
        manifest: BackupManifest,
        output_path: Path,
    ) -> None:
        """Görevi tamamlandı olarak işaretler."""
        task = cls._tasks.get(task_id)
        if task:
            task.status = "done"
            task.manifest = manifest
            task.output_path = output_path

    @classmethod
    def mark_error(cls, task_id: str, error: str) -> None:
        """Görevi hata durumunda işaretler."""
        task = cls._tasks.get(task_id)
        if task:
            task.status = "error"
            task.error = error

    @classmethod
    def clear(cls) -> None:  # noqa: D401 — testlerde kullanılır
        """Tüm görev kayıtlarını temizler (sadece testler için)."""
        cls._tasks.clear()
