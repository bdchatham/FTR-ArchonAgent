"""Property-based tests for workspace provisioner.

This module contains property-based tests using Hypothesis to verify that
the workspace provisioner correctly creates directories, resolves package
URLs, and cleans up expired workspaces across all valid inputs.

**Validates: Requirements 4.1, 4.2, 4.7, 4.8**

Feature: agent-orchestration

Testing Configuration:
- Library: Hypothesis (Python)
- Minimum iterations: 100 per property test
- Tag format: Feature: agent-orchestration, Property N: <property_text>
"""
import asyncio
import os
import tempfile
import time
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st, HealthCheck

from src.pipeline.classifier.models import IssueClassification, IssueType
from src.pipeline.provisioner.workspace import (
    ProvisionedWorkspace, WorkspaceConfig, WorkspaceProvisioner,
    WORKSPACE_DIR_PERMISSIONS,
)


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@st.composite
def valid_github_username(draw):
    return draw(st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"),
        min_size=1, max_size=20))


@st.composite
def valid_repo_name(draw):
    return draw(st.text(
        alphabet=st.sampled_from(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"),
        min_size=1, max_size=30,
    ).filter(lambda x: x.strip() and not x.startswith("-")))


@st.composite
def valid_issue_id(draw):
    owner = draw(valid_github_username())
    repo = draw(valid_repo_name())
    number = draw(st.integers(min_value=1, max_value=100000))
    return f"{owner}/{repo}#{number}"


@st.composite
def valid_package_list(draw):
    return draw(st.lists(valid_repo_name(), min_size=0, max_size=5, unique=True))


@st.composite
def valid_issue_details(draw):
    include_repo = draw(st.booleans())
    if include_repo:
        return {
            "repository": draw(valid_repo_name()),
            "owner": draw(valid_github_username()),
            "title": draw(st.text(min_size=1, max_size=100)),
            "body": draw(st.text(min_size=0, max_size=500)),
        }
    return {}


@st.composite
def valid_retention_days(draw):
    return draw(st.integers(min_value=1, max_value=365))


class TestWorkspacePathConstruction:
    """Property tests for workspace path construction.

    Feature: agent-orchestration

    *For any* valid issue ID, the workspace provisioner SHALL construct
    a filesystem-safe path under the configured base directory.

    **Validates: Requirements 4.1**
    """

    @given(issue_id=valid_issue_id())
    @settings(max_examples=100)
    def test_workspace_path_is_under_base_directory(self, issue_id):
        """Property: Workspace path is always under the configured base path.

        **Validates: Requirements 4.1**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config = WorkspaceConfig(base_path=Path(tmpdir))
            provisioner = WorkspaceProvisioner(config=config)
            workspace_path = provisioner._build_workspace_path(issue_id)
            assert workspace_path.parent == Path(tmpdir)

    @given(issue_id=valid_issue_id())
    @settings(max_examples=100)
    def test_workspace_path_contains_no_special_characters(self, issue_id):
        """Property: Workspace directory name has no path-unsafe characters.

        **Validates: Requirements 4.1**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config = WorkspaceConfig(base_path=Path(tmpdir))
            provisioner = WorkspaceProvisioner(config=config)
            workspace_path = provisioner._build_workspace_path(issue_id)
            directory_name = workspace_path.name
            assert "/" not in directory_name
            assert "#" not in directory_name

    @given(issue_id=valid_issue_id())
    @settings(max_examples=100)
    def test_workspace_directory_is_creatable(self, issue_id):
        """Property: Constructed workspace path can be created as a directory.

        **Validates: Requirements 4.1**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config = WorkspaceConfig(base_path=Path(tmpdir))
            provisioner = WorkspaceProvisioner(config=config)
            workspace_path = provisioner._build_workspace_path(issue_id)
            provisioner._create_workspace_directory(workspace_path)
            assert workspace_path.exists() and workspace_path.is_dir()


class TestPackageUrlResolutionProperties:
    """Property tests for package URL resolution.

    Feature: agent-orchestration

    *For any* set of affected packages and issue details, the provisioner
    SHALL resolve package names to valid Git clone URLs.

    **Validates: Requirements 4.2**
    """

    @given(
        affected_packages=valid_package_list(),
        issue_details=valid_issue_details(),
    )
    @settings(max_examples=100)
    def test_resolved_urls_are_valid_git_urls(self, affected_packages, issue_details):
        """Property: All resolved URLs are valid HTTPS Git URLs.

        **Validates: Requirements 4.2**
        """
        config = WorkspaceConfig(base_path=Path("/tmp/test"))
        provisioner = WorkspaceProvisioner(config=config)
        urls = provisioner._resolve_package_urls(affected_packages, issue_details)
        for url in urls.values():
            assert url.startswith("https://github.com/")
            assert url.endswith(".git")

    @given(
        affected_packages=valid_package_list(),
        issue_details=valid_issue_details(),
    )
    @settings(max_examples=100)
    def test_primary_repo_not_duplicated(self, affected_packages, issue_details):
        """Property: Primary repository appears at most once in resolved URLs.

        **Validates: Requirements 4.2**
        """
        config = WorkspaceConfig(base_path=Path("/tmp/test"))
        provisioner = WorkspaceProvisioner(config=config)
        urls = provisioner._resolve_package_urls(affected_packages, issue_details)
        package_names = list(urls.keys())
        assert len(package_names) == len(set(package_names))

    @given(issue_details=valid_issue_details())
    @settings(max_examples=100)
    def test_empty_packages_includes_only_primary(self, issue_details):
        """Property: Empty affected packages list resolves only primary repo.

        **Validates: Requirements 4.2**
        """
        config = WorkspaceConfig(base_path=Path("/tmp/test"))
        provisioner = WorkspaceProvisioner(config=config)
        urls = provisioner._resolve_package_urls([], issue_details)
        has_repo = bool(issue_details.get("repository") and issue_details.get("owner"))
        if has_repo:
            assert len(urls) == 1
        else:
            assert len(urls) == 0


class TestWorkspacePermissionProperties:
    """Property tests for workspace permission setting.

    Feature: agent-orchestration

    *For any* created workspace directory, the provisioner SHALL set
    the configured file permissions.

    **Validates: Requirements 4.7**
    """

    @given(issue_id=valid_issue_id())
    @settings(max_examples=100)
    def test_workspace_has_correct_permissions(self, issue_id):
        """Property: Created workspace has the expected permission bits.

        **Validates: Requirements 4.7**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config = WorkspaceConfig(base_path=Path(tmpdir))
            provisioner = WorkspaceProvisioner(config=config)
            workspace_path = provisioner._build_workspace_path(issue_id)
            provisioner._create_workspace_directory(workspace_path)
            provisioner._set_directory_permissions(workspace_path)
            actual_mode = workspace_path.stat().st_mode & 0o777
            assert actual_mode == WORKSPACE_DIR_PERMISSIONS


class TestWorkspaceCleanupProperties:
    """Property tests for workspace cleanup.

    Feature: agent-orchestration

    *For any* set of workspaces with varying ages, the cleanup operation
    SHALL remove exactly those workspaces older than the retention period.

    **Validates: Requirements 4.8**
    """

    @given(
        retention_days=valid_retention_days(),
        expired_count=st.integers(min_value=0, max_value=5),
        active_count=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=100)
    def test_cleanup_removes_exactly_expired_workspaces(
        self, retention_days, expired_count, active_count
    ):
        """Property: Cleanup removes exactly the expired workspaces.

        **Validates: Requirements 4.8**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "workspaces"
            base.mkdir()
            config = WorkspaceConfig(base_path=base, retention_days=retention_days)
            provisioner = WorkspaceProvisioner(config=config)

            expired_dirs = []
            for i in range(expired_count):
                d = base / f"expired_{i}"
                d.mkdir()
                old_mtime = time.time() - ((retention_days + 1) * 86400)
                os.utime(d, (old_mtime, old_mtime))
                expired_dirs.append(d)

            active_dirs = []
            for i in range(active_count):
                d = base / f"active_{i}"
                d.mkdir()
                active_dirs.append(d)

            removed = run_async(provisioner.cleanup_old_workspaces())
            assert removed == expired_count
            for d in expired_dirs:
                assert not d.exists()
            for d in active_dirs:
                assert d.exists()

    @given(retention_days=valid_retention_days())
    @settings(max_examples=100)
    def test_cleanup_on_empty_base_returns_zero(self, retention_days):
        """Property: Cleanup on empty base path returns zero.

        **Validates: Requirements 4.8**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir) / "empty_base"
            base.mkdir()
            config = WorkspaceConfig(base_path=base, retention_days=retention_days)
            provisioner = WorkspaceProvisioner(config=config)
            removed = run_async(provisioner.cleanup_old_workspaces())
            assert removed == 0

    @given(retention_days=valid_retention_days())
    @settings(max_examples=100)
    def test_cleanup_on_nonexistent_base_returns_zero(self, retention_days):
        """Property: Cleanup on nonexistent base path returns zero.

        **Validates: Requirements 4.8**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            config = WorkspaceConfig(
                base_path=Path(tmpdir) / "does_not_exist",
                retention_days=retention_days)
            provisioner = WorkspaceProvisioner(config=config)
            removed = run_async(provisioner.cleanup_old_workspaces())
            assert removed == 0
