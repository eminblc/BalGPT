"""APScheduler kurulumu ve job yönetimi (SRP).

FastAPI startup/shutdown lifecycle'ına bağlıdır.
Tüm periyodik işler buradan koordine edilir.

Action tipleri:
  send_message  → payload: {message: str}  — sabit metin WhatsApp'a gönderilir
  run_bridge    → payload: {message: str}  — Bridge'e prompt gönderilir, Claude yanıtlar
"""
from __future__ import annotations

import logging
from pathlib import Path

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from apscheduler.jobstores.base import JobLookupError
    _APSCHEDULER_AVAILABLE = True
except ImportError:
    AsyncIOScheduler = None       # type: ignore[assignment,misc]
    SQLAlchemyJobStore = None     # type: ignore[assignment,misc]
    JobLookupError = Exception    # type: ignore[assignment,misc]
    _APSCHEDULER_AVAILABLE = False

from ..config import get_settings
from ..i18n import t

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "scheduler.db"

if _APSCHEDULER_AVAILABLE:
    _scheduler = AsyncIOScheduler(
        jobstores={
            "default": SQLAlchemyJobStore(url=f"sqlite:///{_DB_PATH}"),
        },
        job_defaults={"coalesce": True, "max_instances": 1},
        timezone=get_settings().timezone,
    )
else:
    _scheduler = None  # type: ignore[assignment]

# Çalışma zamanında değiştirilebilen aktif timezone (FEAT-10)
_active_timezone: str = get_settings().timezone


def get_current_timezone() -> str:
    """Çalışma zamanındaki aktif timezone'u döndür."""
    return _active_timezone


async def apply_timezone(tz: str) -> None:
    """Timezone'u çalışma zamanında değiştir — APScheduler + cron job'larını yeniden yükle.

    APScheduler'ın timezone'u güncellenir; ardından tüm aktif cron job'ları
    yeni timezone'a göre yeniden kaydedilir (CronTrigger'lar yeniden oluşturulur).

    IMP-FEAT-1: _active_timezone yalnızca _reload_cron_jobs_only() başarılıysa güncellenir;
    hata olursa eski değere rollback yapılır.
    """
    global _active_timezone

    if not _scheduler.running:
        # Scheduler çalışmıyorsa yalnızca değeri güncelle (rollback gerekmez)
        _active_timezone = tz
        logger.info("apply_timezone: scheduler çalışmıyor, yalnızca değer güncellendi: %s", tz)
        return

    from zoneinfo import ZoneInfo
    _scheduler.configure(timezone=ZoneInfo(tz))

    old_tz = _active_timezone
    _active_timezone = tz
    try:
        # Takvim hatırlatıcı job'ı sisteme ait — atla; yalnızca kullanıcı job'larını yeniden yükle
        await _reload_cron_jobs_only()
    except Exception as exc:
        # Rollback: cron reload başarısız olursa tutarlı state koru
        _active_timezone = old_tz
        logger.error("apply_timezone: cron reload başarısız, eski timezone'a geri dönüldü (%s): %s", old_tz, exc)
        raise
    logger.info("Timezone uygulandı: %s — cron job'lar yeniden yüklendi", tz)


async def _reload_cron_jobs_only() -> None:
    """SQLite'taki aktif CRON job'larını yeniden yükle (date-trigger job'ları dokunma)."""
    from ..store import sqlite_store as db
    tasks = await db.task_list_active()
    for task in tasks:
        if task.get("status") == "deleted":
            continue
        cron_expr = task.get("cron_expr")
        if not cron_expr:
            continue
        task_id = task["id"]
        try:
            fields = _parse_cron(cron_expr)
            _scheduler.add_job(
                _execute_task,
                trigger="cron",
                id=task_id,
                replace_existing=True,
                kwargs={"task_id": task_id},
                **fields,
            )
            logger.debug("Cron job timezone sonrası yeniden yüklendi: %s", task_id)
        except Exception as exc:
            logger.error("Cron job yeniden yüklenemedi: %s hata=%s", task_id, exc)


