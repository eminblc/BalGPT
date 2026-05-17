"""External project HTTP registration helper (SRP).

ExternalProjectRegistrar: harici projelerin orchestrator'a HTTP üzerinden
kayıt ve kayıt silme akışlarını işler.
"""
from __future__ import annotations

import logging
from typing import Any

from .core import ProjectRegistry

logger = logging.getLogger(__name__)


class ExternalProjectRegistrar:
    """Harici projelerin orchestrator'a HTTP üzerinden kayıt akışını yönetir (SRP).

    ProjectRegistry üzerinden çalışır; HTTP request/response dönüşümünden sorumludur.
    Proje varlık kontrolü bu katmanda yapılır; kayıt işlemi ProjectRegistry'ye delege edilir.

    DIP: ProjectRegistry constructor'dan inject edilir.
    """

    def __init__(self, project_registry: ProjectRegistry) -> None:
        """
        Args:
            project_registry: Kayıt işlemlerini yürütecek ProjectRegistry nesnesi.
        """
        self._registry = project_registry

    async def handle_registration(
        self,
        project_id: str,
        bridge_url: str,
        **kwargs: Any,
    ) -> dict:
        """Kayıt isteğini işle.

        Önce projenin DB'de mevcut olduğunu doğrular; ardından
        ProjectRegistry.register_project'i çağırır.

        Args:
            project_id: Kayıt edilecek proje ID'si.
            bridge_url: Projenin Claude Code Bridge URL'si.
            **kwargs:   ProjectRegistry.register_project'e iletilecek ek parametreler
                        (fastapi_url, concurrent_agents vb.).

        Returns:
            Başarıda: ``{"ok": True, "project_id": project_id}``
            Başarısızlıkta: ``{"ok": False, "error": "<açıklama>"}``
        """
        try:
            await self._registry.register_project(project_id, bridge_url, **kwargs)
        except ValueError as exc:
            logger.warning(
                "ExternalProjectRegistrar.handle_registration: kayıt başarısız — %s", exc
            )
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            logger.error(
                "ExternalProjectRegistrar.handle_registration: beklenmedik hata — %s", exc
            )
            return {"ok": False, "error": "Kayıt sırasında beklenmedik bir hata oluştu."}

        logger.info(
            "ExternalProjectRegistrar: %r başarıyla kaydedildi (bridge_url=%s).",
            project_id, bridge_url,
        )
        return {"ok": True, "project_id": project_id}

    async def handle_unregistration(self, project_id: str) -> dict:
        """Kayıt silme isteğini işle.

        Args:
            project_id: Kaydı kaldırılacak proje ID'si.

        Returns:
            Başarıda: ``{"ok": True, "project_id": project_id}``
            Başarısızlıkta: ``{"ok": False, "error": "<açıklama>"}``
        """
        try:
            await self._registry.unregister_project(project_id)
        except ValueError as exc:
            logger.warning(
                "ExternalProjectRegistrar.handle_unregistration: başarısız — %s", exc
            )
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            logger.error(
                "ExternalProjectRegistrar.handle_unregistration: beklenmedik hata — %s", exc
            )
            return {"ok": False, "error": "Kayıt silme sırasında beklenmedik bir hata oluştu."}

        logger.info(
            "ExternalProjectRegistrar: %r kaydı kaldırıldı.", project_id
        )
        return {"ok": True, "project_id": project_id}
