"""Scan config'lerini data/scan_configs/ dizininden yükler."""
import json
from pathlib import Path

from .models import ScanConfig

_CONFIGS_DIR = Path(__file__).parent.parent.parent.parent.parent / "data" / "scan_configs"


class ScanConfigLoader:
    """SRP: yalnızca config yükleme."""

    def load(self, scan_type: str) -> ScanConfig:
        """scan_type.json'u yükle, yoksa FileNotFoundError."""
        path = _CONFIGS_DIR / f"{scan_type}.json"
        if not path.exists():
            raise FileNotFoundError(f"Scan config bulunamadı: {scan_type}")
        with path.open(encoding="utf-8") as f:
            return json.load(f)

    def list_available(self) -> list[str]:
        """Mevcut scan tiplerini listele."""
        if not _CONFIGS_DIR.exists():
            return []
        return [p.stem for p in _CONFIGS_DIR.glob("*.json")]
