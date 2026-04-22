"""Terminal executor — WhatsApp üzerinden shell komutu çalıştırma (FEAT-12a).

Yalnızca owner kullanabilir; tehlikeli komutlar admin TOTP onayı gerektirir.

Kullanım:
    from backend.features.terminal import execute_command, is_dangerous, TerminalResult
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from ..constants import TERMINAL_MAX_OUTPUT_CHARS

logger = logging.getLogger(__name__)

# Proje kökü: scripts/backend/features/ → ../../../ → proje kökü
_PROJECT_ROOT = Path(__file__).parents[3]

# guardrails_loader'dan gelmeyen ek tehlikeli ilk token'lar
_EXTRA_DANGEROUS: frozenset[str] = frozenset({
    "rm", "dd", "mkfs", "shred", "wipefs", "fdisk", "parted",
    "chmod", "chown", "chattr",
    "sudo", "su", "pkexec",
    "kill", "killall", "pkill",
    "reboot", "shutdown", "poweroff", "halt", "init",
    "mv",        # hedef bağlamına göre tehlikeli olabilir
    "truncate",
    "wget", "curl",   # indirme + çalıştırma zinciri için
    "pip", "pip3",    # paket kurulum/silme
    "apt", "apt-get", "dpkg",
    "systemctl", "service",
    "crontab",
    "useradd", "userdel", "usermod", "passwd", "visudo",
    "iptables", "ip6tables", "ufw", "nft",
    "mount", "umount",
    "docker", "podman",
    "git",        # force push, reset --hard gibi alt komutları var
    "ssh", "scp", "rsync",
    "nc", "netcat", "ncat",
    "python", "python3", "node", "ruby", "perl", "php",  # kod çalıştırma
    "bash", "sh", "zsh", "dash", "ksh",                  # sub-shell
    "eval", "exec",
})


@dataclass
class TerminalResult:
    """Shell komutu çalıştırma sonucu."""
    stdout: str          # stdout + stderr birleşik, max TERMINAL_MAX_OUTPUT_CHARS
    returncode: int      # Süreç çıkış kodu; zaman aşımında -1
    timed_out: bool      # True → komut timeout'a uğradı, süreç öldürüldü
    cwd: str = ""        # Komutun çalıştırıldığı dizin


def is_dangerous(cmd_str: str) -> bool:
    """Komutun tehlikeli sayılıp sayılmayacağını belirler.

    Kontroller:
      1. GUARDRAILS.md bash bloklarından türetilen hint words (guardrails_loader)
      2. _EXTRA_DANGEROUS sabit seti

    Her iki küme de ilk token kontrolü yapar. Ek olarak tüm token'lar
    EXTRA_DANGEROUS ile karşılaştırılır — zincirleme `&&` / `;` komutlarını yakalar.

    Kural: şüphe varsa tehlikeli say (false-negative yerine false-positive tercih edilir).
    """
    if not cmd_str or not cmd_str.strip():
        return False

    # GUARDRAILS.md'den gelen hint words (lazy import — modül başlar başlamaz
    # dosya okunmasın; ilk kullanımda yükle)
    from ..guards.guardrails_loader import load_hint_words
    hint_words = load_hint_words()

    # Kabaca token'lara böl (shell operatörleri: ; && || | ' " ` gibi karakterler
    # arasında bölme yapmak için basit split yeterli — güvenlik katmanı, tam parser değil)
    import shlex
    try:
        tokens = shlex.split(cmd_str)
    except ValueError:
        # Kapanmamış tırnak vb. — güvenli tarafta kal
        tokens = cmd_str.split()

    if not tokens:
        return False

    first = tokens[0].lower()

    # İlk token: guardrails + extra dangerous
    if first in hint_words or first in _EXTRA_DANGEROUS:
        logger.debug("is_dangerous: ilk token eşleşti → %r", first)
        return True

    # Tüm token'lar: extra dangerous (zincirleme komut: `ls && rm -rf ...`)
    for tok in tokens[1:]:
        t = tok.lower().lstrip("-")   # --force gibi flag'leri atla
        if t in _EXTRA_DANGEROUS:
            logger.debug("is_dangerous: zincir token eşleşti → %r", t)
            return True

    return False


def _sudo_stdin(cmd_str: str) -> bytes | None:
    """sudo komutu için SYSTEM_PSSWRD'yi döndürür; yoksa veya sudo yoksa None."""
    try:
        import shlex
        tokens = shlex.split(cmd_str)
    except ValueError:
        tokens = cmd_str.split()
    if "sudo" not in tokens:
        return None
    from ..config import settings
    pw = settings.system_psswrd.get_secret_value()
    return (pw + "\n").encode() if pw else None


