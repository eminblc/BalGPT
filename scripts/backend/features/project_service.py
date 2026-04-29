"""Proje servis yöneticisi — tmux entegrasyonu ile başlatma/durdurma (SRP).

Sorumluluk: Proje servislerini tmux penceresinde yönetmek.
İş mantığı (proje CRUD, beta modu) project_crud.py'e aittir.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
import subprocess
from pathlib import Path

from ..store import sqlite_store as db
from ..i18n import t

logger = logging.getLogger(__name__)

# Shell injection için tehlikeli karakter kalıbı (SEC-A3: \n\r\x00 eklendi)
_UNSAFE_CMD_RE = re.compile(r"[;&|`$<>]|\$\(|`|\n|\r|\x00")

# tmux window adı doğrulama kalıbı (SEC-A7)
_WINDOW_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,50}$")


def _validate_service_cmd(cmd: str) -> str:
    """H5: Veritabanından gelen servis komutunu doğrula.

    Tehlikeli shell operatörlerini içeriyorsa ValueError fırlatır.
    """
    stripped = cmd.strip()
    if not stripped:
        raise ValueError("Boş servis komutu")
    if "\n" in stripped or "\r" in stripped or "\x00" in stripped:
        raise ValueError(f"Newline/null byte içeren komut reddedildi: {stripped!r}")
    if _UNSAFE_CMD_RE.search(stripped):
        raise ValueError(f"Güvensiz servis komutu reddedildi: {stripped!r}")
    return stripped


def _validate_service(svc: object, project_dir: Path) -> tuple[str, str, Path] | None:
    """Servis kaydını doğrula; geçerliyse (window, cmd, work_dir) döndür, yoksa None."""
    if not isinstance(svc, dict):
        logger.warning("ServiceValidator: geçersiz servis kaydı atlandı: %r", svc)
        return None

    window = svc.get("tmux_window")
    if not window:
        logger.warning("ServiceValidator: tmux_window eksik, servis atlandı: %s", svc.get("name"))
        return None
    if not _WINDOW_NAME_RE.match(window):
        logger.warning("ServiceValidator: geçersiz tmux window adı reddedildi: %r", window)
        return None

    try:
        cmd = _validate_service_cmd(svc.get("cmd", ""))
    except ValueError as exc:
        logger.error("ServiceValidator: komut reddedildi: window=%s hata=%s", window, exc)
        return None

    svc_cwd = svc.get("cwd", "")
    if svc_cwd:
        work_dir = (project_dir / svc_cwd).resolve()
        try:
            work_dir.relative_to(project_dir.resolve())
        except ValueError:
            logger.warning("ServiceValidator: güvensiz svc_cwd engellendi: %s", svc_cwd)
            return None
    else:
        work_dir = project_dir

    return window, cmd, work_dir


def _tmux_start_service(tmux_session: str, window: str, cmd: str, work_dir: Path) -> bool:
    """Tmux penceresi aç/seç, dizine geç, komutu başlat."""
    tmux_target = f"{tmux_session}:{window}"
    safe_cd = shlex.quote(str(work_dir))

    session_exists = subprocess.run(
        ["tmux", "has-session", "-t", tmux_session], capture_output=True,
    ).returncode == 0

    if not session_exists:
        result = subprocess.run(
            ["tmux", "new-session", "-d", "-s", tmux_session, "-n", window],
            capture_output=True,
        )
        if result.returncode != 0:
            logger.error("tmux new-session başarısız: session=%s stderr=%s",
                         tmux_session, result.stderr.decode(errors="replace"))
            return False
    else:
        window_exists = subprocess.run(
            ["tmux", "select-window", "-t", tmux_target], capture_output=True,
        ).returncode == 0
        if not window_exists:
            result = subprocess.run(
                ["tmux", "new-window", "-t", tmux_session, "-n", window],
                capture_output=True,
            )
            if result.returncode != 0:
                logger.error("tmux new-window başarısız: window=%s stderr=%s",
                             window, result.stderr.decode(errors="replace"))
                return False

    subprocess.run(["tmux", "send-keys", "-t", tmux_target, "C-c", ""])
    subprocess.run(["tmux", "send-keys", "-t", tmux_target, f"cd {safe_cd}", "Enter"],
                   capture_output=True)
    result = subprocess.run(
        ["tmux", "send-keys", "-t", tmux_target, cmd, "Enter"],
        capture_output=True,
    )
    if result.returncode != 0:
        logger.error("tmux send-keys başarısız: window=%s stderr=%s",
                     window, result.stderr.decode(errors="replace"))
        return False
    return True


async def start_project_services(project_id: str, sender: str, lang: str = "tr") -> None:
    """Projenin servislerini tmux penceresinde başlat."""
    from ..adapters.messenger import get_messenger
    messenger = get_messenger()

    project = await db.project_get(project_id)
    if not project:
        await messenger.send_text(sender, t("project_svc.not_found", lang, id=project_id))
        return

    try:
        meta = json.loads(project.get("metadata") or "{}")
    except Exception:
        meta = {}

    services = meta.get("services", [])
    if not isinstance(services, list):
        logger.warning("start_project_services: services liste değil, tip=%s", type(services))
        await messenger.send_text(sender, t("project_svc.invalid_config", lang, name=project["name"]))
        return
    if not services:
        await messenger.send_text(sender, t("project_svc.no_start_cmd", lang, name=project["name"]))
        return

    project_dir = Path(project["path"]).resolve()
    tmux_session = "services"

    for svc in services:
        validated = _validate_service(svc, project_dir)
        if validated is None:
            continue
        window, cmd, work_dir = validated
        await asyncio.to_thread(_tmux_start_service, tmux_session, window, cmd, work_dir)

    await db.project_update_status(project_id, "running")
    await messenger.send_text(sender, t("project_svc.started", lang, name=project["name"]))
    logger.info("start_project_services: %s", project_id)


async def stop_project_services(project_id: str, sender: str, lang: str = "tr") -> None:
    """Projenin servislerini port üzerinden durdur."""
    from ..adapters.messenger import get_messenger
    messenger = get_messenger()

    project = await db.project_get(project_id)
    if not project:
        await messenger.send_text(sender, t("project_svc.not_found", lang, id=project_id))
        return

    try:
        meta = json.loads(project.get("metadata") or "{}")
    except Exception:
        meta = {}

    services = meta.get("services", [])
    if not isinstance(services, list):
        logger.warning("stop_project_services: services liste değil, tip=%s", type(services))
        await messenger.send_text(sender, t("project_svc.invalid_config", lang, name=project["name"]))
        return
    if not services:
        await messenger.send_text(sender, t("project_svc.no_stop_cmd", lang, name=project["name"]))
        return

    killed = []
    for svc in services:
        if not isinstance(svc, dict):
            logger.warning("stop_project_services: geçersiz servis kaydı atlandı: %r", svc)
            continue

        port = svc.get("port")
        if port:
            try:
                port_int = int(port)
            except (TypeError, ValueError):
                logger.warning("Geçersiz port değeri reddedildi: %r", port)
                continue
            if not (1 <= port_int <= 65535):
                logger.warning("Port aralık dışı reddedildi: %d", port_int)
                continue
            await asyncio.to_thread(
                subprocess.run,
                ["fuser", "-k", f"{port_int}/tcp"],
                capture_output=True,
            )
            killed.append(f"{svc.get('name', '?')}:{port_int}")

    await db.project_update_status(project_id, "stopped")
    await messenger.send_text(sender, t("project_svc.stopped", lang, name=project["name"], services=", ".join(killed)))
    logger.info("stop_project_services: %s", project_id)
