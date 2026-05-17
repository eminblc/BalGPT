"""Orchestrator core module testleri.

AgentLifecycleManager, OrchestratorSessionManager, ProjectRegistry ve
ExternalProjectRegistrar sınıflarını kapsar.
"""
from __future__ import annotations

import asyncio
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ── AgentLifecycleManager ─────────────────────────────────────────


class TestAgentLifecycleManager:
    """AgentLifecycleManager birim testleri — agent_run_repo mock'lanmış."""

    def _make_manager(self, mock_repo=None):
        """Mock repo inject edilmiş AgentLifecycleManager döndür."""
        from backend.features.orchestrator.core import AgentLifecycleManager
        mgr = AgentLifecycleManager()
        if mock_repo is not None:
            mgr._repo = mock_repo
        return mgr

    def _make_repo(self, run_id="test-run-001"):
        """Standart mock agent_run_repo döndür."""
        repo = MagicMock()
        repo.agent_run_create = AsyncMock(return_value=run_id)
        repo.agent_run_update_status = AsyncMock(return_value=None)
        repo.agent_run_cancel = AsyncMock(return_value=None)
        repo.agent_run_list = AsyncMock(return_value=[])
        repo.agent_run_list_active = AsyncMock(return_value=[])
        return repo

    # test_lifecycle_start_run_returns_run_id

    def test_lifecycle_start_run_returns_run_id(self):
        """start_run → string id döner."""
        repo = self._make_repo(run_id="abc-123")
        mgr = self._make_manager(mock_repo=repo)

        result = asyncio.run(mgr.start_run("scheduler_cron", "main"))

        assert result == "abc-123"
        repo.agent_run_create.assert_awaited_once()

    def test_lifecycle_start_run_passes_agent_type_and_session(self):
        """start_run agent_type ve session_id'yi repo'ya iletir."""
        repo = self._make_repo()
        mgr = self._make_manager(mock_repo=repo)

        asyncio.run(mgr.start_run("manual_bridge", "project_petekv5"))

        call_args = repo.agent_run_create.call_args
        assert call_args.args[0] == "manual_bridge"
        assert call_args.args[1] == "project_petekv5"

    def test_lifecycle_start_run_optional_fields(self):
        """start_run project_id, task_id, prompt, source, sender iletir."""
        repo = self._make_repo()
        mgr = self._make_manager(mock_repo=repo)

        asyncio.run(mgr.start_run(
            "project_task", "sess-1",
            project_id="petekv5",
            task_id="task-99",
            prompt="Deploy et",
            source="whatsapp",
            sender="905001234567",
        ))

        kwargs = repo.agent_run_create.call_args.kwargs
        assert kwargs["project_id"] == "petekv5"
        assert kwargs["task_id"] == "task-99"
        assert kwargs["prompt"] == "Deploy et"
        assert kwargs["source"] == "whatsapp"
        assert kwargs["sender"] == "905001234567"

    # test_lifecycle_mark_running

    def test_lifecycle_mark_running(self):
        """mark_running → agent_run_update_status 'running' ile çağrılır."""
        repo = self._make_repo()
        mgr = self._make_manager(mock_repo=repo)

        asyncio.run(mgr.mark_running("run-001"))

        repo.agent_run_update_status.assert_awaited_once_with("run-001", "running")

    # test_lifecycle_mark_completed

    def test_lifecycle_mark_completed(self):
        """mark_completed → agent_run_update_status 'completed' ile çağrılır."""
        repo = self._make_repo()
        mgr = self._make_manager(mock_repo=repo)

        asyncio.run(mgr.mark_completed("run-002", output="Başarılı"))

        repo.agent_run_update_status.assert_awaited_once_with(
            "run-002", "completed", output="Başarılı"
        )

    def test_lifecycle_mark_completed_without_output(self):
        """mark_completed output=None varsayılan değeri kullanır."""
        repo = self._make_repo()
        mgr = self._make_manager(mock_repo=repo)

        asyncio.run(mgr.mark_completed("run-002"))

        repo.agent_run_update_status.assert_awaited_once_with(
            "run-002", "completed", output=None
        )

    # test_lifecycle_mark_failed_with_error

    def test_lifecycle_mark_failed_with_error(self):
        """mark_failed → error_msg iletilir."""
        repo = self._make_repo()
        mgr = self._make_manager(mock_repo=repo)

        asyncio.run(mgr.mark_failed("run-003", error_msg="Timeout", exit_code=1))

        repo.agent_run_update_status.assert_awaited_once_with(
            "run-003", "failed", error_msg="Timeout", exit_code=1
        )

    def test_lifecycle_mark_failed_exit_code_optional(self):
        """mark_failed exit_code=None varsayılan kullanılabilir."""
        repo = self._make_repo()
        mgr = self._make_manager(mock_repo=repo)

        asyncio.run(mgr.mark_failed("run-004", error_msg="Hata"))

        kwargs = repo.agent_run_update_status.call_args
        assert kwargs.kwargs.get("exit_code") is None

    # test_lifecycle_list_runs_delegates_to_repo

    def test_lifecycle_list_runs_delegates_to_repo(self):
        """list_runs → repo'ya filtreler iletilir."""
        fake_runs = [{"id": "r1"}, {"id": "r2"}]
        repo = self._make_repo()
        repo.agent_run_list = AsyncMock(return_value=fake_runs)
        mgr = self._make_manager(mock_repo=repo)

        result = asyncio.run(mgr.list_runs(project_id="petekv5", status="running", limit=10))

        assert result == fake_runs
        repo.agent_run_list.assert_awaited_once_with(
            project_id="petekv5", status="running", limit=10
        )

    def test_lifecycle_list_active_runs_delegates_to_repo(self):
        """list_active_runs → repo.agent_run_list_active çağrılır."""
        active = [{"id": "r1", "status": "pending"}]
        repo = self._make_repo()
        repo.agent_run_list_active = AsyncMock(return_value=active)
        mgr = self._make_manager(mock_repo=repo)

        result = asyncio.run(mgr.list_active_runs())

        assert result == active
        repo.agent_run_list_active.assert_awaited_once()

    def test_lifecycle_cancel_run_delegates_to_repo(self):
        """cancel_run → repo.agent_run_cancel çağrılır."""
        repo = self._make_repo()
        mgr = self._make_manager(mock_repo=repo)

        asyncio.run(mgr.cancel_run("run-cancel"))

        repo.agent_run_cancel.assert_awaited_once_with("run-cancel")


