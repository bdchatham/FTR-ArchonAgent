"""Kiro CLI subprocess management.

Executes the Kiro CLI as an async subprocess with timeout enforcement,
output streaming, and structured result capture. Designed for use in
the agent pipeline's implementation stage.

Requirements:
- 5.1: Invoke kiro-cli as subprocess with workspace path
- 5.2: Pass task summary via task file
- 5.3: Capture stdout and stderr from kiro-cli execution
- 5.4: Enforce configurable timeout for kiro-cli execution
- 5.5: Exit code 0 → proceed to PR creation (success)
- 5.6: Non-zero exit → log error and transition to failed state (failure)
- 5.7: Stream kiro-cli output to logs for observability
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class KiroResult:
    """Result of a Kiro CLI execution.

    Attributes:
        success: True when kiro-cli exited with code 0.
        exit_code: Process exit code (-1 for timeout/OS errors).
        stdout: Captured standard output.
        stderr: Captured standard error.
        duration_seconds: Wall-clock execution time.
    """

    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float


class KiroRunner:
    """Manages Kiro CLI subprocess execution.

    Launches kiro-cli as an async subprocess, streams output line-by-line
    to both Python logging and an optional callback, enforces a timeout,
    and returns a structured result.

    Attributes:
        kiro_path: Filesystem path to the kiro-cli executable.
        timeout_seconds: Maximum execution time before the process is killed.
    """

    def __init__(self, kiro_path: str, timeout_seconds: int = 3600):
        self.kiro_path = kiro_path
        self.timeout_seconds = timeout_seconds

    async def run(
        self,
        workspace_path: Path,
        task_file: Path,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> KiroResult:
        """Execute Kiro CLI against a workspace.

        Starts kiro-cli with the workspace path and task file as arguments,
        streams output in real time, and enforces the configured timeout.

        Args:
            workspace_path: Directory containing the provisioned workspace.
            task_file: Path to the task.md file describing the work.
            log_callback: Optional function called with each output line.

        Returns:
            KiroResult with exit code, captured output, and duration.
        """
        start_time = time.monotonic()

        try:
            process = await self._start_process(workspace_path, task_file)
            stdout, stderr = await self._collect_output_with_timeout(
                process, log_callback
            )
            exit_code = process.returncode or 0
        except asyncio.TimeoutError:
            return self._handle_timeout(process, start_time)
        except OSError as exc:
            return self._handle_os_error(exc, start_time)

        duration = time.monotonic() - start_time
        return self._build_result(exit_code, stdout, stderr, duration)

    async def _start_process(
        self, workspace_path: Path, task_file: Path
    ) -> asyncio.subprocess.Process:
        """Launch the kiro-cli subprocess.

        Args:
            workspace_path: Workspace directory argument.
            task_file: Task file argument.

        Returns:
            The started subprocess.

        Raises:
            OSError: If the kiro-cli executable cannot be found or started.
        """
        logger.info(
            "Starting kiro-cli",
            extra={
                "workspace": str(workspace_path),
                "task_file": str(task_file),
                "timeout": self.timeout_seconds,
            },
        )

        return await asyncio.create_subprocess_exec(
            self.kiro_path,
            "--workspace",
            str(workspace_path),
            "--task",
            str(task_file),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def _collect_output_with_timeout(
        self,
        process: asyncio.subprocess.Process,
        log_callback: Optional[Callable[[str], None]],
    ) -> tuple:
        """Stream and collect process output within the timeout window.

        Reads stdout and stderr concurrently, streaming each line to
        the logger and optional callback. Raises TimeoutError if the
        process exceeds the configured timeout.

        Args:
            process: Running subprocess.
            log_callback: Optional per-line callback.

        Returns:
            Tuple of (stdout_text, stderr_text).

        Raises:
            asyncio.TimeoutError: If the process exceeds the timeout.
        """
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        async def stream_stdout():
            async for line in self._read_stream(process.stdout):
                stdout_lines.append(line)
                self._emit_line("stdout", line, log_callback)

        async def stream_stderr():
            async for line in self._read_stream(process.stderr):
                stderr_lines.append(line)
                self._emit_line("stderr", line, log_callback)

        await asyncio.wait_for(
            self._gather_streams(stream_stdout, stream_stderr, process),
            timeout=self.timeout_seconds,
        )

        return "\n".join(stdout_lines), "\n".join(stderr_lines)

    async def _gather_streams(
        self,
        stdout_reader: Callable,
        stderr_reader: Callable,
        process: asyncio.subprocess.Process,
    ) -> None:
        """Run stdout/stderr readers and wait for process exit.

        Args:
            stdout_reader: Coroutine reading stdout.
            stderr_reader: Coroutine reading stderr.
            process: The subprocess to wait on.
        """
        await asyncio.gather(stdout_reader(), stderr_reader())
        await process.wait()

    async def _read_stream(
        self, stream: Optional[asyncio.StreamReader]
    ):
        """Yield decoded lines from an async stream.

        Args:
            stream: Subprocess stdout or stderr stream.

        Yields:
            Each line as a stripped string.
        """
        if stream is None:
            return

        while True:
            raw_line = await stream.readline()
            if not raw_line:
                break
            yield raw_line.decode("utf-8", errors="replace").rstrip("\n")

    def _emit_line(
        self,
        stream_name: str,
        line: str,
        log_callback: Optional[Callable[[str], None]],
    ) -> None:
        """Send a single output line to the logger and optional callback.

        Args:
            stream_name: "stdout" or "stderr" for log context.
            line: The output line text.
            log_callback: Optional external callback.
        """
        logger.debug(
            "kiro-cli %s: %s",
            stream_name,
            line,
        )
        if log_callback is not None:
            log_callback(f"[{stream_name}] {line}")

    def _handle_timeout(
        self,
        process: asyncio.subprocess.Process,
        start_time: float,
    ) -> KiroResult:
        """Kill the process and return a timeout failure result.

        Args:
            process: The timed-out subprocess.
            start_time: Monotonic timestamp when execution started.

        Returns:
            KiroResult indicating timeout failure.
        """
        process.kill()
        duration = time.monotonic() - start_time
        logger.error(
            "kiro-cli timed out after %ds",
            self.timeout_seconds,
        )
        return KiroResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr=f"Process timed out after {self.timeout_seconds}s",
            duration_seconds=duration,
        )

    def _handle_os_error(
        self,
        exc: OSError,
        start_time: float,
    ) -> KiroResult:
        """Return a failure result for OS-level errors (e.g., missing binary).

        Args:
            exc: The caught OSError.
            start_time: Monotonic timestamp when execution started.

        Returns:
            KiroResult indicating OS error failure.
        """
        duration = time.monotonic() - start_time
        logger.error("Failed to start kiro-cli: %s", exc)
        return KiroResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr=f"Failed to start kiro-cli: {exc}",
            duration_seconds=duration,
        )

    def _build_result(
        self,
        exit_code: int,
        stdout: str,
        stderr: str,
        duration: float,
    ) -> KiroResult:
        """Construct a KiroResult from process output.

        Args:
            exit_code: Process exit code.
            stdout: Captured standard output.
            stderr: Captured standard error.
            duration: Execution wall-clock time in seconds.

        Returns:
            KiroResult with success derived from exit code.
        """
        is_success = exit_code == 0

        if is_success:
            logger.info(
                "kiro-cli completed successfully in %.1fs",
                duration,
            )
        else:
            logger.error(
                "kiro-cli failed with exit code %d in %.1fs",
                exit_code,
                duration,
            )

        return KiroResult(
            success=is_success,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
        )
