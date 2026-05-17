"""Orchestrator core — ProjectRegistry, OrchestratorSessionManager, AgentLifecycleManager.

Her class tek sorumluluğa sahiptir (SRP):
  ProjectRegistry           — harici projelerin orchestrator kaydını yönetir
  OrchestratorSessionManager — proje bazlı session bağlamını yönetir
  AgentLifecycleManager      — agent run lifecycle yönetimi
"""
from __future__ import annotations

import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── ProjectRegistry ───────────────────────────────────────────────


class ProjectRegistry:
    """Harici projelerin (petekv5, bengisu vb.) 99-root'a kaydını yönetir.

    DIP: store bağımlılığı constructor üzerinden inject edilir;
    concrete SqliteStore sınıfına doğrudan bağımlılık yoktur.
    """

    def __init__(self, store: Any) -> None:
        """
        Args:
            store: sqlite_store modülü (ya da StoreProtocol'ü karşılayan nesne).
                   project_get / project_list / project_update_status
                   fonksiyonlarına sahip olması beklenir.
        """
        self._store = store

    async def register_project(
        self,
        project_id: str,
        bridge_url: str,
        *,
        fastapi_url: str = "",
        concurrent_agents: int = 3,
    ) -> None:
        """Projeyi DB'deki metadata alanına orchestrator bilgisiyle kaydet.

        Mevcut metadata korunur; yalnızca orchestrator alanları eklenir/güncellenir.

        Args:
            project_id:        Kayıt edilecek proje ID'si (projects tablosunda mevcut olmalı).
            bridge_url:        Projenin Claude Code Bridge endpoint'i.
            fastapi_url:       Projenin FastAPI endpoint'i (opsiyonel).
            concurrent_agents: İzin verilen maksimum eşzamanlı agent sayısı.

        Raises:
            ValueError: Proje DB'de bulunamazsa.
        """
        project = await self._store.project_get(project_id)
        if project is None:
            raise ValueError(f"Proje bulunamadı: {project_id!r}")

        existing_meta: dict = {}
        try:
            existing_meta = json.loads(project.get("metadata") or "{}")
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "ProjectRegistry.register_project: %r için geçersiz metadata JSON — sıfırlandı.",
                project_id,
            )

        existing_meta.update(
            {
                "orchestrator_enabled": True,
                "bridge_url": bridge_url,
                "fastapi_url": fastapi_url,
                "concurrent_agents": concurrent_agents,
                "registered_at": time.time(),
            }
        )

        await self._store.project_update_metadata(project_id, json.dumps(existing_meta))
        logger.info(
            "ProjectRegistry: %r kaydedildi (bridge_url=%s, concurrent=%d).",
            project_id, bridge_url, concurrent_agents,
        )

    async def unregister_project(self, project_id: str) -> None:
        """Projenin orchestrator kaydını kaldır (orchestrator_enabled=False).

        Args:
            project_id: Kaydı kaldırılacak proje ID'si.

        Raises:
            ValueError: Proje DB'de bulunamazsa.
        """
        project = await self._store.project_get(project_id)
        if project is None:
            raise ValueError(f"Proje bulunamadı: {project_id!r}")

        existing_meta: dict = {}
        try:
            existing_meta = json.loads(project.get("metadata") or "{}")
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "ProjectRegistry.unregister_project: %r için geçersiz metadata JSON — sıfırlandı.",
                project_id,
            )

        existing_meta["orchestrator_enabled"] = False
        await self._store.project_update_metadata(project_id, json.dumps(existing_meta))
        logger.info("ProjectRegistry: %r kaydı kaldırıldı.", project_id)

    async def list_registered(self) -> list[dict]:
        """orchestrator_enabled=True olan tüm projeleri döndür.

        Returns:
            Proje dict listesi (metadata alanı parse edilmiş halde).
        """
        all_projects: list[dict] = await self._store.project_list()
        result: list[dict] = []
        for proj in all_projects:
            try:
                meta = json.loads(proj.get("metadata") or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            if meta.get("orchestrator_enabled"):
                proj_copy = dict(proj)
                proj_copy["metadata"] = meta
                result.append(proj_copy)
        return result


# ── OrchestratorSessionManager ────────────────────────────────────


class OrchestratorSessionManager:
    """Proje bazlı session bağlamını yönetir (SRP).

    Dosya I/O atomik write ile yapılır; context JSON'u kaybolmaz.
    """

    _CONTEXT_DIR = ".orchestrator"
    _CONTEXT_FILE = "context.json"

    def get_session_id(self, project_id: str) -> str:
        """project_{id} formatında session_id üret.

        Args:
            project_id: Proje tanımlayıcısı.

        Returns:
            Bridge'e gönderilecek session_id string'i.
        """
        return f"project_{project_id}"

    def get_context_path(self, project_path: str) -> Path:
        """Proje dizinindeki .orchestrator/context.json yolunu döndür.

        Args:
            project_path: Projenin dosya sistemi kök dizini.

        Returns:
            context.json dosyasının mutlak Path'i.
        """
        return Path(project_path) / self._CONTEXT_DIR / self._CONTEXT_FILE

    def read_context(self, project_path: str) -> dict:
        """Context dosyasını oku; yoksa veya bozuksa boş dict döndür.

        Args:
            project_path: Projenin dosya sistemi kök dizini.

        Returns:
            Context sözlüğü.
        """
        ctx_path = self.get_context_path(project_path)
        if not ctx_path.exists():
            return {}
        try:
            return json.loads(ctx_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "OrchestratorSessionManager.read_context: %s okunamadı — %s",
                ctx_path, exc,
            )
            return {}

    def write_context(self, project_path: str, data: dict) -> None:
        """Context dosyasını atomic write ile yaz (yarım yazma riski yok).

        İşlem sırası:
          1. .orchestrator/ dizinini oluştur (idempotent).
          2. Geçici dosyaya yaz.
          3. Atomik rename ile context.json konumuna taşı.

        Args:
            project_path: Projenin dosya sistemi kök dizini.
            data:         Yazılacak context sözlüğü.
        """
        ctx_path = self.get_context_path(project_path)
        ctx_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Atomik write: önce geçici dosyaya yaz, sonra rename
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=ctx_path.parent,
                delete=False,
                suffix=".tmp",
            ) as tmp_file:
                json.dump(data, tmp_file, ensure_ascii=False, indent=2)
                tmp_path = Path(tmp_file.name)

            tmp_path.replace(ctx_path)
            logger.debug(
                "OrchestratorSessionManager.write_context: %s yazıldı.", ctx_path
            )
        except OSError as exc:
            logger.error(
                "OrchestratorSessionManager.write_context: %s yazılamadı — %s",
                ctx_path, exc,
            )
            raise


