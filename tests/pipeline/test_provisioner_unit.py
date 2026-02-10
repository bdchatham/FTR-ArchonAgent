"""Unit tests for workspace provisioner.

Tests workspace directory creation, Git clone operations, permission
setting, and workspace cleanup for the WorkspaceProvisioner.

**Validates: Requirements 4.1, 4.2, 4.7, 4.8**
"""
import asyncio
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from src.pipeline.classifier.models import IssueClassification, IssueType
from src.pipeline.provisioner.workspace import (
    GitCloneError, ProvisionedWorkspace, WorkspaceConfig,
    WorkspaceProvisionError, WorkspaceProvisioner, WORKSPACE_DIR_PERMISSIONS,
)


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def workspace_base(tmp_path):
    base = tmp_path / "workspaces"
    base.mkdir()
    return base


@pytest.fixture
def workspace_config(workspace_base):
    return WorkspaceConfig(base_path=workspace_base, retention_days=7)


@pytest.fixture
def provisioner(workspace_config):
    return WorkspaceProvisioner(config=workspace_config)


@pytest.fixture
def sample_classification():
    return IssueClassification(
        issue_type=IssueType.FEATURE, requirements=["Add auth"],
        affected_packages=["auth-service"], completeness_score=4,
        clarification_questions=[],
    )


@pytest.fixture
def sample_issue_details():
    return {"repository": "ArchonAgent", "owner": "testorg",
            "title": "Add auth", "body": "Implement OAuth2", "labels": ["feature"]}


class TestWorkspaceDirectoryCreation:

    def test_build_workspace_path_creates_safe_name(self, provisioner):
        path = provisioner._build_workspace_path("owner/repo#42")
        assert "owner_repo_42" in path.name
        assert path.parent == provisioner.config.base_path

    def test_build_workspace_path_includes_timestamp(self, provisioner):
        path = provisioner._build_workspace_path("owner/repo#1")
        parts = path.name.split("_")
        assert parts[-1].isdigit()

    def test_create_workspace_directory_succeeds(self, provisioner, workspace_base):
        target = workspace_base / "test_workspace"
        provisioner._create_workspace_directory(target)
        assert target.exists() and target.is_dir()

    def test_create_workspace_directory_creates_parents(self, provisioner, workspace_base):
        target = workspace_base / "nested" / "deep" / "workspace"
        provisioner._create_workspace_directory(target)
        assert target.exists()

    def test_create_workspace_directory_raises_on_failure(self, provisioner):
        invalid_path = Path("/nonexistent/root/that/cannot/exist/workspace")
        with pytest.raises(WorkspaceProvisionError, match="Failed to create"):
            provisioner._create_workspace_directory(invalid_path)


class TestWorkspacePermissions:

    def test_set_directory_permissions(self, provisioner, workspace_base):
        target = workspace_base / "perm_test"
        target.mkdir()
        provisioner._set_directory_permissions(target)
        actual_mode = target.stat().st_mode & 0o777
        assert actual_mode == WORKSPACE_DIR_PERMISSIONS


class TestPackageUrlResolution:

    def test_resolve_primary_repository(self, provisioner):
        urls = provisioner._resolve_package_urls(
            [], {"repository": "MyRepo", "owner": "myorg"})
        assert urls["MyRepo"] == "https://github.com/myorg/MyRepo.git"

    def test_resolve_affected_packages(self, provisioner):
        urls = provisioner._resolve_package_urls(
            ["extra-lib"], {"repository": "MainRepo", "owner": "org"})
        assert "MainRepo" in urls and "extra-lib" in urls
        assert urls["extra-lib"] == "https://github.com/org/extra-lib.git"

    def test_resolve_deduplicates_primary_and_affected(self, provisioner):
        urls = provisioner._resolve_package_urls(
            ["MainRepo"], {"repository": "MainRepo", "owner": "org"})
        assert len(urls) == 1

    def test_resolve_empty_issue_details(self, provisioner):
        urls = provisioner._resolve_package_urls([], {})
        assert len(urls) == 0

    def test_resolve_affected_without_owner(self, provisioner):
        urls = provisioner._resolve_package_urls(
            ["some-pkg"], {"repository": "", "owner": ""})
        assert len(urls) == 0