def _inject_sudo_s(cmd_str: str) -> str:
    """'sudo ' → 'sudo -S ' (zaten -S varsa dokunma)."""
    if "sudo -S" in cmd_str:
        return cmd_str
    return cmd_str.replace("sudo ", "sudo -S ", 1)


async def execute_command(
    cmd_str: str,
    timeout: int = 30,
    cwd: str | Path | None = None,
) -> TerminalResult:
    """Shell komutunu çalıştır ve sonucu döndür.

    Args:
        cmd_str:  Çalıştırılacak shell komutu (shell=True — owner tek kullanıcı).
        timeout:  Saniye cinsinden zaman aşımı (varsayılan 30).
        cwd:      Çalışma dizini. None → proje kökü (_PROJECT_ROOT).

    Returns:
        TerminalResult  — stdout (truncated), returncode, timed_out.

    Not:
        stdout ve stderr ayrı toplanır; sudo şifre prompt satırları filtrelenir,
        ardından birleştirilerek döndürülür.
        Çıktı TERMINAL_MAX_OUTPUT_CHARS karakterle sınırlandırılır; uzunsa başına
        truncation uyarısı eklenir.
    """
    work_dir = str(cwd) if cwd is not None else str(_PROJECT_ROOT)

    # sudo içeren komutlarda -S flag ekle ve şifreyi stdin'e pipe et
    stdin_data = _sudo_stdin(cmd_str)
    run_cmd = _inject_sudo_s(cmd_str) if stdin_data is not None else cmd_str

    try:
        proc = await asyncio.create_subprocess_shell(
            run_cmd,
            stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=work_dir,
        )
    except Exception as exc:
        logger.error("execute_command: süreç başlatılamadı: %s", exc)
        return TerminalResult(
            stdout=f"❌ Komut başlatılamadı: {exc}",
            returncode=-1,
            timed_out=False,
            cwd=work_dir,
        )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(input=stdin_data), timeout=timeout
        )
        timed_out = False
        returncode = proc.returncode if proc.returncode is not None else -1
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except ProcessLookupError:
            pass
        logger.warning("execute_command: zaman aşımı (%ds) — %r", timeout, cmd_str[:80])
        return TerminalResult(
            stdout=f"⏱️ Komut {timeout} saniyede tamamlanamadı ve durduruldu.",
            returncode=-1,
            timed_out=True,
            cwd=work_dir,
        )

    out = stdout_bytes.decode(errors="replace") if stdout_bytes else ""
    err = stderr_bytes.decode(errors="replace") if stderr_bytes else ""
    # sudo şifre prompt satırlarını gizle
    err_clean = "\n".join(
        line for line in err.splitlines()
        if "password" not in line.lower() and "[sudo]" not in line
    )
    raw = (out + ("\n" + err_clean if err_clean else "")).strip()
    output = _truncate_output(raw)

    logger.info(
        "execute_command: returncode=%d, çıktı=%d karakter — %r",
        returncode, len(output), cmd_str[:80],
    )
    return TerminalResult(stdout=output, returncode=returncode, timed_out=False, cwd=work_dir)


def _truncate_output(text: str) -> str:
    """Çıktıyı TERMINAL_MAX_OUTPUT_CHARS ile sınırlandırır; uzunsa uyarı ekler."""
    if len(text) <= TERMINAL_MAX_OUTPUT_CHARS:
        return text
    truncated = text[-TERMINAL_MAX_OUTPUT_CHARS:]
    prefix = f"[⚠️ Çıktı uzun — son {TERMINAL_MAX_OUTPUT_CHARS} karakter gösteriliyor]\n\n"
    return prefix + truncated