# ── OrchestratorSessionManager ────────────────────────────────────


class TestOrchestratorSessionManager:
    """OrchestratorSessionManager birim testleri — gerçek dosya sistemi (tmp_path)."""

    @pytest.fixture
    def mgr(self):
        from backend.features.orchestrator.core import OrchestratorSessionManager
        return OrchestratorSessionManager()

    # test_session_manager_get_session_id

    def test_session_manager_get_session_id(self, mgr):
        """project_id='petekv5' → 'project_petekv5' döner."""
        assert mgr.get_session_id("petekv5") == "project_petekv5"

    def test_session_manager_get_session_id_generic(self, mgr):
        """project_id='bengisu' → 'project_bengisu' döner."""
        assert mgr.get_session_id("bengisu") == "project_bengisu"

    # test_session_manager_read_context_missing_file

    def test_session_manager_read_context_missing_file(self, mgr, tmp_path):
        """Context dosyası yoksa boş dict döner."""
        result = mgr.read_context(str(tmp_path))
        assert result == {}

    def test_session_manager_read_context_invalid_json(self, mgr, tmp_path):
        """Bozuk JSON → boş dict döner (exception fırlatmaz)."""
        ctx_dir = tmp_path / ".orchestrator"
        ctx_dir.mkdir()
        ctx_file = ctx_dir / "context.json"
        ctx_file.write_text("not-valid-json{{{", encoding="utf-8")

        result = mgr.read_context(str(tmp_path))
        assert result == {}

    # test_session_manager_write_context_atomic

    def test_session_manager_write_context_atomic(self, mgr, tmp_path):
        """Yazılan veri sonraki okumada aynı döner."""
        data = {"last_task": "deploy", "ts": 1234567890}
        mgr.write_context(str(tmp_path), data)
        result = mgr.read_context(str(tmp_path))
        assert result == data

    def test_session_manager_write_context_creates_dir(self, mgr, tmp_path):
        """.orchestrator dizini yoksa oluşturulur."""
        data = {"x": 1}
        mgr.write_context(str(tmp_path), data)
        ctx_path = tmp_path / ".orchestrator" / "context.json"
        assert ctx_path.exists()

    def test_session_manager_write_context_overwrites(self, mgr, tmp_path):
        """İkinci yazma önceki içeriği overwrite eder."""
        mgr.write_context(str(tmp_path), {"v": 1})
        mgr.write_context(str(tmp_path), {"v": 2, "extra": True})
        result = mgr.read_context(str(tmp_path))
        assert result["v"] == 2
        assert result["extra"] is True

    def test_session_manager_context_path_structure(self, mgr, tmp_path):
        """get_context_path doğru path döndürür."""
        path = mgr.get_context_path(str(tmp_path))
        assert path == tmp_path / ".orchestrator" / "context.json"

    def test_session_manager_read_roundtrip_unicode(self, mgr, tmp_path):
        """Unicode karakterler kayıpsız saklanır."""
        data = {"proje": "Müzik API", "açıklama": "Türkçe metin"}
        mgr.write_context(str(tmp_path), data)
        result = mgr.read_context(str(tmp_path))
        assert result["proje"] == "Müzik API"
        assert result["açıklama"] == "Türkçe metin"