class TestGitClone:

    def test_clone_single_package_success(self, provisioner, workspace_base):
        workspace = workspace_base / "clone_test"
        workspace.mkdir()
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            run_async(provisioner._clone_single_package(
                workspace, "test-pkg", "https://github.com/org/test-pkg.git"))

    def test_clone_single_package_failure_raises(self, provisioner, workspace_base):
        workspace = workspace_base / "clone_fail"
        workspace.mkdir()
        mock_process = AsyncMock()
        mock_process.returncode = 128
        mock_process.communicate = AsyncMock(
            return_value=(b"", b"fatal: repository not found"))
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with pytest.raises(GitCloneError, match="repository not found"):
                run_async(provisioner._clone_single_package(
                    workspace, "bad-pkg", "https://github.com/org/bad-pkg.git"))

    def test_clone_timeout_raises(self, provisioner, workspace_base):
        workspace = workspace_base / "clone_timeout"
        workspace.mkdir()
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with pytest.raises(GitCloneError, match="timed out"):
                run_async(provisioner._clone_single_package(
                    workspace, "slow-pkg", "https://github.com/org/slow-pkg.git"))

    def test_clone_os_error_raises(self, provisioner, workspace_base):
        workspace = workspace_base / "clone_oserr"
        workspace.mkdir()
        with patch("asyncio.create_subprocess_exec", side_effect=OSError("git not found")):
            with pytest.raises(GitCloneError, match="Failed to execute git"):
                run_async(provisioner._clone_single_package(
                    workspace, "pkg", "https://github.com/org/pkg.git"))


class TestProvisionFlow:

    def test_provision_creates_workspace_and_clones(
        self, provisioner, sample_classification, sample_issue_details
    ):
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate = AsyncMock(return_value=(b"", b""))
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = run_async(provisioner.provision(
                issue_id="testorg/ArchonAgent#42",
                classification=sample_classification,
                issue_details=sample_issue_details))
        assert isinstance(result, ProvisionedWorkspace)
        assert result.path.exists()
        assert "ArchonAgent" in result.packages
        assert "auth-service" in result.packages
        assert result.context_file == result.path / "context.md"
        assert result.task_file == result.path / "task.md"

    def test_provision_with_no_packages(self, provisioner):
        classification = IssueClassification(
            issue_type=IssueType.DOCUMENTATION, requirements=[],
            affected_packages=[], completeness_score=3, clarification_questions=[])
        result = run_async(provisioner.provision(
            issue_id="org/repo#1", classification=classification, issue_details={}))
        assert result.path.exists()
        assert result.packages == []


class TestWorkspaceCleanup:

    def test_cleanup_removes_expired_workspaces(self, workspace_base):
        config = WorkspaceConfig(base_path=workspace_base, retention_days=1)
        prov = WorkspaceProvisioner(config=config)
        old_ws = workspace_base / "old_workspace"
        old_ws.mkdir()
        old_mtime = time.time() - (2 * 86400)
        os.utime(old_ws, (old_mtime, old_mtime))
        removed = run_async(prov.cleanup_old_workspaces())
        assert removed == 1
        assert not old_ws.exists()

    def test_cleanup_preserves_recent_workspaces(self, workspace_base):
        config = WorkspaceConfig(base_path=workspace_base, retention_days=7)
        prov = WorkspaceProvisioner(config=config)
        recent_ws = workspace_base / "recent_workspace"
        recent_ws.mkdir()
        removed = run_async(prov.cleanup_old_workspaces())
        assert removed == 0
        assert recent_ws.exists()

    def test_cleanup_mixed_workspaces(self, workspace_base):
        config = WorkspaceConfig(base_path=workspace_base, retention_days=3)
        prov = WorkspaceProvisioner(config=config)
        old_ws = workspace_base / "expired"
        old_ws.mkdir()
        old_mtime = time.time() - (5 * 86400)
        os.utime(old_ws, (old_mtime, old_mtime))
        recent_ws = workspace_base / "active"
        recent_ws.mkdir()
        removed = run_async(prov.cleanup_old_workspaces())
        assert removed == 1
        assert not old_ws.exists()
        assert recent_ws.exists()

    def test_cleanup_nonexistent_base_path(self, tmp_path):
        config = WorkspaceConfig(base_path=tmp_path / "nonexistent", retention_days=7)
        prov = WorkspaceProvisioner(config=config)
        removed = run_async(prov.cleanup_old_workspaces())
        assert removed == 0

    def test_cleanup_empty_base_path(self, workspace_base):
        config = WorkspaceConfig(base_path=workspace_base, retention_days=7)
        prov = WorkspaceProvisioner(config=config)
        removed = run_async(prov.cleanup_old_workspaces())
        assert removed == 0

    def test_cleanup_ignores_files(self, workspace_base):
        config = WorkspaceConfig(base_path=workspace_base, retention_days=1)
        prov = WorkspaceProvisioner(config=config)
        stale_file = workspace_base / "stale.txt"
        stale_file.write_text("old data")
        old_mtime = time.time() - (5 * 86400)
        os.utime(stale_file, (old_mtime, old_mtime))
        removed = run_async(prov.cleanup_old_workspaces())
        assert removed == 0
        assert stale_file.exists()
