"""Workspace provisioning for agent pipeline execution.

Creates filesystem workspaces with cloned Git repositories for Kiro CLI
to use during autonomous implementation. Handles workspace lifecycle
including creation, package cloning, and retention-based cleanup.

Requirements:
- 4.1: Create filesystem folder at configurable base path
- 4.2: Clone required packages from Git into workspace
- 4.7: Set appropriate file permissions for workspace
- 4.8: Clean up workspaces older than configurable retention period
"""

import asyncio
import logging
import shutil
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.pipeline.classifier.models import IssueClassification

logger = logging.getLogger(__name__)

WORKSPACE_DIR_PERMISSIONS = 0o755
WORKSPACE_CLONE_TIMEOUT_SECONDS = 300


@dataclass
class WorkspaceConfig:
    """Configuration for workspace provisioning.

    Attributes:
        base_path: Root directory where workspaces are created.
        retention_days: Days to retain workspaces before cleanup eligibility.
    """

    base_path: Path
    retention_days: int = 7


@dataclass
class ProvisionedWorkspace:
    """Result of a successful workspace provisioning.

    Attributes:
        path: Absolute path to the provisioned workspace directory.
        packages: List of package names cloned into the workspace.
        context_file: Path to the generated context.md file.
        task_file: Path to the generated task.md file.
    """

    path: Path
    packages: list[str] = field(default_factory=list)
    context_file: Path = field(default_factory=lambda: Path())
    task_file: Path = field(default_factory=lambda: Path())


class WorkspaceProvisionError(Exception):
    """Raised when workspace provisioning fails."""

    pass


class GitCloneError(WorkspaceProvisionError):
    """Raised when a Git clone operation fails."""

    def __init__(self, package_url: str, message: str):
        self.package_url = package_url
        super().__init__(f"Failed to clone {package_url}: {message}")