# ── ProjectRegistry ───────────────────────────────────────────────


class TestProjectRegistry:
    """ProjectRegistry birim testleri — store mock'lanmış."""

    def _make_store(self, project=None, projects=None):
        """Standart mock store döndür."""
        store = MagicMock()
        store.project_get = AsyncMock(return_value=project)
        store.project_list = AsyncMock(return_value=projects or [])
        store.project_update_metadata = AsyncMock(return_value=None)
        return store

    def _make_registry(self, store):
        from backend.features.orchestrator.core import ProjectRegistry
        return ProjectRegistry(store)

    # test_registry_list_registered_empty

    def test_registry_list_registered_empty(self):
        """Henüz kayıt yokken boş list döner."""
        store = self._make_store(projects=[])
        reg = self._make_registry(store)

        result = asyncio.run(reg.list_registered())
        assert result == []

    def test_registry_list_registered_filters_disabled(self):
        """orchestrator_enabled=False olan projeler filtrelenir."""
        projects = [
            {"id": "proj-a", "name": "A", "metadata": json.dumps({"orchestrator_enabled": True, "bridge_url": "http://a"})},
            {"id": "proj-b", "name": "B", "metadata": json.dumps({"orchestrator_enabled": False})},
            {"id": "proj-c", "name": "C", "metadata": "{}"},
        ]
        store = self._make_store(projects=projects)
        reg = self._make_registry(store)

        result = asyncio.run(reg.list_registered())

        assert len(result) == 1
        assert result[0]["id"] == "proj-a"

    def test_registry_list_registered_metadata_parsed(self):
        """Dönen kayıtlarda metadata str değil dict olmalı."""
        projects = [
            {"id": "proj-x", "name": "X", "metadata": json.dumps({
                "orchestrator_enabled": True,
                "bridge_url": "http://x:8013",
                "concurrent_agents": 5,
            })},
        ]
        store = self._make_store(projects=projects)
        reg = self._make_registry(store)

        result = asyncio.run(reg.list_registered())

        assert isinstance(result[0]["metadata"], dict)
        assert result[0]["metadata"]["concurrent_agents"] == 5

    def test_registry_register_project_calls_update_metadata(self):
        """register_project → store.project_update_metadata çağrılır."""
        project = {"id": "petekv5", "name": "PetekV5", "metadata": "{}"}
        store = self._make_store(project=project)
        reg = self._make_registry(store)

        asyncio.run(reg.register_project(
            "petekv5",
            bridge_url="http://localhost:8015",
            concurrent_agents=3,
        ))

        store.project_update_metadata.assert_awaited_once()
        call_args = store.project_update_metadata.call_args
        assert call_args.args[0] == "petekv5"
        meta = json.loads(call_args.args[1])
        assert meta["orchestrator_enabled"] is True
        assert meta["bridge_url"] == "http://localhost:8015"
        assert meta["concurrent_agents"] == 3

    def test_registry_register_project_not_found_raises(self):
        """Olmayan proje için register_project ValueError fırlatır."""
        store = self._make_store(project=None)
        reg = self._make_registry(store)

        with pytest.raises(ValueError, match="bulunamadı"):
            asyncio.run(reg.register_project("ghost-project", bridge_url="http://x"))

    def test_registry_register_project_preserves_existing_metadata(self):
        """Mevcut metadata alanları korunur; orchestrator alanları eklenir."""
        existing_meta = {"custom_key": "custom_value", "version": 2}
        project = {"id": "proj-y", "name": "Y", "metadata": json.dumps(existing_meta)}
        store = self._make_store(project=project)
        reg = self._make_registry(store)

        asyncio.run(reg.register_project("proj-y", bridge_url="http://y"))

        call_args = store.project_update_metadata.call_args
        meta = json.loads(call_args.args[1])
        assert meta["custom_key"] == "custom_value"
        assert meta["version"] == 2
        assert meta["orchestrator_enabled"] is True

    def test_registry_unregister_project_sets_disabled(self):
        """unregister_project → orchestrator_enabled=False set edilir."""
        existing_meta = {"orchestrator_enabled": True, "bridge_url": "http://z"}
        project = {"id": "proj-z", "name": "Z", "metadata": json.dumps(existing_meta)}
        store = self._make_store(project=project)
        reg = self._make_registry(store)

        asyncio.run(reg.unregister_project("proj-z"))

        call_args = store.project_update_metadata.call_args
        meta = json.loads(call_args.args[1])
        assert meta["orchestrator_enabled"] is False

    def test_registry_unregister_project_not_found_raises(self):
        """Olmayan proje için unregister_project ValueError fırlatır."""
        store = self._make_store(project=None)
        reg = self._make_registry(store)

        with pytest.raises(ValueError, match="bulunamadı"):
            asyncio.run(reg.unregister_project("ghost"))

    def test_registry_register_project_invalid_metadata_json(self):
        """Bozuk metadata JSON'u sıfırlanır, kayıt yine de tamamlanır."""
        project = {"id": "proj-corrupt", "name": "Corrupt", "metadata": "NOT-JSON"}
        store = self._make_store(project=project)
        reg = self._make_registry(store)

        # ValueError fırlatmamalı
        asyncio.run(reg.register_project("proj-corrupt", bridge_url="http://c"))

        store.project_update_metadata.assert_awaited_once()
        meta_str = store.project_update_metadata.call_args.args[1]
        meta = json.loads(meta_str)
        assert meta["orchestrator_enabled"] is True