async def _purge_stale_apscheduler_jobs() -> None:
    """APScheduler başlamadan önce scheduler.db'deki stale job'ları siler.

    Restart sırasında deactivated job'ların persistent store'dan yüklenip
    misfire tetiklemesini engeller (race condition — start() sonra temizleme).
    """
    from ..store import sqlite_store as _db
    from ..store._connection import _resolve_db_path
    import sqlite3 as _sqlite3

    try:
        active_ids = {t["id"] for t in await _db.task_list_active()}
        system_jobs = {"calendar_reminder_check"}
        sched_db = _resolve_db_path().parent / "scheduler.db"
        if not sched_db.exists():
            return
        con = _sqlite3.connect(str(sched_db))
        rows = con.execute("SELECT id FROM apscheduler_jobs").fetchall()
        for (job_id,) in rows:
            if job_id in system_jobs or job_id in active_ids:
                continue
            con.execute("DELETE FROM apscheduler_jobs WHERE id = ?", (job_id,))
            logger.info("Startup öncesi stale APScheduler job silindi: %s", job_id)
        con.commit()
        con.close()
    except Exception as _err:
        logger.warning("APScheduler pre-start temizlik başarısız: %s", _err)


async def start_scheduler() -> None:
    if _scheduler.running:
        return

    # Persistent DB'deki stale job'ları scheduler.start()'tan ÖNCE sil
    # (start() job'ları yükler ve geçmiş next_run_time olanları anında tetikler)
    await _purge_stale_apscheduler_jobs()

    _scheduler.start()

    # Takvim hatırlatıcılarını her dakika kontrol et
    _scheduler.add_job(
        _check_reminders,
        trigger="interval",
        minutes=1,
        id="calendar_reminder_check",
        replace_existing=True,
    )

    # SQLite'taki aktif job'ları (cron + one-shot) APScheduler'a yükle
    await _reload_all_jobs()

    # Otomatik periyodik yedekleme (BACKUP-10)
    _register_auto_backup_job()

    logger.info("Scheduler başladı")


async def stop_scheduler() -> None:
    if _scheduler.running:
        # wait=True: devam eden job tamamlanana kadar bekle — veri tutarsızlığı önlenir.
        # Maksimum 5 saniye timeout ile thread'de çalıştır; event loop'u bloklamaz.
        import asyncio as _asyncio
        try:
            await _asyncio.wait_for(
                _asyncio.to_thread(_scheduler.shutdown, wait=True),
                timeout=5.0,
            )
        except _asyncio.TimeoutError:
            logger.warning("Scheduler graceful shutdown zaman aşımına uğradı; zorla durduruluyor")
            _scheduler.shutdown(wait=False)
        logger.info("Scheduler durduruldu")


# ── Kullanıcı cron job'ları ───────────────────────────────────────

async def create_scheduled_task(
    description: str,
    cron_expr: str,
    action_type: str,
    message: str,
) -> dict:
    """Yeni zamanlanmış görev oluştur: SQLite'a kaydet + APScheduler'a ekle (K-N4).

    Router'ın doğrudan store'a erişmesi yerine bu fonksiyon kullanılmalıdır (DIP).
    """
    _parse_cron(cron_expr)  # Geçersizse ValueError fırlatır — router HTTPException'a çevirir
    from ..store import sqlite_store as db
    msg = message or description
    task = await db.task_create(
        description    = description,
        action_type    = action_type,
        action_payload = {"message": msg},
        cron_expr      = cron_expr,
    )
    await add_cron_job(task["id"], cron_expr, description, action_type, {"message": msg})
    return task


async def add_cron_job(task_id: str, cron_expr: str, description: str,
                       action_type: str, action_payload: dict) -> None:
    """SQLite + APScheduler'a cron job ekle.

    cron_expr: standart 5-alan cron  (ör. "0 9 * * *" = her sabah 9)
    action_type: "send_message" | "run_bridge"
    """
    fields = _parse_cron(cron_expr)
    _scheduler.add_job(
        _execute_task,
        trigger="cron",
        id=task_id,
        replace_existing=True,
        kwargs={"task_id": task_id},
        **fields,
    )
    logger.info("Cron job eklendi: %s [%s] %s", task_id, cron_expr, description)