# ── AgentLifecycleManager ─────────────────────────────────────────


class AgentLifecycleManager:
    """Agent run lifecycle yönetimi — agent_run_repo üzerinden (SRP).

    agent_run_repo modülü lazy import edilir; circular import riski yoktur.
    """

    def __init__(self) -> None:
        # Bağımlılık lazy import ile çözülür (DIP — concrete modüle doğrudan bağlanmaz)
        self._repo: Any = None

    def _get_repo(self) -> Any:
        """agent_run_repo modülünü lazy import et ve döndür."""
        if self._repo is None:
            from ...store.repositories import agent_run_repo as _run_repo  # noqa: PLC0415
            self._repo = _run_repo
        return self._repo

    async def start_run(
        self,
        agent_type: str,
        session_id: str,
        *,
        project_id: str | None = None,
        task_id: str | None = None,
        prompt: str | None = None,
        source: str = "internal",
        sender: str | None = None,
    ) -> str:
        """Yeni run kaydı oluştur (status=pending), run_id döndür.

        Args:
            agent_type:  Agent tipi ('scheduler_cron' | 'manual_bridge' | 'project_task' vb.)
            session_id:  Bridge session kimliği.
            project_id:  İlişkili proje ID'si (opsiyonel).
            task_id:     İlişkili zamanlanmış görev ID'si (opsiyonel).
            prompt:      Agent'a gönderilecek prompt metni (opsiyonel).
            source:      Kaynağı ('internal' | 'whatsapp' | 'telegram' | 'http').
            sender:      Gönderen kimlik bilgisi (opsiyonel).

        Returns:
            Oluşturulan run'ın UUID string ID'si.
        """
        repo = self._get_repo()
        run_id: str = await repo.agent_run_create(
            agent_type,
            session_id,
            project_id=project_id,
            task_id=task_id,
            source=source,
            sender=sender,
            prompt=prompt,
        )
        logger.info(
            "AgentLifecycleManager.start_run: run_id=%s agent_type=%s session=%s",
            run_id, agent_type, session_id,
        )
        return run_id

    async def mark_running(self, run_id: str) -> None:
        """status=running, started_at=now olarak güncelle.

        Args:
            run_id: Güncellenecek run'ın ID'si.
        """
        repo = self._get_repo()
        await repo.agent_run_update_status(run_id, "running")
        logger.debug("AgentLifecycleManager.mark_running: run_id=%s", run_id)

    async def mark_completed(
        self, run_id: str, output: str | None = None
    ) -> None:
        """status=completed, completed_at=now, duration_ms hesapla.

        duration_ms, repo katmanında started_at üzerinden otomatik hesaplanır.

        Args:
            run_id: Tamamlanan run'ın ID'si.
            output: Agent'ın çıktı metni (opsiyonel).
        """
        repo = self._get_repo()
        await repo.agent_run_update_status(run_id, "completed", output=output)
        logger.info("AgentLifecycleManager.mark_completed: run_id=%s", run_id)

    async def mark_failed(
        self, run_id: str, error_msg: str, exit_code: int | None = None
    ) -> None:
        """status=failed, hata bilgilerini kaydet.

        Args:
            run_id:    Başarısız olan run'ın ID'si.
            error_msg: Hata açıklaması.
            exit_code: İşlem çıkış kodu (opsiyonel).
        """
        repo = self._get_repo()
        await repo.agent_run_update_status(
            run_id, "failed", error_msg=error_msg, exit_code=exit_code
        )
        logger.warning(
            "AgentLifecycleManager.mark_failed: run_id=%s error=%s exit_code=%s",
            run_id, error_msg, exit_code,
        )

    async def cancel_run(self, run_id: str) -> None:
        """status=cancelled olarak işaretle.

        Args:
            run_id: İptal edilecek run'ın ID'si.
        """
        repo = self._get_repo()
        await repo.agent_run_cancel(run_id)
        logger.info("AgentLifecycleManager.cancel_run: run_id=%s", run_id)

    async def list_runs(
        self,
        *,
        project_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Filtrelenmiş run listesi döndür (en yeni önce).

        Args:
            project_id: Yalnızca bu projeye ait run'ları filtrele.
            status:     Yalnızca bu statüdeki run'ları filtrele.
            limit:      Maksimum kayıt sayısı.

        Returns:
            AgentRun dict listesi.
        """
        repo = self._get_repo()
        return await repo.agent_run_list(
            project_id=project_id, status=status, limit=limit
        )

    async def list_active_runs(self) -> list[dict]:
        """pending + running olan tüm run'ları döndür (en eski önce).

        Returns:
            Aktif AgentRun dict listesi.
        """
        repo = self._get_repo()
        return await repo.agent_run_list_active()
