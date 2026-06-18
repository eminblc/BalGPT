"""ScanPauseStore — scan duraklatma/devam state'ini yönetir (SRP).

Dosya tabanlı kalıcı checkpoint + in-memory flag:
  data/scan_state/{run_id}/state.json

state.json formatı:
  {
    "phase": "scanner" | "reviewer",
    "paused": bool,
    "completed_chunks": [0, 1, 2, ...],
    "resume_from": 3,
    "completed_batches": [0, 1, ...],
    "resume_batch": 2,
    "scan_type": "security",
    "project_id": "...",
    "started_at": 1234567890.0
  }

Restart-safe: process yeniden başlasa bile state.json'dan devam edilebilir.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

_STATE_DIR = Path(__file__).parent.parent.parent.parent.parent / "data" / "scan_state"
_lock = threading.Lock()


class ScanPauseStore:
    """Scan duraklatma ve checkpoint state'ini yönetir.

    SRP: Yalnızca pause/resume ve checkpoint — tarama mantığı ScannerAgent'ta.
    Thread-safe: tüm mutasyonlar _lock altında gerçekleşir.
    DIP: Dosya sistemine doğrudan yazar; DB bağımsız.
    """

    # Sınıf düzeyinde in-memory pause flags {run_id: bool}
    # Process restart'larında sıfırlanır; file-based state dosyadan yeniden yüklenir.
    _paused: dict[str, bool] = {}

    # ── Başlatma ve okuma ──────────────────────────────────────────────────────

    @classmethod
    def init_state(
        cls,
        run_id: str,
        scan_type: str,
        project_id: str,
        started_at: float,
        phase: str = "scanner",
    ) -> None:
        """Yeni bir scan run için state dosyası oluşturur.

        Zaten mevcutsa üzerine yazmaz — resume senaryosu için güvenli.
        """
        state_path = _STATE_DIR / run_id / "state.json"
        if state_path.exists():
            # Resume: mevcut state korunur, sadece in-memory flag yüklenir.
            with _lock:
                existing = cls._read_state_unlocked(run_id)
                cls._paused[run_id] = existing.get("paused", False)
            return

        state: dict = {
            "phase": phase,
            "paused": False,
            "completed_chunks": [],
            "resume_from": 0,
            "completed_batches": [],
            "resume_batch": 0,
            "scan_type": scan_type,
            "project_id": project_id,
            "started_at": started_at,
        }
        with _lock:
            cls._paused[run_id] = False
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    @classmethod
    def get_state(cls, run_id: str) -> dict:
        """State dosyasını okur; bulunamazsa boş dict döner."""
        with _lock:
            return cls._read_state_unlocked(run_id)

    @classmethod
    def _read_state_unlocked(cls, run_id: str) -> dict:
        """State dosyasını okur. _lock tutularak çağrılmalı."""
        state_path = _STATE_DIR / run_id / "state.json"
        if not state_path.exists():
            return {}
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    @classmethod
    def _write_state_unlocked(cls, run_id: str, state: dict) -> None:
        """State'i diske yazar. _lock tutularak çağrılmalı."""
        state_dir = _STATE_DIR / run_id
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ── Pause / Resume ─────────────────────────────────────────────────────────

    @classmethod
    def request_pause(cls, run_id: str) -> None:
        """Belirtilen run_id için pause ister.

        Bir sonraki chunk/batch kontrolünde tarama durur.
        """
        with _lock:
            cls._paused[run_id] = True
            state = cls._read_state_unlocked(run_id)
            if state:
                state["paused"] = True
                cls._write_state_unlocked(run_id, state)

    @classmethod
    def request_resume(cls, run_id: str) -> None:
        """Duraklatılmış scan'i devam ettirir."""
        with _lock:
            cls._paused[run_id] = False
            state = cls._read_state_unlocked(run_id)
            if state:
                state["paused"] = False
                cls._write_state_unlocked(run_id, state)

    @classmethod
    def is_paused(cls, run_id: str) -> bool:
        """Bu run_id için pause flag'i set edilmişse True döner."""
        with _lock:
            # In-memory önce; process restart'ında dosyadan yükle.
            if run_id in cls._paused:
                return cls._paused[run_id]
            state = cls._read_state_unlocked(run_id)
            paused = state.get("paused", False)
            cls._paused[run_id] = paused
            return paused

    # ── Checkpoint ─────────────────────────────────────────────────────────────

    @classmethod
    def mark_chunk_done(cls, run_id: str, chunk_index: int) -> None:
        """Tamamlanan chunk'ı checkpoint'e kaydeder.

        Restart sonrasında tamamlanan chunk'lar atlanabilir.
        """
        with _lock:
            state = cls._read_state_unlocked(run_id)
            if not state:
                return
            completed: list[int] = state.get("completed_chunks", [])
            if chunk_index not in completed:
                completed.append(chunk_index)
            state["completed_chunks"] = completed
            state["resume_from"] = max(completed) + 1 if completed else 0
            cls._write_state_unlocked(run_id, state)

    @classmethod
    def mark_batch_done(cls, run_id: str, batch_index: int) -> None:
        """Tamamlanan batch'i checkpoint'e kaydeder (reviewer fazı).

        Restart sonrasında tamamlanan batch'ler atlanabilir.
        """
        with _lock:
            state = cls._read_state_unlocked(run_id)
            if not state:
                return
            completed: list[int] = state.get("completed_batches", [])
            if batch_index not in completed:
                completed.append(batch_index)
            state["completed_batches"] = completed
            state["resume_batch"] = max(completed) + 1 if completed else 0
            state["phase"] = "reviewer"
            cls._write_state_unlocked(run_id, state)

    @classmethod
    def set_total_batches(cls, run_id: str, total: int) -> None:
        """Reviewer fazına geçişte toplam batch sayısını state'e yazar.

        Progress bar UI (dashboard, /scan durum) bu değeri kullanır.
        Yalnızca yeni bir reviewer çalışmasının başlangıcında çağrılmalı.
        """
        with _lock:
            state = cls._read_state_unlocked(run_id)
            if not state:
                return
            state["total_batches"] = max(0, int(total))
            state["phase"] = "reviewer"
            cls._write_state_unlocked(run_id, state)

    @classmethod
    def get_total_batches(cls, run_id: str) -> int:
        """Reviewer fazı için kaydedilmiş toplam batch sayısı (0 → bilinmiyor)."""
        state = cls.get_state(run_id)
        return int(state.get("total_batches", 0) or 0)

    @classmethod
    def get_completed_chunks(cls, run_id: str) -> set[int]:
        """Tamamlanan chunk index'lerini döndürür."""
        state = cls.get_state(run_id)
        return set(state.get("completed_chunks", []))

    @classmethod
    def get_completed_batches(cls, run_id: str) -> set[int]:
        """Tamamlanan batch index'lerini döndürür."""
        state = cls.get_state(run_id)
        return set(state.get("completed_batches", []))
