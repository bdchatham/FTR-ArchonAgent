"""Unit tests for Kiro CLI runner.

Tests subprocess execution, timeout enforcement, output streaming,
exit code handling, and error recovery for the KiroRunner.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7**
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from typing import List, Optional

import pytest

from src.pipeline.runner.kiro import KiroResult, KiroRunner


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def runner():
    return KiroRunner(kiro_path="/usr/local/bin/kiro-cli", timeout_seconds=60)


@pytest.fixture
def workspace_path(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def task_file(tmp_path):
    tf = tmp_path / "task.md"
    tf.write_text("Implement feature X")
    return tf


def _make_mock_process(
    returncode: int = 0,
    stdout_lines: Optional[List[bytes]] = None,
    stderr_lines: Optional[List[bytes]] = None,
):
    """Build a mock subprocess with readable stdout/stderr streams."""
    process = AsyncMock()
    process.returncode = returncode
    process.kill = MagicMock()

    stdout_data = b"".join(stdout_lines) if stdout_lines else b""
    stderr_data = b"".join(stderr_lines) if stderr_lines else b""

    stdout_reader = AsyncMock()
    stdout_reader.readline = AsyncMock(
        side_effect=list(stdout_lines or []) + [b""]
    )
    stderr_reader = AsyncMock()
    stderr_reader.readline = AsyncMock(
        side_effect=list(stderr_lines or []) + [b""]
    )

    process.stdout = stdout_reader
    process.stderr = stderr_reader
    process.wait = AsyncMock()

    return process


class TestSuccessfulExecution:
    """Validates Requirement 5.5: exit code 0 → success."""

    def test_zero_exit_code_returns_success(
        self, runner, workspace_path, task_file
    ):
        process = _make_mock_process(
            returncode=0,
            stdout_lines=[b"Building...\n", b"Done.\n"],
            stderr_lines=[],
        )
        with patch(
            "asyncio.create_subprocess_exec", return_value=process
        ):
            result = run_async(runner.run(workspace_path, task_file))

        assert result.success is True
        assert result.exit_code == 0
        assert "Building..." in result.stdout
        assert "Done." in result.stdout

    def test_empty_output_still_succeeds(
        self, runner, workspace_path, task_file
    ):
        process = _make_mock_process(returncode=0)
        with patch(
            "asyncio.create_subprocess_exec", return_value=process
        ):
            result = run_async(runner.run(workspace_path, task_file))

        assert result.success is True
        assert result.exit_code == 0
        assert result.stdout == ""
        assert result.stderr == ""

    def test_duration_is_positive(self, runner, workspace_path, task_file):
        process = _make_mock_process(returncode=0)
        with patch(
            "asyncio.create_subprocess_exec", return_value=process
        ):
            result = run_async(runner.run(workspace_path, task_file))

        assert result.duration_seconds >= 0


class TestFailedExecution:
    """Validates Requirement 5.6: non-zero exit → failure."""

    def test_nonzero_exit_code_returns_failure(
        self, runner, workspace_path, task_file
    ):
        process = _make_mock_process(
            returncode=1,
            stdout_lines=[],
            stderr_lines=[b"Error: compilation failed\n"],
        )
        with patch(
            "asyncio.create_subprocess_exec", return_value=process
        ):
            result = run_async(runner.run(workspace_path, task_file))

        assert result.success is False
        assert result.exit_code == 1
        assert "compilation failed" in result.stderr

    def test_exit_code_preserved_for_various_codes(
        self, runner, workspace_path, task_file
    ):
        for code in [2, 127, 137, 255]:
            process = _make_mock_process(returncode=code)
            with patch(
                "asyncio.create_subprocess_exec", return_value=process
            ):
                result = run_async(runner.run(workspace_path, task_file))

            assert result.success is False
            assert result.exit_code == code


class TestTimeoutEnforcement:
    """Validates Requirement 5.4: configurable timeout."""

    def test_timeout_kills_process_and_returns_failure(
        self, workspace_path, task_file
    ):
        short_timeout_runner = KiroRunner(
            kiro_path="/usr/local/bin/kiro-cli", timeout_seconds=1
        )
        process = AsyncMock()
        process.kill = MagicMock()

        stdout_reader = AsyncMock()
        stderr_reader = AsyncMock()

        async def hang_forever():
            await asyncio.sleep(100)
            return b""

        stdout_reader.readline = hang_forever
        stderr_reader.readline = hang_forever
        process.stdout = stdout_reader
        process.stderr = stderr_reader
        process.wait = AsyncMock(side_effect=asyncio.sleep(100))

        with patch(
            "asyncio.create_subprocess_exec", return_value=process
        ):
            result = run_async(
                short_timeout_runner.run(workspace_path, task_file)
            )

        assert result.success is False
        assert result.exit_code == -1
        assert "timed out" in result.stderr
        process.kill.assert_called_once()

    def test_timeout_duration_is_recorded(self, workspace_path, task_file):
        short_timeout_runner = KiroRunner(
            kiro_path="/usr/local/bin/kiro-cli", timeout_seconds=1
        )
        process = AsyncMock()
        process.kill = MagicMock()

        stdout_reader = AsyncMock()
        stderr_reader = AsyncMock()

        async def hang():
            await asyncio.sleep(100)
            return b""

        stdout_reader.readline = hang
        stderr_reader.readline = hang
        process.stdout = stdout_reader
        process.stderr = stderr_reader
        process.wait = AsyncMock(side_effect=asyncio.sleep(100))

        with patch(
            "asyncio.create_subprocess_exec", return_value=process
        ):
            result = run_async(
                short_timeout_runner.run(workspace_path, task_file)
            )

        assert result.duration_seconds >= 0


class TestOSErrorHandling:
    """Validates graceful handling when kiro-cli binary is missing."""

    def test_missing_binary_returns_failure(
        self, runner, workspace_path, task_file
    ):
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=OSError("No such file or directory"),
        ):
            result = run_async(runner.run(workspace_path, task_file))

        assert result.success is False
        assert result.exit_code == -1
        assert "Failed to start kiro-cli" in result.stderr

    def test_permission_denied_returns_failure(
        self, runner, workspace_path, task_file
    ):
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=OSError("Permission denied"),
        ):
            result = run_async(runner.run(workspace_path, task_file))

        assert result.success is False
        assert result.exit_code == -1
        assert "Permission denied" in result.stderr


class TestOutputStreaming:
    """Validates Requirement 5.7: stream output to logs."""

    def test_stdout_lines_streamed_to_callback(
        self, runner, workspace_path, task_file
    ):
        captured_lines: list[str] = []
        process = _make_mock_process(
            returncode=0,
            stdout_lines=[b"line1\n", b"line2\n", b"line3\n"],
            stderr_lines=[],
        )
        with patch(
            "asyncio.create_subprocess_exec", return_value=process
        ):
            result = run_async(
                runner.run(
                    workspace_path, task_file, log_callback=captured_lines.append
                )
            )

        assert result.success is True
        stdout_callbacks = [l for l in captured_lines if "[stdout]" in l]
        assert len(stdout_callbacks) == 3
        assert "[stdout] line1" in stdout_callbacks[0]

    def test_stderr_lines_streamed_to_callback(
        self, runner, workspace_path, task_file
    ):
        captured_lines: list[str] = []
        process = _make_mock_process(
            returncode=1,
            stdout_lines=[],
            stderr_lines=[b"warning: something\n", b"error: fatal\n"],
        )
        with patch(
            "asyncio.create_subprocess_exec", return_value=process
        ):
            result = run_async(
                runner.run(
                    workspace_path, task_file, log_callback=captured_lines.append
                )
            )

        stderr_callbacks = [l for l in captured_lines if "[stderr]" in l]
        assert len(stderr_callbacks) == 2

    def test_no_callback_does_not_raise(
        self, runner, workspace_path, task_file
    ):
        process = _make_mock_process(
            returncode=0,
            stdout_lines=[b"output\n"],
            stderr_lines=[b"warn\n"],
        )
        with patch(
            "asyncio.create_subprocess_exec", return_value=process
        ):
            result = run_async(
                runner.run(workspace_path, task_file, log_callback=None)
            )

        assert result.success is True


class TestOutputCapture:
    """Validates Requirement 5.3: capture stdout and stderr."""

    def test_multiline_stdout_captured(
        self, runner, workspace_path, task_file
    ):
        process = _make_mock_process(
            returncode=0,
            stdout_lines=[b"alpha\n", b"beta\n", b"gamma\n"],
            stderr_lines=[],
        )
        with patch(
            "asyncio.create_subprocess_exec", return_value=process
        ):
            result = run_async(runner.run(workspace_path, task_file))

        assert result.stdout == "alpha\nbeta\ngamma"

    def test_multiline_stderr_captured(
        self, runner, workspace_path, task_file
    ):
        process = _make_mock_process(
            returncode=1,
            stdout_lines=[],
            stderr_lines=[b"err1\n", b"err2\n"],
        )
        with patch(
            "asyncio.create_subprocess_exec", return_value=process
        ):
            result = run_async(runner.run(workspace_path, task_file))

        assert result.stderr == "err1\nerr2"

    def test_mixed_stdout_and_stderr_captured(
        self, runner, workspace_path, task_file
    ):
        process = _make_mock_process(
            returncode=0,
            stdout_lines=[b"out\n"],
            stderr_lines=[b"warn\n"],
        )
        with patch(
            "asyncio.create_subprocess_exec", return_value=process
        ):
            result = run_async(runner.run(workspace_path, task_file))

        assert "out" in result.stdout
        assert "warn" in result.stderr


class TestSubprocessArguments:
    """Validates Requirements 5.1, 5.2: workspace path and task file args."""

    def test_kiro_cli_invoked_with_correct_arguments(
        self, runner, workspace_path, task_file
    ):
        process = _make_mock_process(returncode=0)
        with patch(
            "asyncio.create_subprocess_exec", return_value=process
        ) as mock_exec:
            run_async(runner.run(workspace_path, task_file))

        mock_exec.assert_called_once()
        call_args = mock_exec.call_args
        positional = call_args[0]

        assert positional[0] == "/usr/local/bin/kiro-cli"
        assert "--workspace" in positional
        assert str(workspace_path) in positional
        assert "--task" in positional
        assert str(task_file) in positional

    def test_custom_kiro_path_used(self, workspace_path, task_file):
        custom_runner = KiroRunner(
            kiro_path="/opt/bin/my-kiro", timeout_seconds=30
        )
        process = _make_mock_process(returncode=0)
        with patch(
            "asyncio.create_subprocess_exec", return_value=process
        ) as mock_exec:
            run_async(custom_runner.run(workspace_path, task_file))

        positional = mock_exec.call_args[0]
        assert positional[0] == "/opt/bin/my-kiro"


class TestKiroResultDataclass:
    """Validates KiroResult structure."""

    def test_success_result_fields(self):
        result = KiroResult(
            success=True,
            exit_code=0,
            stdout="done",
            stderr="",
            duration_seconds=12.5,
        )
        assert result.success is True
        assert result.exit_code == 0
        assert result.stdout == "done"
        assert result.stderr == ""
        assert result.duration_seconds == 12.5

    def test_failure_result_fields(self):
        result = KiroResult(
            success=False,
            exit_code=1,
            stdout="",
            stderr="error",
            duration_seconds=3.0,
        )
        assert result.success is False
        assert result.exit_code == 1
        assert result.stderr == "error"