class WorkspaceProvisioner:
    """Creates and manages workspaces for Kiro CLI execution.

    Each workspace is a directory containing cloned Git repositories
    and context files needed for autonomous implementation. Workspaces
    are identified by issue ID and created under the configured base path.

    Attributes:
        config: Workspace configuration (base path, retention).
    """

    def __init__(self, config: WorkspaceConfig):
        self.config = config

    async def provision(
        self,
        issue_id: str,
        classification: IssueClassification,
        issue_details: dict,
    ) -> ProvisionedWorkspace:
        """Provision a workspace for the given issue.

        Creates a workspace directory, clones required packages, and
        returns the workspace metadata. Context and task file generation
        is handled separately by the context module.

        Args:
            issue_id: Canonical issue identifier (e.g., "owner/repo#123").
            classification: LLM classification result with affected packages.
            issue_details: Raw issue data (title, body, labels, etc.).

        Returns:
            ProvisionedWorkspace with path and cloned package list.

        Raises:
            WorkspaceProvisionError: If workspace creation fails.
            GitCloneError: If any package clone fails.
        """
        workspace_path = self._build_workspace_path(issue_id)
        self._create_workspace_directory(workspace_path)
        self._set_directory_permissions(workspace_path)

        cloned_packages = await self._clone_required_packages(
            workspace_path,
            classification.affected_packages,
            issue_details,
        )

        context_file = workspace_path / "context.md"
        task_file = workspace_path / "task.md"

        return ProvisionedWorkspace(
            path=workspace_path,
            packages=cloned_packages,
            context_file=context_file,
            task_file=task_file,
        )

    async def cleanup_old_workspaces(self) -> int:
        """Remove workspaces older than the configured retention period.

        Scans the base path for workspace directories and removes any
        whose modification time exceeds the retention threshold.

        Returns:
            Number of workspaces removed.
        """
        if not self.config.base_path.exists():
            return 0

        retention_threshold = self._calculate_retention_threshold()
        removed_count = 0

        for workspace_dir in self._list_workspace_directories():
            if self._is_expired(workspace_dir, retention_threshold):
                self._remove_workspace(workspace_dir)
                removed_count += 1

        logger.info(
            "Workspace cleanup complete",
            extra={"removed_count": removed_count},
        )
        return removed_count

    def _build_workspace_path(self, issue_id: str) -> Path:
        """Build the filesystem path for a workspace from an issue ID.

        Converts the issue ID format "owner/repo#123" into a safe
        directory name under the base path.

        Args:
            issue_id: Canonical issue identifier.

        Returns:
            Absolute path for the workspace directory.
        """
        safe_name = issue_id.replace("/", "_").replace("#", "_")
        timestamp_suffix = str(int(time.time()))
        directory_name = f"{safe_name}_{timestamp_suffix}"
        return self.config.base_path / directory_name

    def _create_workspace_directory(self, workspace_path: Path) -> None:
        """Create the workspace directory and any missing parents.

        Args:
            workspace_path: Path to create.

        Raises:
            WorkspaceProvisionError: If directory creation fails.
        """
        try:
            workspace_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkspaceProvisionError(
                f"Failed to create workspace at {workspace_path}: {exc}"
            ) from exc

    def _set_directory_permissions(self, workspace_path: Path) -> None:
        """Set appropriate permissions on the workspace directory.

        Args:
            workspace_path: Path to set permissions on.

        Raises:
            WorkspaceProvisionError: If permission setting fails.
        """
        try:
            workspace_path.chmod(WORKSPACE_DIR_PERMISSIONS)
        except OSError as exc:
            raise WorkspaceProvisionError(
                f"Failed to set permissions on {workspace_path}: {exc}"
            ) from exc

    async def _clone_required_packages(
        self,
        workspace_path: Path,
        affected_packages: list[str],
        issue_details: dict,
    ) -> list[str]:
        """Clone all required packages into the workspace.

        Determines which packages to clone from the classification and
        issue details, then clones each one.

        Args:
            workspace_path: Workspace directory to clone into.
            affected_packages: Package names from classification.
            issue_details: Raw issue data with repository info.

        Returns:
            List of successfully cloned package names.

        Raises:
            GitCloneError: If any clone operation fails.
        """
        package_urls = self._resolve_package_urls(
            affected_packages, issue_details
        )

        cloned_packages: list[str] = []
        for package_name, clone_url in package_urls.items():
            await self._clone_single_package(
                workspace_path, package_name, clone_url
            )
            cloned_packages.append(package_name)

        return cloned_packages

    def _resolve_package_urls(
        self,
        affected_packages: list[str],
        issue_details: dict,
    ) -> dict[str, str]:
        """Resolve package names to Git clone URLs.

        Uses the issue's repository as the primary package and includes
        any additional affected packages. Package URLs are constructed
        from the repository owner and name.

        Args:
            affected_packages: Package names from classification.
            issue_details: Raw issue data with repository/owner fields.

        Returns:
            Mapping of package name to clone URL.
        """
        package_urls: dict[str, str] = {}

        repository = issue_details.get("repository", "")
        owner = issue_details.get("owner", "")
        if repository and owner:
            primary_url = f"https://github.com/{owner}/{repository}.git"
            package_urls[repository] = primary_url

        for package_name in affected_packages:
            if package_name not in package_urls and owner:
                url = f"https://github.com/{owner}/{package_name}.git"
                package_urls[package_name] = url

        return package_urls

    async def _clone_single_package(
        self,
        workspace_path: Path,
        package_name: str,
        clone_url: str,
    ) -> None:
        """Clone a single Git repository into the workspace.

        Uses asyncio subprocess to run git clone without blocking
        the event loop.

        Args:
            workspace_path: Parent directory for the clone.
            package_name: Name for the cloned directory.
            clone_url: Git URL to clone from.

        Raises:
            GitCloneError: If the clone operation fails or times out.
        """
        target_path = workspace_path / package_name

        try:
            process = await asyncio.create_subprocess_exec(
                "git",
                "clone",
                "--depth",
                "1",
                clone_url,
                str(target_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=WORKSPACE_CLONE_TIMEOUT_SECONDS,
            )

            if process.returncode != 0:
                error_output = stderr.decode().strip()
                raise GitCloneError(clone_url, error_output)

            logger.info(
                "Cloned package",
                extra={
                    "package": package_name,
                    "target": str(target_path),
                },
            )

        except asyncio.TimeoutError as exc:
            raise GitCloneError(
                clone_url,
                f"Clone timed out after {WORKSPACE_CLONE_TIMEOUT_SECONDS}s",
            ) from exc
        except OSError as exc:
            raise GitCloneError(
                clone_url, f"Failed to execute git: {exc}"
            ) from exc

    def _calculate_retention_threshold(self) -> float:
        """Calculate the timestamp threshold for workspace expiration.

        Returns:
            Unix timestamp; workspaces modified before this are expired.
        """
        retention_seconds = self.config.retention_days * 86400
        return time.time() - retention_seconds

    def _list_workspace_directories(self) -> list[Path]:
        """List all workspace directories under the base path.

        Returns:
            List of directory paths (excludes files).
        """
        return [
            entry
            for entry in self.config.base_path.iterdir()
            if entry.is_dir()
        ]

    def _is_expired(
        self, workspace_dir: Path, retention_threshold: float
    ) -> bool:
        """Check if a workspace directory has exceeded its retention period.

        Args:
            workspace_dir: Path to the workspace directory.
            retention_threshold: Unix timestamp threshold.

        Returns:
            True if the workspace is older than the threshold.
        """
        modification_time = workspace_dir.stat().st_mtime
        return modification_time < retention_threshold

    def _remove_workspace(self, workspace_dir: Path) -> None:
        """Remove a workspace directory and all its contents.

        Args:
            workspace_dir: Path to remove.
        """
        try:
            shutil.rmtree(workspace_dir)
            logger.info(
                "Removed expired workspace",
                extra={"workspace": str(workspace_dir)},
            )
        except OSError:
            logger.exception(
                "Failed to remove workspace",
                extra={"workspace": str(workspace_dir)},
            )