async def create_one_shot_task(
    description: str,
    message: str,
    run_at: float,
    action_type: str = "send_message",
) -> dict:
    """Tek seferlik job oluştur: SQLite'a kaydet + APScheduler date trigger ekle.

    Restart-safe: _reload_all_jobs() startup'ta yeniden yükler.
    run_at: Unix timestamp (UTC)
    """
    import datetime
    from ..store import sqlite_store as db

    msg = message or description
    task = await db.task_create(
        description    = description,
        action_type    = action_type,
        action_payload = {"message": msg},
        cron_expr      = None,
        next_run       = run_at,
    )
    run_date = datetime.datetime.fromtimestamp(run_at, tz=datetime.timezone.utc)
    _scheduler.add_job(
        _execute_one_shot_task,
        trigger="date",
        run_date=run_date,
        id=task["id"],
        replace_existing=True,
        kwargs={"task_id": task["id"]},
    )
    logger.info("One-shot job eklendi: %s run_at=%s %s", task["id"], run_at, description)
    return task


async def _execute_one_shot_task(task_id: str) -> None:
    """APScheduler date trigger tarafından çağrılır — tek seferlik job."""
    import json
    from ..store import sqlite_store as db

    task = await db.task_get(task_id)
    if not task:
        logger.warning("_execute_one_shot_task: task bulunamadı %s", task_id)
        return

    try:
        payload = json.loads(task.get("action_payload") or "{}")
    except (json.JSONDecodeError, ValueError) as _json_err:
        logger.warning(
            "Scheduler: one-shot task %s için action_payload geçersiz JSON — boş dict kullanılıyor: %s",
            task_id,
            _json_err,
        )
        payload = {}

    action_type = task.get("action_type", "send_message")
    message = payload.get("message", task.get("description", ""))

    logger.info("One-shot task çalıştırılıyor: %s [%s]", task_id, action_type)

    # Agent run tracking — DB hatası mevcut işi bloklamasın
    run_id: str | None = None
    try:
        from ..store.repositories.agent_run_repo import (
            agent_run_create,
            agent_run_update_status,
        )
        run_id = await agent_run_create(
            "scheduler_oneshot",
            "main",
            project_id=task.get("project_id"),
            task_id=task_id,
            source="scheduler",
            prompt=task.get("description"),
        )
        await agent_run_update_status(run_id, "running")
    except Exception as _track_err:
        logger.warning("_execute_one_shot_task: agent run kaydedilemedi: %s", _track_err)

    await db.task_update_status(task_id, "running")
    try:
        if action_type == "send_message":
            await _send_notification(t("scheduler.task_reminder", "tr", message=message))
        elif action_type == "run_bridge":
            await _run_bridge_query(message, silent=True)
        elif action_type == "run_scan":
            # Agent run tracking ScanRunner.run() içinde yapılır — burada duplicate etme
            scan_type = payload.get("scan_type", "security")
            project_id_scan = payload.get("project_id", "")
            dry_run_scan = payload.get("dry_run", False)
            from .scan_pipeline.runner import ScanRunner
            await ScanRunner().run(scan_type, project_id_scan, dry_run_scan)
        elif action_type == "run_scanner":
            scan_type = payload.get("scan_type", "security")
            project_id_scan = payload.get("project_id", "")
            auto_review = payload.get("auto_review", True)
            dry_run_scan = payload.get("dry_run", False)
            from .scan_pipeline.scanner_agent import ScannerAgent
            await ScannerAgent().run(scan_type, project_id_scan, auto_review, dry_run_scan)
        elif action_type == "run_backlog_executor":
            project_id_exec = payload.get("project_id", "")
            prefix = payload.get("prefix", "")
            max_items = int(payload.get("max_items", 3))
            parallel = int(payload.get("parallel", 2))
            dry_run_exec = payload.get("dry_run", False)
            from .backlog_executor.runner import BacklogExecutorAgent
            await BacklogExecutorAgent().run(project_id_exec, prefix, max_items, parallel, dry_run_exec)
        await db.task_update_status(task_id, "succeeded")
        if run_id is not None:
            try:
                await agent_run_update_status(run_id, "completed")
            except Exception as _track_err:
                logger.warning("_execute_one_shot_task: run completed güncellenemedi: %s", _track_err)
    except Exception as e:
        logger.error("_execute_one_shot_task başarısız: %s hata=%s", task_id, e)
        await db.task_update_status(task_id, "failed")
        if run_id is not None:
            try:
                await agent_run_update_status(run_id, "failed", error_msg=str(e))
            except Exception as _track_err:
                logger.warning("_execute_one_shot_task: run failed güncellenemedi: %s", _track_err)
        raise
    finally:
        # Tek seferlik — çalıştıktan sonra devre dışı bırak
        await db.task_deactivate(task_id)
        await db.task_update_last_run(task_id)


