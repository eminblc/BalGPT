"""Proje iskelet oluşturucu — klasör ve markdown dosyaları (SRP).

Sorumluluk: Proje dizini ile başlangıç dosyalarını oluşturmak.
Veri erişimi yok; dosya sistemi işlemleri bu modüle aittir.
"""
from __future__ import annotations

from pathlib import Path


def _build_md_content(
    filename: str,
    name: str,
    description: str,
    project_dir: Path,
    ai_overrides: dict | None = None,
) -> str:
    if filename == "CLAUDE.md":
        base = f"# {name}\n\n{description}\n\n## Proje Kök Dizini\n`{project_dir}`\n"
        if ai_overrides:
            stack = ai_overrides.get("stack") or []
            directories = ai_overrides.get("directories") or []
            architecture = ai_overrides.get("architecture") or ""
            extra = ""
            if stack:
                extra += "\n## Stack\n" + "".join(f"- {s}\n" for s in stack)
            if directories:
                extra += "\n## Klasör Yapısı\n" + "".join(f"- `{d}`\n" for d in directories)
            if architecture:
                extra += f"\n## Mimari\n{architecture}\n"
            base += extra
        return base
    if filename == "AGENT.md":
        return f"# {name} — Agent\n\n## Mission\n{description}\n"
    if filename == "BACKLOG.md":
        return (
            f"# Backlog — {name}\n\n"
            f"## 🔴 Kritik\n\n| # | Başlık | Tarih |\n|---|--------|-------|\n\n"
            f"## ✅ Tamamlanan\n"
        )
    if filename == "README.md":
        return f"# {name}\n\n{description}\n"
    return ""


def _scaffold_project(
    project_dir: Path,
    name: str,
    description: str,
    level: str = "full",
    mds: list[str] | None = None,
    ai_overrides: dict | None = None,
) -> None:
    """Klasör ve dosyaları seçilen seviyede oluştur.

    level:
      "full"    → src/ + tests/ + outputs/ + md dosyaları
      "minimal" → outputs/ + md dosyaları
      "none"    → sadece boş klasör

    mds=None → level'a göre varsayılan dosya seti.
    mds=[]   → hiçbir .md oluşturulmaz.
    mds=[…]  → yalnızca belirtilen dosyalar.
    """
    project_dir.mkdir(parents=True, exist_ok=True)

    if level == "full":
        (project_dir / "src").mkdir(exist_ok=True)
        (project_dir / "tests").mkdir(exist_ok=True)
        (project_dir / "outputs").mkdir(exist_ok=True)
        effective_mds = mds if mds is not None else ["CLAUDE.md", "AGENT.md", "BACKLOG.md", "README.md"]

    elif level == "minimal":
        (project_dir / "outputs").mkdir(exist_ok=True)
        effective_mds = mds if mds is not None else ["README.md"]

    else:  # "none"
        effective_mds = mds if mds is not None else []

    for filename in effective_mds:
        content = _build_md_content(filename, name, description, project_dir, ai_overrides)
        if content:
            (project_dir / filename).write_text(content, encoding="utf-8")
