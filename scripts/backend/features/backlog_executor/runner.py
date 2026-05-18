"""BacklogExecutorAgent — BACKLOG item'larını Bridge üzerinden implement eder.

Her item için Bridge /query endpoint'ine implementation promptu gönderir.
Paralel çalışma asyncio.Semaphore ile sınırlanır.

SRP: Yalnızca orchestration ve Bridge iletişimi — parse/güncelleme parser.py'de.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import TypedDict

import httpx

from ...config import get_settings
from ...store.repositories.project_repo import project_get
from ..orchestrator.core import AgentLifecycleManager
from .parser import BacklogItem, BacklogParser

logger = logging.getLogger(__name__)


class ExecutorResult(TypedDict):
    project_id: str
    prefix: str
    total: int
    completed: int
    failed: int
    skipped: int
    run_id: str


class BacklogExecutorAgent:
    """BACKLOG item'larını sırayla veya paralel olarak Bridge'e gönderir.

    DIP: settings ve repo bağımlılıkları factory/accessor üzerinden alınır;
    concrete sınıflara doğrudan bağımlılık yoktur.
    """

    async def run(
        self,
        project_id: str,
        prefix: str = "",
        max_items: int = 0,
        parallel: int = 2,
        dry_run: bool = False,
    ) -> ExecutorResult:
        """BACKLOG item'larını çalıştır.

        Args:
            project_id: DB'deki proje ID'si.
            prefix:     Yalnızca bu prefix'li item'ları işle (boşsa tümü).
            max_items:  Tek çalışmada işlenecek maksimum item sayısı (0 = tümü).
            parallel:   Eşzamanlı Bridge istekleri (Semaphore büyüklüğü).
            dry_run:    True ise Bridge'e istek atmadan item'ları done olarak işaretle.

        Returns:
            ExecutorResult — tamamlama istatistikleri.

        Raises:
            ValueError: Proje DB'de bulunamazsa.
            FileNotFoundError: Projede BACKLOG.md yoksa.
        """
        started_at = time.time()

        # 1. Proje kontrolü
        project = await project_get(project_id)
        if project is None:
            raise ValueError(f"Proje bulunamadı: {project_id!r}")

        project_root: str = project["path"]

        # 2. BACKLOG.md kontrolü
        backlog_path = Path(project_root) / "BACKLOG.md"
        if not backlog_path.exists():
            raise FileNotFoundError(
                f"BACKLOG.md bulunamadı: {backlog_path}"
            )

        # 3. Run kaydı oluştur
        run_id = str(uuid.uuid4())
        lifecycle = AgentLifecycleManager()
        agent_run_id = await lifecycle.start_run(
            agent_type="backlog_executor",
            session_id=f"executor_{project_id}_{prefix or 'all'}",
            project_id=project_id,
            source="internal",
        )
        await lifecycle.mark_running(agent_run_id)

        # 4. Pending item'ları al
        parser = BacklogParser()
        items = parser.get_pending_items(backlog_path, prefix)
        if max_items and max_items > 0:
            items = items[:max_items]

        # İlerleme takibi — progress.json yaz (status endpoint okur)
        _PROGRESS_FILE = Path(__file__).parent.parent.parent.parent.parent / "data" / "backlog_progress.json"
        import json as _json
        _progress = {
            "run_id":      run_id,
            "project_id":  project_id,
            "total_items": len(items),
            "completed":   0,
            "failed":      0,
            "started_at":  started_at,
            "status":      "running",
        }
        try:
            _PROGRESS_FILE.write_text(_json.dumps(_progress, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

        if not items:
            await lifecycle.mark_completed(agent_run_id, output="0 item — işlenecek görev yok")
            logger.info(
                "BacklogExecutorAgent: %r için pending item bulunamadı (prefix=%r).",
                project_id, prefix,
            )
            return ExecutorResult(
                project_id=project_id,
                prefix=prefix,
                total=0,
                completed=0,
                failed=0,
                skipped=0,
                run_id=run_id,
            )

        # 5. Paralel çalıştır
        sem = asyncio.Semaphore(parallel)
        file_lock = asyncio.Lock()  # BACKLOG.md concurrent yazma koruması
        tasks = [
            self._execute_item(item, backlog_path, project_root, sem, dry_run, file_lock)
            for item in items
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 6. Sonuçları say
        completed = sum(1 for r in results if r is True)
        failed = sum(1 for r in results if r is False or isinstance(r, Exception))
        skipped = len(items) - completed - failed

        # Progress.json'u tamamlandı olarak güncelle
        try:
            _progress.update({"completed": completed, "failed": failed, "status": "completed"})
            _PROGRESS_FILE.write_text(_json.dumps(_progress, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

        summary = f"completed={completed} failed={failed} total={len(items)}"
        await lifecycle.mark_completed(agent_run_id, output=summary)
        logger.info("BacklogExecutorAgent.run: %s — %s", project_id, summary)

        # Tamamlanma bildirimi — tüm işler bittikten sonra tek seferde
        try:
            from ...adapters.messenger import get_messenger
            from ...config import settings
            from ...i18n import t

            lang     = "tr"
            owner    = settings.owner_id
            duration = max(1, int((time.time() - started_at) / 60))
            project_name = project.get("name") or project_id
            await get_messenger().send_text(
                owner,
                t(
                    "backlog.done_summary",
                    lang,
                    project=project_name,
                    completed=completed,
                    total=len(items),
                    failed=failed,
                    minutes=duration,
                ),
            )
        except Exception as _notify_err:
            logger.warning("BacklogExecutorAgent: bildirim gönderilemedi: %s", _notify_err)

        return ExecutorResult(
            project_id=project_id,
            prefix=prefix,
            total=len(items),
            completed=completed,
            failed=failed,
            skipped=skipped,
            run_id=run_id,
        )

    async def _execute_item(
        self,
        item: BacklogItem,
        backlog_path: Path,
        project_root: str,
        sem: asyncio.Semaphore,
        dry_run: bool,
        file_lock: asyncio.Lock,
    ) -> bool:
        """Tek bir BACKLOG item'ını işle.

        Args:
            item:         İşlenecek BacklogItem.
            backlog_path: BACKLOG.md dosyasının Path'i.
            project_root: Proje kök dizini.
            sem:          Eşzamanlılık sınırlayıcı Semaphore.
            dry_run:      True ise Bridge çağrısı yapılmadan done olarak işaretlenir.
            file_lock:    BACKLOG.md dosyasına eşzamanlı yazma koruması için Lock.

        Returns:
            True → başarı, False → hata.
        """
        async with sem:
            parser = BacklogParser()
            async with file_lock:
                parser.mark_in_progress(backlog_path, item["item_id"])

            if dry_run:
                async with file_lock:
                    parser.mark_done(backlog_path, item["item_id"])
                logger.info(
                    "BacklogExecutorAgent._execute_item: %s dry_run ile done.",
                    item["item_id"],
                )
                return True

            try:
                settings = get_settings()
                prompt = self._build_prompt(item, project_root)
                url = f"{settings.claude_bridge_url}/query"
                headers = {
                    "X-Api-Key": settings.api_key.get_secret_value(),
                    "Content-Type": "application/json",
                }
                # Bridge allowedRoots yalnızca ROOT_DIR altındaki yolları kabul eder.
                # Harici projeler için project_path gönderilmez; Bridge active_context.json
                # üzerinden active_root_project.path'i zaten kullanır.
                _root_dir = Path(__file__).parent.parent.parent.parent.parent
                body: dict = {
                    "session_id": f"executor_{item['item_id']}",
                    "message": prompt,
                    "init_prompt": "",
                    "silent": True,
                }
                _pp = Path(project_root).resolve()
                if str(_pp).startswith(str(_root_dir.resolve()) + "/") or _pp == _root_dir.resolve():
                    body["project_path"] = str(_pp)
                async with httpx.AsyncClient(timeout=1800.0) as client:
                    response = await client.post(url, json=body, headers=headers)

                if response.status_code == 200:
                    async with file_lock:
                        parser.mark_done(backlog_path, item["item_id"])
                    logger.info(
                        "BacklogExecutorAgent._execute_item: %s tamamlandı.",
                        item["item_id"],
                    )
                    return True

                logger.error(
                    "BacklogExecutorAgent._execute_item: %s — HTTP %d",
                    item["item_id"], response.status_code,
                )
                async with file_lock:
                    parser.mark_failed(backlog_path, item["item_id"])
                return False

            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "BacklogExecutorAgent._execute_item: %s için istisna — %s",
                    item["item_id"], exc,
                )
                async with file_lock:
                    parser.mark_failed(backlog_path, item["item_id"])
                return False

    def _build_prompt(self, item: BacklogItem, project_root: str) -> str:
        """Bridge'e gönderilecek implementation promptunu oluştur.

        Args:
            item:         Implement edilecek BacklogItem.
            project_root: Proje kök dizini (context için).

        Returns:
            Prompt metni.
        """
        return (
            f"Sen {project_root} dizininde çalışan bir kod asistanısın.\n"
            f"Aşağıdaki BACKLOG maddesini implement et:\n\n"
            f"{item['text']}\n\n"
            f"Talimatlar:\n"
            f"- Gerekli dosyaları oku, değişiklikleri yaz\n"
            f"- Mümkün olan en minimal değişikliği yap\n"
            f"- Tamamladığında kısa bir özet ver"
        )