async def soft_delete_job(task_id: str) -> None:
    """APScheduler'dan kaldır + SQLite'ta soft delete (active=0, status='deleted')."""
    try:
        _scheduler.remove_job(task_id)
    except JobLookupError:
        logger.debug("soft_delete_job: job APScheduler'da yok: %s", task_id)
    except Exception as exc:
        logger.error("soft_delete_job beklenmedik hata: %s — %s", task_id, exc)
    from ..store import sqlite_store as db
    await db.task_soft_delete(task_id)
    logger.info("Job soft-deleted: %s", task_id)


def remove_cron_job(task_id: str) -> None:
    """Geriye dönük uyum alias — soft_delete_job'ı çağırır (async wrapper)."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(soft_delete_job(task_id))
        else:
            loop.run_until_complete(soft_delete_job(task_id))
    except Exception as exc:
        logger.error("remove_cron_job alias hatası: %s — %s", task_id, exc)
        # Fallback: senkron hard delete
        from ..store import sqlite_store as db
        db._sync_task_delete(task_id)
    logger.info("Cron job silindi (alias): %s", task_id)


def pause_cron_job(task_id: str) -> None:
    """Job'ı durdur (APScheduler'dan sil + SQLite active=0).

    pause yerine remove_job kullanılıyor: persistent job store'da
    paused job restart sonrası tekrar yükleniyor (uyumsuzluk kaynağı).
    """
    try:
        _scheduler.remove_job(task_id)
    except JobLookupError:
        logger.debug("pause_cron_job: job APScheduler'da yok, yalnızca SQLite güncelleniyor: %s", task_id)
    except Exception as exc:
        logger.error("pause_cron_job beklenmedik hata: %s — SQLite güncelleniyor: %s", task_id, exc)
    from ..store import sqlite_store as db
    db._sync_task_deactivate(task_id)
    logger.info("Cron job durduruldu: %s", task_id)


def resume_cron_job(task_id: str) -> None:
    """Durdurulan job'ı yeniden başlat."""
    try:
        _scheduler.resume_job(task_id)
    except Exception as exc:
        # APScheduler'da yoksa yeniden ekle
        logger.debug("resume_cron_job: APScheduler'da bulunamadı (%s), yeniden ekleniyor: %s", exc, task_id)
        try:
            from ..store import sqlite_store as db
            import json
            task = db._sync_task_get(task_id)
            if task and task.get("cron_expr"):
                payload = json.loads(task.get("action_payload") or "{}")
                fields = _parse_cron(task["cron_expr"])
                _scheduler.add_job(
                    _execute_task,
                    trigger="cron",
                    id=task_id,
                    replace_existing=True,
                    kwargs={"task_id": task_id},
                    **fields,
                )
        except Exception as re_exc:
            logger.error("resume_cron_job: job yeniden eklenemedi: %s hata=%s", task_id, re_exc)
            return
    from ..store import sqlite_store as db
    db._sync_task_activate(task_id)
    logger.info("Cron job yeniden başlatıldı: %s", task_id)


async def list_active_tasks() -> list[dict]:
    """Aktif görevleri döndür — features katmanı store'a doğrudan erişmez (DIP)."""
    from ..store import sqlite_store as db
    return await db.task_list_active()


def list_cron_jobs() -> list[dict]:
    """Tüm kullanıcı job'larını döndür (sistem job'ları hariç)."""
    from ..store import sqlite_store as db
    tasks = db._sync_task_list_all()
    result = []
    for t in tasks:
        apsjob = None
        try:
            apsjob = _scheduler.get_job(t["id"])
        except Exception:
            pass
        t["next_run_time"] = apsjob.next_run_time.isoformat() if apsjob and apsjob.next_run_time else None
        result.append(t)
    return result