# ── ExternalProjectRegistrar ──────────────────────────────────────


class TestExternalProjectRegistrar:
    """ExternalProjectRegistrar birim testleri — ProjectRegistry mock'lanmış."""

    def _make_registrar(self, *, register_raises=None, unregister_raises=None):
        from backend.features.orchestrator.registry import ExternalProjectRegistrar
        from backend.features.orchestrator.core import ProjectRegistry

        mock_reg = MagicMock(spec=ProjectRegistry)
        if register_raises is not None:
            mock_reg.register_project = AsyncMock(side_effect=register_raises)
        else:
            mock_reg.register_project = AsyncMock(return_value=None)

        if unregister_raises is not None:
            mock_reg.unregister_project = AsyncMock(side_effect=unregister_raises)
        else:
            mock_reg.unregister_project = AsyncMock(return_value=None)

        return ExternalProjectRegistrar(project_registry=mock_reg)

    def test_handle_registration_success(self):
        """Başarılı kayıt → ok=True, project_id döner."""
        reg = self._make_registrar()

        result = asyncio.run(reg.handle_registration("petekv5", "http://localhost:8015"))

        assert result["ok"] is True
        assert result["project_id"] == "petekv5"

    def test_handle_registration_not_found(self):
        """Olmayan proje → ok=False, error dolu."""
        reg = self._make_registrar(register_raises=ValueError("Proje bulunamadı: 'ghost'"))

        result = asyncio.run(reg.handle_registration("ghost", "http://x"))

        assert result["ok"] is False
        assert "bulunamadı" in result["error"].lower() or "ghost" in result["error"]

    def test_handle_registration_unexpected_error(self):
        """Beklenmedik istisna → ok=False, generic hata mesajı."""
        reg = self._make_registrar(register_raises=RuntimeError("DB bağlantı hatası"))

        result = asyncio.run(reg.handle_registration("proj-x", "http://x"))

        assert result["ok"] is False
        assert "beklenmedik" in result["error"].lower() or "error" in result["error"].lower()

    def test_handle_unregistration_success(self):
        """Başarılı kayıt silme → ok=True, project_id döner."""
        reg = self._make_registrar()

        result = asyncio.run(reg.handle_unregistration("petekv5"))

        assert result["ok"] is True
        assert result["project_id"] == "petekv5"

    def test_handle_unregistration_not_found(self):
        """Olmayan proje → ok=False."""
        reg = self._make_registrar(unregister_raises=ValueError("Proje bulunamadı: 'ghost'"))

        result = asyncio.run(reg.handle_unregistration("ghost"))

        assert result["ok"] is False

    def test_handle_unregistration_unexpected_error(self):
        """Beklenmedik istisna → ok=False."""
        reg = self._make_registrar(unregister_raises=RuntimeError("DB hatası"))

        result = asyncio.run(reg.handle_unregistration("proj-y"))

        assert result["ok"] is False
