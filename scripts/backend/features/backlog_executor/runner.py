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

# Bridge'in HTTP 200 + boş `answer` ile sahte tamamlama döndürmesini engellemek
# için minimum kabul edilebilir cevap uzunluğu. Claude Code gerçek iş yaptığında
# en azından bir özet cümle (>= ~40 karakter) döner; bunun altı sessiz exit kabul
# edilir ve item failed olarak işaretlenir.
_MIN_ANSWER_LEN = 40

# Process-wide serialization of backlog runs.
# "Tümü" dosya seçiminde menu.py 3 ayrı POST atıyor; her biri kendi
# BackgroundTask'ında BacklogExecutorAgent().run() çağırıyor. Lock olmadan
# 3 run aynı progress.json'a aynı anda yazıyor (race) ve aynı cancel flag'ini
# birbirinin altından temizliyor. Bu Lock tüm run() çağrılarını seri hale
# getirir: ilk run bitmeden ikincisi başlamaz.
_RUN_LOCK = asyncio.Lock()

# Model alias → tam Claude Code CLI model ID'si (llm_factory._SCAN_MODEL_ALIASES ile senkron)
_MODEL_ALIASES: dict[str, str] = {
    "haiku":  "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-8",
    "fable":  "claude-fable-5",
}


def _resolve_model(model: str | None) -> str:
    """Alias'ı tam model ID'sine çevir; alias değilse olduğu gibi döndür; boşsa "" döndür."""
    if not model:
        return ""
    return _MODEL_ALIASES.get(model.lower().strip(), model.strip())


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
        model: str | None = None,
        backlog_path: str | None = None,
        effort: str | None = None,
        thinking: bool = False,
    ) -> ExecutorResult:
        """BACKLOG item'larını çalıştır.

        Args:
            project_id:   DB'deki proje ID'si.
            prefix:       Yalnızca bu prefix'li item'ları işle (boşsa tümü).
            max_items:    Tek çalışmada işlenecek maksimum item sayısı (0 = tümü).
            parallel:     Eşzamanlı Bridge istekleri (Semaphore büyüklüğü).
            dry_run:      True ise Bridge'e istek atmadan item'ları done olarak işaretle.
            model:        Opsiyonel model alias ("haiku" | "sonnet" | "opus") veya tam ad.
                          Verilmezse Claude Code CLI varsayılan modeli kullanır.
            backlog_path: Belirli BACKLOG.md dosyasının tam yolu. None → proje kökündeki BACKLOG.md.
            effort:       Opsiyonel Claude Code CLI effort seviyesi
                          ("low" | "medium" | "high" | "max").
            thinking:     Extended Thinking on/off toggle. False (varsayılan) iken
                          effort seviyesi seçili olsa bile Bridge'e gönderilmez
                          (VS Code UX'iyle birebir aynı davranış).

        Returns:
            ExecutorResult — tamamlama istatistikleri.

        Raises:
            ValueError: Proje DB'de bulunamazsa.
            FileNotFoundError: Projede BACKLOG.md yoksa.
        """
        from ...guards.runtime_state import (
            clear_backlog_cancel,
            enter_backlog_run,
            exit_backlog_run,
            is_backlog_cancel_requested,
        )

        # Kuyruk sayacı + cancel-all-queued semantiği:
        #  - enter_backlog_run() True döndürdüyse bu run kuyruğa giren ilk
        #    run'dır → cancel flag'ini temizleyebilir (taze başlangıç).
        #  - False döndürdüyse aynı kuyrukta bekleyen başka run(lar) var;
        #    cancel state'ini miras alır → flag set ise hemen atlayacak.
        is_first = enter_backlog_run()
        try:
            # Process-wide serialization: birden çok eşzamanlı run() (örn.
            # "Tümü" dosya seçimi 3 paralel BackgroundTask başlatır) burada
            # kuyruğa girer. progress.json + cancel race böylece elenir.
            async with _RUN_LOCK:
                if is_first:
                    clear_backlog_cancel()
                # Eğer bu run kuyrukta beklerken bir önceki run cancel
                # alıp flag'i set ettiyse, hiç başlamadan dön.
                if is_backlog_cancel_requested():
                    logger.info(
                        "BacklogExecutorAgent.run: %s — kuyrukta iken cancel "
                        "görüldü, run atlandı (backlog_path=%s).",
                        project_id, backlog_path or "BACKLOG.md",
                    )
                    return ExecutorResult(
                        project_id=project_id,
                        prefix=prefix,
                        total=0,
                        completed=0,
                        failed=0,
                        skipped=0,
                        run_id="",
                    )
                return await self._run_locked(
                    project_id, prefix, max_items, parallel, dry_run, model,
                    backlog_path, effort, thinking,
                )
        finally:
            exit_backlog_run()

    async def _run_locked(
        self,
        project_id: str,
        prefix: str,
        max_items: int,
        parallel: int,
        dry_run: bool,
        model: str | None,
        backlog_path: str | None,
        effort: str | None,
        thinking: bool,
    ) -> ExecutorResult:
        """run()'ın gerçek gövdesi — _RUN_LOCK altında tek seferde bir kez koşar.

        Cancel flag'i artık run() tarafından (kuyruk semantiğine uygun şekilde)
        yönetiliyor; bu metot içeride flag'e dokunmaz, sadece okur.
        """
        started_at = time.time()

        # 1. Proje kontrolü
        project = await project_get(project_id)
        if project is None:
            raise ValueError(f"Proje bulunamadı: {project_id!r}")

        project_root: str = project["path"]

        # 2. BACKLOG.md kontrolü — belirtilen yol varsa kullan, yoksa varsayılan
        resolved_backlog = Path(backlog_path) if backlog_path else Path(project_root) / "BACKLOG.md"
        if not resolved_backlog.exists():
            raise FileNotFoundError(
                f"BACKLOG.md bulunamadı: {resolved_backlog}"
            )

        # 2b. Önceki run'dan kalan in_progress orphan'ları pending'e geri çevir.
        # Çökme/iptal sonucu `- [~]` veya 🔄 prefix'li satırlar kalıyorsa,
        # `get_pending_items` onları görmüyordu (sadece `- [ ]` döndürüyor).
        try:
            BacklogParser().reset_stranded_items(resolved_backlog)
        except Exception as _reset_err:  # noqa: BLE001
            logger.warning(
                "BacklogExecutorAgent.run: stranded item recovery başarısız (%s) — %s",
                resolved_backlog.name, _reset_err,
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
        items = parser.get_pending_items(resolved_backlog, prefix)
        if max_items and max_items > 0:
            items = items[:max_items]

        # İlerleme takibi — progress.json yaz (status endpoint okur)
        _PROGRESS_FILE = Path(__file__).parent.parent.parent.parent.parent / "data" / "backlog_progress.json"
        import json as _json
        _progress = {
            "run_id":        run_id,
            "project_id":    project_id,
            "backlog_file":  resolved_backlog.name,
            "total_items":   len(items),
            "completed":     0,
            "failed":        0,
            "started_at":    started_at,
            "status":        "running",
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
        progress_lock = asyncio.Lock()  # progress.json eşzamanlı yazma koruması
        resolved_model = _resolve_model(model)
        # Effort whitelist — geçersiz/None → "" (Bridge body'ye eklenmez)
        resolved_effort = effort if effort in {"low", "medium", "high", "max"} else ""
        # Thinking off iken effort gönderilmez (VS Code UX'iyle birebir aynı)
        effective_effort = resolved_effort if thinking else ""
        tasks = [
            self._execute_item(
                item, resolved_backlog, project_root, sem, dry_run, file_lock,
                _progress, _PROGRESS_FILE, progress_lock, resolved_model,
                effective_effort, bool(thinking), run_id,
            )
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

        # BACKLOG.md dışındaki dosyalar tamamen bitince backlog_dones/ klasörüne taşı
        self._maybe_archive_backlog(resolved_backlog, project_root, parser)

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
        progress: dict,
        progress_file: Path,
        progress_lock: asyncio.Lock,
        model: str = "",
        effort: str = "",
        thinking: bool = False,
        run_id: str = "",
    ) -> bool:
        """Tek bir BACKLOG item'ını işle.

        Args:
            item:          İşlenecek BacklogItem.
            backlog_path:  BACKLOG.md dosyasının Path'i.
            project_root:  Proje kök dizini.
            sem:           Eşzamanlılık sınırlayıcı Semaphore.
            dry_run:       True ise Bridge çağrısı yapılmadan done olarak işaretlenir.
            file_lock:     BACKLOG.md dosyasına eşzamanlı yazma koruması için Lock.
            progress:      Paylaşılan ilerleme dict'i (run() tarafından oluşturulur).
            progress_file: progress.json Path'i.
            progress_lock: progress dict/dosyasına eşzamanlı erişim kilidi.
            model:         Bridge'e gönderilecek Claude Code CLI model ID'si (alias çözülmüş).
                           Boş string → Bridge default'unu kullanır.

        Returns:
            True → başarı, False → hata.
        """
        async with sem:
            from ...guards.runtime_state import is_backlog_cancel_requested
            if is_backlog_cancel_requested():
                logger.info(
                    "BacklogExecutorAgent._execute_item: %s — iptal nedeniyle atlandı",
                    item["item_id"],
                )
                return False

            parser = BacklogParser()
            async with file_lock:
                parser.mark_in_progress(backlog_path, item["item_id"])

            if dry_run:
                async with file_lock:
                    parser.mark_done(backlog_path, item["item_id"])
                async with progress_lock:
                    progress["completed"] += 1
                    try:
                        import json as _json
                        progress_file.write_text(_json.dumps(progress, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass
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
                    # PERF-INIT-1: Bridge'in 15KB'lık agentIntro init prompt'unu atla —
                    # executor prompt'u zaten dosya bağlamını + kuralları kendi sağlıyor.
                    "bare": True,
                }
                if model:
                    body["model"] = model
                # Effort + thinking iki bağımsız ayar: thinking off iken Bridge'e
                # effort gönderilmez (yukarıda effective_effort=""ye düşürüldü).
                if effort and thinking:
                    body["effort"] = effort
                    body["thinking"] = True
                _pp = Path(project_root).resolve()
                if str(_pp).startswith(str(_root_dir.resolve()) + "/") or _pp == _root_dir.resolve():
                    body["project_path"] = str(_pp)
                async with httpx.AsyncClient(timeout=1800.0) as client:
                    response = await client.post(url, json=body, headers=headers)

                if response.status_code != 200:
                    logger.error(
                        "BacklogExecutorAgent._execute_item: %s — HTTP %d",
                        item["item_id"], response.status_code,
                    )
                    await self._record_failure(
                        item, backlog_path, parser, file_lock,
                        progress, progress_file, progress_lock,
                    )
                    return False

                # HTTP 200 yeterli değil: Bridge, Claude Code CLI exit code 0 ile
                # boş cevap verirse de 200 döner (server.js:988). Sahte tamamlamayı
                # önlemek için response body'sini doğrula.
                try:
                    payload = response.json()
                except Exception as parse_err:  # noqa: BLE001
                    logger.error(
                        "BacklogExecutorAgent._execute_item: %s — JSON parse hatası: %s",
                        item["item_id"], parse_err,
                    )
                    await self._record_failure(
                        item, backlog_path, parser, file_lock,
                        progress, progress_file, progress_lock,
                    )
                    return False

                answer = (payload.get("answer") or "").strip()
                cancelled = bool(payload.get("cancelled"))
                # EXEC-PROMPT-001: Prompt sözleşmesi modelden son satırda
                # `STATUS: ok` veya `STATUS: failed` ister. Bu satır mevcutsa
                # mekanik olarak okunur; yoksa eski davranış (uzunluk eşiği)
                # geriye-uyumluluk için korunur.
                status_line = answer.splitlines()[-1].strip().upper() if answer else ""
                status_failed = status_line == "STATUS: FAILED"
                status_ok = status_line == "STATUS: OK"
                if cancelled or len(answer) < _MIN_ANSWER_LEN or status_failed:
                    logger.error(
                        "BacklogExecutorAgent._execute_item: %s — Bridge boş/eksik yanıt "
                        "veya STATUS: failed döndü (cancelled=%s, answer_len=%d, "
                        "status_failed=%s). Sahte tamamlama önlendi.",
                        item["item_id"], cancelled, len(answer), status_failed,
                    )
                    await self._record_failure(
                        item, backlog_path, parser, file_lock,
                        progress, progress_file, progress_lock,
                    )
                    return False

                async with file_lock:
                    parser.mark_done(backlog_path, item["item_id"])
                async with progress_lock:
                    progress["completed"] += 1
                    try:
                        import json as _json
                        progress_file.write_text(_json.dumps(progress, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass
                logger.info(
                    "BacklogExecutorAgent._execute_item: %s tamamlandı "
                    "(answer_len=%d, status_ok=%s).",
                    item["item_id"], len(answer), status_ok,
                )
                # TOKEN-PER-ITEM-1: Bridge'den dönen usage verisini kaydet
                await self._record_item_token_usage(item["item_id"], run_id, payload)
                return True

            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "BacklogExecutorAgent._execute_item: %s için istisna — %s",
                    item["item_id"], exc,
                )
                await self._record_failure(
                    item, backlog_path, parser, file_lock,
                    progress, progress_file, progress_lock,
                )
                return False

    async def _record_failure(
        self,
        item: BacklogItem,
        backlog_path: Path,
        parser: BacklogParser,
        file_lock: asyncio.Lock,
        progress: dict,
        progress_file: Path,
        progress_lock: asyncio.Lock,
    ) -> None:
        """Item'ı failed olarak işaretle ve progress.json'ı güncelle.

        SRP: Hata yolu üç ayrı şube tarafından kullanılıyordu (HTTP error,
        boş yanıt doğrulaması, exception). Tek helper hâline alındı.
        """
        async with file_lock:
            parser.mark_failed(backlog_path, item["item_id"])
        async with progress_lock:
            progress["failed"] += 1
            try:
                import json as _json
                progress_file.write_text(_json.dumps(progress, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass

    async def _record_item_token_usage(
        self,
        item_id: str,
        run_id: str,
        payload: dict,
    ) -> None:
        """Bridge yanıtından usage verisini okuyarak task_token_usage tablosuna yazar.

        TOKEN-PER-ITEM-1: hata durumunda sessizce atlar — token kaydı kritik değil.
        """
        usage = payload.get("usage") or {}
        input_tokens: int = usage.get("input_tokens", 0)
        if input_tokens <= 0:
            return  # usage bilgisi yok — eski Bridge sürümü veya dry-run

        try:
            from ...store.repositories import token_stat_repo
            model_id: str = payload.get("model_id") or "(unknown)"
            await token_stat_repo.record_task_usage(
                task_id=item_id,
                task_type="backlog_item",
                run_id=run_id or None,
                model_id=model_id,
                model_name=model_id,
                backend="bridge",
                input_tokens=input_tokens,
                output_tokens=usage.get("output_tokens", 0),
                cache_read=usage.get("cache_read_input_tokens", 0),
                cache_write=usage.get("cache_creation_input_tokens", 0),
            )
        except Exception as _te:
            logger.warning(
                "BacklogExecutorAgent: per-item token kaydı başarısız (%s): %s",
                item_id, _te,
            )

    def _maybe_archive_backlog(
        self,
        backlog_file: Path,
        project_root: str,
        parser: BacklogParser,
    ) -> None:
        """BACKLOG.md dışındaki dosyayı, hiç pending item kalmadıysa backlog_dones/ klasörüne taşır.

        Koşullar:
          - Dosya adı tam olarak "BACKLOG.md" değil (proje ana backlog'u korunur).
          - Dosyada hâlâ `- [ ]` pending item yok (tamamlanmış ya da başarısız olmuş).
        """
        if backlog_file.name == "BACKLOG.md":
            return

        remaining = parser.get_pending_items(backlog_file, prefix="")
        if remaining:
            logger.debug(
                "_maybe_archive_backlog: %s içinde %d pending item kaldı — taşınmıyor",
                backlog_file.name, len(remaining),
            )
            return

        done_dir = Path(project_root) / "backlog_dones"
        try:
            done_dir.mkdir(parents=True, exist_ok=True)
            dest = done_dir / backlog_file.name
            # Aynı isimli dosya zaten varsa üzerine yaz
            backlog_file.rename(dest)
            logger.info(
                "_maybe_archive_backlog: %s → backlog_dones/%s",
                backlog_file.name, backlog_file.name,
            )
        except Exception as _err:
            logger.warning(
                "_maybe_archive_backlog: taşıma başarısız %s — %s",
                backlog_file.name, _err,
            )

    def _build_prompt(self, item: BacklogItem, project_root: str) -> str:
        """Bridge'e gönderilecek implementation promptunu oluştur.

        Args:
            item:         Implement edilecek BacklogItem.
            project_root: Proje kök dizini (context için).

        Returns:
            Prompt metni.
        """
        comments_path = str(Path(project_root) / "EXECUTORS_COMMENTS.md")
        return (
            f"Proje: `{project_root}`\n\n"
            f"Görev:\n{item['text']}\n\n"
            f"Kurallar:\n"
            f"- Minimal değişiklik yap. Yalnızca görev için gerekli olanı düzenle.\n"
            f"- İş bitiminde 1–3 cümlelik ANLAMLI özet yaz: ne değiştirdiğini, hangi dosyaları "
            f"etkilediğini ya da yapılamadıysa nedenini (engel, eksik bilgi, halüsinasyon) net "
            f"açıkla. \"yapıldı.\" / \"yapılamadı.\" gibi tek kelimelik cevaplar YASAK — "
            f"yanıtın < 40 karakter ise executor item'ı failed kabul eder.\n"
            f"- Mesajın SON SATIRI mutlaka `STATUS: ok` veya `STATUS: failed` olmalı "
            f"(büyük harfli, başka karakter yok). Executor bu satıra göre item'ı done/failed "
            f"olarak işaretler; satır eksikse uzunluk eşiğine düşer.\n"
            f"- Tüm git komutları `git -C \"{project_root}\" ...` formatında — başka dizinde git ÇALIŞTIRMA, başka repo'ya dokunma.\n"
            f"- `git -C \"{project_root}\" status --porcelain` boşsa (hiç değişiklik yok) commit ATMA, durumu raporla ve bitir.\n"
            f"- `git -C \"{project_root}\" remote` boşsa commit ATMA; doluysa Conventional Commit mesajıyla (`feat:`/`fix:`/`refactor:`/`chore:`) commit at.\n"
            f"- `git push` YAPMA (kullanıcı ayrıca isterse yapılır).\n"
            f"- Kullanıcıya soru sormana veya görevi atlaman gerektiğinde (belirsizlik, eksik bilgi, "
            f"kullanıcı kararı gerektiren durum, risk vs.) DURMA ve SORU SORMA. "
            f"Bunun yerine `{comments_path}` dosyasına şu formatta bir madde EKLE "
            f"(dosya yoksa oluştur, varsa mevcut içeriğe append et — üzerine YAZMA):\n"
            f"  `- [{item['item_id']}] <yorumun veya sorun>`\n"
            f"  Ardından görevi mümkün olduğunca tamamlamaya çalış; tamamen blokluysa bitir.\n\n"
            f"**Önemli not:** Bu görev Claude Code tarafından otomatik oluşturulmuştur; "
            f"halüsinasyon (var olmayan dosya/satır/sembol) içerebilir. "
            f"Eğer görev bir halüsinasyon ise (dosya yok, satır numarası tutmuyor, sorun gerçekte mevcut değil vb.) "
            f"`{comments_path}` dosyasına şu formatta bir madde EKLE:\n"
            f"  `- [{item['item_id']}] HALÜSINASYON: <kısa açıklama>`\n"
            f"  Ardından görevi bitir."
        )