async def _reload_all_jobs() -> None:
    """Startup'ta SQLite'taki TÜM aktif job'ları APScheduler'a yükle.

    - cron_expr IS NOT NULL → CronTrigger
    - next_run IS NOT NULL, cron_expr IS NULL → DateTrigger (tek seferlik)
      - geçmiş ≤5dk: coalesce=True ile hemen çalıştır
      - geçmiş >5dk: soft-deactivate + log (kaçırıldı)
      - gelecekte: normal DateTrigger
    - status='deleted': atla
    - scope='project': atla (project-specific orchestrator yönetir)

    Startup temizliği: persistent job store'da kalan ama DB'de active=0/deleted
    olan job'lar (pause→restart uyumsuzluğu) APScheduler'dan temizlenir.
    """
    import datetime
    import time as _time
    from ..store import sqlite_store as db

    # Startup temizliği: APScheduler'daki sistem dışı job'ları DB ile karşılaştır
    active_ids = {t["id"] for t in await db.task_list_active()}
    system_jobs = {"calendar_reminder_check"}
    for job in _scheduler.get_jobs():
        if job.id in system_jobs:
            continue
        if job.id not in active_ids:
            try:
                _scheduler.remove_job(job.id)
                logger.info("_reload_all_jobs: stale job temizlendi: %s", job.id)
            except Exception as _rm_exc:
                logger.warning("_reload_all_jobs: stale job silinemedi: %s — %s", job.id, _rm_exc)

    tasks = await db.task_list_active()
    now = _time.time()
    for task in tasks:
        # Soft-deleted job'ları atla
        if task.get("status") == "deleted":
            continue

        # Project-scoped job'lar project orchestrator'a bırakılır
        if task.get("scope") == "project":
            logger.debug(
                "Project-scoped job atlanıyor: %s (project=%s)",
                task["id"], task.get("project_id"),
            )
            continue

        task_id = task["id"]
        cron_expr = task.get("cron_expr")
        next_run = task.get("next_run")

        if cron_expr:
            # Tekrarlayan cron job
            try:
                fields = _parse_cron(cron_expr)
                _scheduler.add_job(
                    _execute_task,
                    trigger="cron",
                    id=task_id,
                    replace_existing=True,
                    kwargs={"task_id": task_id},
                    **fields,
                )
                logger.debug("Cron job yüklendi: %s", task_id)
            except Exception as e:
                logger.error("Cron job yüklenemedi: %s hata=%s", task_id, e)

        elif next_run is not None:
            # Tek seferlik date-trigger job
            overdue_seconds = now - next_run
            if overdue_seconds > 300:
                # 5 dakikadan fazla gecikmiş → kaçırıldı, devre dışı bırak
                await db.task_soft_delete(task_id)
                logger.info(
                    "One-shot job kaçırıldı (>5dk): %s gecikme=%.0fs",
                    task_id, overdue_seconds,
                )
            else:
                # Gelecekte veya ≤5dk gecikmiş → DateTrigger (coalesce=True hemen tetikler)
                run_date = datetime.datetime.fromtimestamp(
                    max(next_run, now + 1), tz=datetime.timezone.utc
                )
                try:
                    _scheduler.add_job(
                        _execute_one_shot_task,
                        trigger="date",
                        run_date=run_date,
                        id=task_id,
                        replace_existing=True,
                        kwargs={"task_id": task_id},
                    )
                    logger.debug("One-shot job yüklendi: %s run_at=%s", task_id, next_run)
                except Exception as e:
                    logger.error("One-shot job yüklenemedi: %s hata=%s", task_id, e)


# Geriye dönük uyum alias — start_scheduler() ve dış çağrılar için
_reload_cron_jobs = _reload_all_jobs


