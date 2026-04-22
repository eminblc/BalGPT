"""Çıktı filtresi — tehlikeli içerikleri temizler (SRP).

filter_response() — satır bazlı temizlik; placeholder ile değiştirir.
pdf_importer tarafından PDF yanıtlarını denetlemek için kullanılır.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_PLACEHOLDER = "[GÜVENLİK FİLTRESİ: tehlikeli içerik engellendi]"

# Her desen (threat_type, compiled_pattern) çifti olarak tutulur.
# threat_type log ve WhatsApp uyarısında kullanılır.
_RULES: list[tuple[str, re.Pattern[str]]] = [
    # Dosya sistemi yıkım komutları
    ("rm -rf",              re.compile(r"rm\s+-rf", re.IGNORECASE)),
    ("dd if=/dev",          re.compile(r"dd\s+if=/dev", re.IGNORECASE)),
    ("mkfs",                re.compile(r"mkfs\b", re.IGNORECASE)),
    ("shred",               re.compile(r"\bshred\b", re.IGNORECASE)),
    ("fork bomb",           re.compile(r":\(\)\{.*\}", re.DOTALL)),
    # Kernel / donanım tetikleyiciler
    ("/proc/sysrq-trigger", re.compile(r"/proc/sysrq-trigger", re.IGNORECASE)),
    # Yedeksiz veritabanı yıkım sorguları
    ("DROP TABLE",          re.compile(r"DROP\s+TABLE", re.IGNORECASE)),
    ("TRUNCATE TABLE",      re.compile(r"TRUNCATE\s+TABLE", re.IGNORECASE)),
    ("DELETE FROM",         re.compile(r"DELETE\s+FROM\s+\w+\s*;", re.IGNORECASE)),
    # Kritik sistem dosyalarına yazma
    ("write /etc/passwd",   re.compile(r">\s*/etc/passwd")),
    ("write /etc/shadow",   re.compile(r">\s*/etc/shadow")),
    ("write .ssh",          re.compile(r">\s*~?/.ssh/")),
    # Sistem kapatma / yeniden başlatma — yalnızca komut bağlamında (teknik açıklama false-positive'ini önler)
    ("shutdown",            re.compile(r"(?:^|[;&|`$]|\bsudo\b|\bexec\b)\s*shutdown\b", re.IGNORECASE | re.MULTILINE)),
    ("poweroff",            re.compile(r"(?:^|[;&|`$]|\bsudo\b)\s*poweroff\b", re.IGNORECASE | re.MULTILINE)),
    ("systemctl poweroff/halt", re.compile(r"systemctl\s+(poweroff|halt)\b", re.IGNORECASE)),
    # Kritik process öldürme
    ("pkill -9",            re.compile(r"pkill\s+-9", re.IGNORECASE)),
    ("kill -9 PID 1",       re.compile(r"kill\s+-9\s+1\b")),
    # SEC-A5: Eksik GUARDRAILS kategorileri eklendi
    # İzin yönetimi
    ("chmod -R wide",       re.compile(r"chmod\s+-R\s+[0-7]*7[0-7]*\s+/", re.IGNORECASE)),
    # Git yıkıcı işlemler
    ("git push --force",    re.compile(r"git\s+push\s+.*--force", re.IGNORECASE)),
    ("git reset --hard",    re.compile(r"git\s+reset\s+--hard", re.IGNORECASE)),
    # Pipe-to-shell RCE
    ("curl|bash RCE",       re.compile(r"curl\s+\S+\s*\|\s*(bash|sh)\b", re.IGNORECASE)),
    ("wget|bash RCE",       re.compile(r"wget\s+.*-O\s*-.*\|\s*(bash|sh)\b", re.IGNORECASE | re.DOTALL)),
    ("base64|sh",           re.compile(r"base64\s+-d.*\|\s*(bash|sh)\b", re.IGNORECASE | re.DOTALL)),
    # Crontab silme
    ("crontab -r",          re.compile(r"crontab\s+-r\b", re.IGNORECASE)),
    # SSH authorized_keys değiştirme
    ("ssh authorized_keys", re.compile(r">>\s*~?/\.ssh/authorized_keys")),
    # Güvenlik duvarı devre dışı
    ("iptables -F",         re.compile(r"iptables\s+-F\b", re.IGNORECASE)),
    ("ufw disable",         re.compile(r"ufw\s+disable\b", re.IGNORECASE)),
    # Docker toplu silme
    ("docker rm all",       re.compile(r"docker\s+rm\s+.*\$\(docker\s+ps", re.IGNORECASE | re.DOTALL)),
    # eval/exec — yalnızca obfuscation kalıpları; meşru eval() açıklamalarını engellemez
    ("python eval obfuscation",  re.compile(
        r"\beval\s*\(\s*(base64|__import__|compile\s*\(|bytes\s*\(|chr\s*\()",
        re.IGNORECASE,
    )),
    ("python exec obfuscation",  re.compile(
        r"\bexec\s*\(\s*(compile\s*\(|__import__|base64|bytes\s*\(|chr\s*\()",
        re.IGNORECASE,
    )),
]


def filter_response(text: str) -> tuple[str, list[str]]:
    """
    Tehlikeli desenleri metinden temizler.

    Returns:
        (temizlenmiş_metin, tetiklenen_kural_adları)
    """
    if not text:
        return text, []

    blocked: list[str] = []
    lines = text.split("\n")
    cleaned: list[str] = []

    for line in lines:
        matched_rules: list[str] = []
        for name, pattern in _RULES:
            if pattern.search(line):
                matched_rules.append(name)
        if matched_rules:
            blocked.extend(matched_rules)
            cleaned.append(_PLACEHOLDER)
        else:
            cleaned.append(line)

    return "\n".join(cleaned), blocked


