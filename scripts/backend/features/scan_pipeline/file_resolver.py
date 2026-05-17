"""Taranacak dosyaları glob pattern'larından çözer."""
import fnmatch
from pathlib import Path


class FileResolver:
    """SRP: glob pattern → dosya listesi."""

    def resolve(
        self,
        project_path: str,
        target_patterns: list[str],
        exclude_patterns: list[str],
    ) -> list[str]:
        """
        Göreceli dosya yollarını döndür (project_path'e göre).
        - target_patterns: dahil edilecek glob'lar
        - exclude_patterns: hariç tutulacak glob'lar
        - Döndürülen liste: projeye göreceli string yollar, sıralı
        """
        root = Path(project_path)
        included: set[Path] = set()

        for pattern in target_patterns:
            included.update(root.glob(pattern))

        result: list[str] = []
        for p in sorted(included):
            if not p.is_file():
                continue
            rel = str(p.relative_to(root))
            # Exclude kontrolü
            if any(fnmatch.fnmatch(rel, ex) or fnmatch.fnmatch(p.name, ex)
                   for ex in exclude_patterns):
                continue
            result.append(rel)

        return result

    def split_into_chunks(
        self, files: list[str], chunk_size: int = 15
    ) -> list[list[str]]:
        """
        Dosyaları chunk'lara böl — her chunk bir scanner agent'a gider.
        chunk_size: token bütçesine göre ayarla (default 15 dosya/agent).
        """
        return [files[i:i + chunk_size] for i in range(0, len(files), chunk_size)]