async def _execute_task(task_id: str) -> None:
    """APScheduler tarafından çağrılır — action_type'a göre işlemi yürütür."""
    import json
    from ..store import sqlite_store as db
    import time

    task = await db.task_get(task_id)
    if not task:
        logger.warning("_execute_task: task bulunamadı %s", task_id)
        return

    try:
        payload = json.loads(task.get("action_payload") or "{}")
    except (json.JSONDecodeError, ValueError) as _json_err:
        logger.warning(
            "Scheduler: task %s için action_payload geçersiz JSON — boş dict kullanılıyor: %s",
            task_id,
            _json_err,
        )
        payload = {}

    action_type = task.get("action_type", "send_message")
    message = payload.get("message", task.get("description", ""))

    logger.info("Task çalıştırılıyor: %s [%s]", task_id, action_type)

    # Agent run tracking — DB hatası mevcut işi bloklamasın
    run_id: str | None = None
    try:
        from ..store.repositories.agent_run_repo import (
            agent_run_create,
            agent_run_update_status,
        )
        run_id = await agent_run_create(
            "scheduler_cron",
            "main",
            project_id=task.get("project_id"),
            task_id=task_id,
            source="scheduler",
            prompt=task.get("description"),
        )
        await agent_run_update_status(run_id, "running")
    except Exception as _track_err:
        logger.warning("_execute_task: agent run kaydedilemedi: %s", _track_err)

    await db.task_update_status(task_id, "running")
    try:
        if action_type == "send_message":
            # IMP-FEAT-5: _send_notification network'te takılırsa thread'i sonsuz bloke etmesini önle
            import asyncio as _aio
            await _aio.wait_for(_send_notification(t("scheduler.task_reminder", "tr", message=message)), timeout=30.0)
        elif action_type == "run_bridge":
            await _run_bridge_query(message, silent=True)
        elif action_type == "run_scan":
            # Agent run tracking ScanRunner.run() içinde yapılır — burada duplicate etme
            scan_type = payload.get("scan_type", "security")
            project_id_scan = payload.get("project_id", "")
            dry_run_scan = payload.get("dry_run", False)
            from .scan_pipeline.runner import ScanRunner
            await ScanRunner().run(scan_type, project_id_scan, dry_run_scan)
        elif action_type == "run_scanner":
            scan_type = payload.get("scan_type", "security")
            project_id_scan = payload.get("project_id", "")
            auto_review = payload.get("auto_review", True)
            dry_run_scan = payload.get("dry_run", False)
            from .scan_pipeline.scanner_agent import ScannerAgent
            await ScannerAgent().run(scan_type, project_id_scan, auto_review, dry_run_scan)
        elif action_type == "run_backlog_executor":
            project_id_exec = payload.get("project_id", "")
            prefix = payload.get("prefix", "")
            max_items = int(payload.get("max_items", 3))
            parallel = int(payload.get("parallel", 2))
            dry_run_exec = payload.get("dry_run", False)
            from .backlog_executor.runner import BacklogExecutorAgent
            await BacklogExecutorAgent().run(project_id_exec, prefix, max_items, parallel, dry_run_exec)
        # Cron job'lar tamamlandıktan sonra "scheduled" durumuna geri döner
        await db.task_update_status(task_id, "scheduled")
        if run_id is not None:
            try:
                await agent_run_update_status(run_id, "completed")
            except Exception as _track_err:
                logger.warning("_execute_task: run completed güncellenemedi: %s", _track_err)
    except Exception as e:
        logger.error("_execute_task başarısız: %s hata=%s", task_id, e)
        await db.task_update_status(task_id, "failed")
        if run_id is not None:
            try:
                await agent_run_update_status(run_id, "failed", error_msg=str(e))
            except Exception as _track_err:
                logger.warning("_execute_task: run failed güncellenemedi: %s", _track_err)
        raise

    # last_run güncelle (BUG-A5: private _conn yerine public metot)
    await db.task_update_last_run(task_id)


async def _send_notification(text: str) -> None:
    from ..adapters.messenger import get_messenger
    if get_settings().owner_id:
        await get_messenger().send_text(get_settings().owner_id, text)


async def _run_bridge_query(message: str, silent: bool = False) -> None:
    """Bridge'e prompt gönderir; Claude yanıtı doğrudan messenger'a iletir.

    silent=True: ⚙️ İşleniyor... bildirimi gönderilmez (scheduler çağrıları için).

    Zamanlama görevi bağlamında Claude'un araç çağrısı sırasında doğrudan WhatsApp'a
    mesaj göndermesi duplicate'e yol açar. Bu nedenle mesaja ek talimat eklenerek
    Claude'un yalnızca metin yanıtı döndürmesi sağlanır; asıl gönderim buradan yapılır.
    """
    import httpx

    # Scheduler bağlamı: Claude'un araç bildirimleri (⚙️ curl calls) yerine
    # yalnızca metin yanıtı döndürmesi isteniyor — duplicate WhatsApp mesajını önler.
    _SCHEDULER_SUFFIX = (
        "\n\n[ZAMANLAMA GÖREVİ: Bu mesaj bir arka plan zamanlayıcısından geliyor. "
        "Araç çağrıları (Bash, WebFetch vb.) sırasında WhatsApp bildirim curl'ü GÖNDERME. "
        "Yalnızca metin yanıtı döndür — scheduler yanıtı otomatik olarak iletecektir.]"
    )
    augmented_message = message + _SCHEDULER_SUFFIX

    try:
        timeout = float(get_settings().bridge_client_timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{get_settings().claude_bridge_url}/query",
                headers={"X-Api-Key": get_settings().api_key.get_secret_value()},
                json={"session_id": "main", "message": augmented_message, "silent": silent},
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data.get("answer", "").strip()
            if answer:
                await _send_notification(answer)
    except Exception as e:
        error_detail = repr(e) or type(e).__name__
        logger.error("Bridge query başarısız (scheduled): %s", error_detail)
        await _send_notification(t("scheduler.task_error", "tr", error=error_detail))


# ── Takvim hatırlatıcıları ────────────────────────────────────────

async def _check_reminders() -> None:
    """Her dakika çalışır — takvim hatırlatıcılarını kontrol eder."""
    from ..adapters.messenger import get_messenger
    from .calendar import check_and_notify_reminders

    if not get_settings().owner_id:
        return

    async def _send(text: str):
        await get_messenger().send_text(get_settings().owner_id, text)

    await check_and_notify_reminders(_send)


# ── Tek seferlik job (mevcut API) ─────────────────────────────────

def add_one_shot_job(job_id: str, run_at: float, message: str) -> None:
    """Belirli bir zamanda WhatsApp mesajı gönder."""
    import datetime
    _scheduler.add_job(
        _send_notification,
        trigger="date",
        run_date=datetime.datetime.fromtimestamp(run_at),
        id=job_id,
        args=[t("scheduler.task_reminder", "tr", message=message)],
        replace_existing=True,
    )


# ── Otomatik periyodik yedekleme (BACKUP-10) ─────────────────────

_AUTO_BACKUP_JOB_ID = "system_auto_backup"


def _register_auto_backup_job() -> None:
    """AUTO_BACKUP_ENABLED=true ise APScheduler'a sistem yedekleme cron'u ekler.

    OCP: Mevcut start_scheduler() koduna dokunulmadan ayrı fonksiyon olarak eklendi.
    SRP: Yalnızca kayıt mantığını içerir; iş mantığı AutoBackupJob'da.
    """
    cfg = get_settings()
    if not cfg.auto_backup_enabled:
        logger.debug("Otomatik yedekleme devre dışı (AUTO_BACKUP_ENABLED=false)")
        return

    try:
        fields = _parse_cron(cfg.auto_backup_cron)
    except ValueError as exc:
        logger.error("Geçersiz AUTO_BACKUP_CRON ifadesi: %s — otomatik yedekleme kaydedilemedi", exc)
        return

    _scheduler.add_job(
        _run_auto_backup,
        trigger="cron",
        id=_AUTO_BACKUP_JOB_ID,
        replace_existing=True,
        **fields,
    )
    logger.info(
        "Otomatik yedekleme kaydedildi: cron=%r job_id=%s",
        cfg.auto_backup_cron, _AUTO_BACKUP_JOB_ID,
    )


async def _run_auto_backup() -> None:
    """APScheduler tarafından çağrılan otomatik yedekleme entrypoint'i."""
    from .backup._auto_backup import get_auto_backup_job

    logger.info("Otomatik yedekleme tetiklendi")
    try:
        job = get_auto_backup_job()
        await job.run()
    except Exception as exc:
        logger.exception("Otomatik yedekleme beklenmedik hata: %s", exc)


# ── Yardımcı ─────────────────────────────────────────────────────

def _parse_cron(expr: str) -> dict:
    """5-alan cron string'ini APScheduler CronTrigger kwargs'ına çevirir.

    Geçerli alan aralıkları:
      dakika:     0-59
      saat:       0-23
      ay-gün:     1-31
      ay:         1-12
      hafta-gün:  0-7  (0 ve 7 = Pazar)

    Desteklenen formatlar: *, */n, n, n-m, n,m (virgüllü liste)
    Geçersiz değer → ValueError.
    """
    import re

    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Geçersiz cron ifadesi (5 alan gerekli): {expr!r}")

    # (alan_adı, min_değer, max_değer)
    _FIELD_RANGES: tuple[tuple[str, int, int], ...] = (
        ("minute",      0, 59),
        ("hour",        0, 23),
        ("day",         1, 31),
        ("month",       1, 12),
        ("day_of_week", 0,  7),
    )

    # Tek bir cron token'ını doğrula (*,  */n, n, n-m, n,m,n)
    _TOKEN_RE = re.compile(
        r"^\*$"                   # *
        r"|^\*/(\d+)$"            # */n
        r"|^(\d+)$"               # n
        r"|^(\d+)-(\d+)$"         # n-m
        r"|^(\d+(?:,\d+)+)$"      # n,m,...
    )

    def _check_token(token: str, lo: int, hi: int, field: str) -> None:
        m = _TOKEN_RE.match(token)
        if m is None:
            raise ValueError(
                f"Geçersiz cron alanı {field!r}: {token!r} tanınan formatlarda değil"
            )
        # */n — n > 0 ve aralıkta
        if m.group(1) is not None:
            n = int(m.group(1))
            if n == 0:
                raise ValueError(f"Geçersiz cron alanı {field!r}: */0 geçersiz adım")
        # tek sayı
        elif m.group(2) is not None:
            n = int(m.group(2))
            if not (lo <= n <= hi):
                raise ValueError(
                    f"Geçersiz cron alanı {field!r}: {n} aralık dışı [{lo}-{hi}]"
                )
        # n-m aralığı
        elif m.group(3) is not None:
            a, b = int(m.group(3)), int(m.group(4))
            if not (lo <= a <= hi and lo <= b <= hi and a <= b):
                raise ValueError(
                    f"Geçersiz cron alanı {field!r}: {a}-{b} geçersiz aralık [{lo}-{hi}]"
                )
        # virgüllü liste
        elif m.group(5) is not None:
            for val_str in m.group(5).split(","):
                v = int(val_str)
                if not (lo <= v <= hi):
                    raise ValueError(
                        f"Geçersiz cron alanı {field!r}: {v} aralık dışı [{lo}-{hi}]"
                    )

    for part, (field_name, lo, hi) in zip(parts, _FIELD_RANGES):
        _check_token(part, lo, hi, field_name)

    keys = ("minute", "hour", "day", "month", "day_of_week")
    return dict(zip(keys, parts))


# ── Startup / Shutdown hook'ları (registry tarafından çağrılır) ──────────────

async def lifecycle_startup() -> None:
    if not _APSCHEDULER_AVAILABLE:
        logger.warning("apscheduler kurulu değil — scheduler başlatılamıyor (RESTRICT_SCHEDULER=true ise beklenen durum)")
        return
    from ..config import settings
    await start_scheduler()
    try:
        from ..store.repositories.settings_repo import _sync_user_setting_get
        saved_tz = _sync_user_setting_get(settings.owner_id, "timezone")
        if saved_tz:
            await apply_timezone(saved_tz)
            logger.info("Kullanıcı timezone tercihi yüklendi: %s", saved_tz)
    except Exception as exc:
        # BUG-FEAT-1: hata durumunda settings.timezone fallback uygula
        logger.warning("Timezone ayarı yüklenemedi, varsayılan kullanılıyor: %s", exc)
        await apply_timezone(settings.timezone)


async def lifecycle_shutdown() -> None:
    await stop_scheduler()
