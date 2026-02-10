"""Property-based tests for Kiro CLI runner.

Verifies universal properties of KiroRunner across randomized inputs:
exit code semantics, output capture integrity, timeout behavior, and
result structure consistency.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7**

Feature: agent-orchestration

Testing Configuration:
- Library: Hypothesis (Python)
- Minimum iterations: 100 per property test
- Tag format: Feature: agent-orchestration, Property N: <property_text>
"""

import asyncio
import tempfile
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, strategies as st

from src.pipeline.runner.kiro import KiroResult, KiroRunner


def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_mock_process(
    returncode: int,
    stdout_lines: List[bytes],
    stderr_lines: List[bytes],
):
    """Build a mock subprocess with controllable output streams."""
    process = AsyncMock()
    process.returncode = returncode
    process.kill = MagicMock()

    stdout_reader = AsyncMock()
    stdout_reader.readline = AsyncMock(
        side_effect=list(stdout_lines) + [b""]
    )
    stderr_reader = AsyncMock()
    stderr_reader.readline = AsyncMock(
        side_effect=list(stderr_lines) + [b""]
    )

    process.stdout = stdout_reader
    process.stderr = stderr_reader
    process.wait = AsyncMock()

    return process


safe_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00\r",
    ),
    min_size=0,
    max_size=200,
)

stdout_line_strategy = st.lists(
    safe_text.map(lambda t: (t.replace("\n", " ") + "\n").encode("utf-8")),
    min_size=0,
    max_size=20,
)

stderr_line_strategy = st.lists(
    safe_text.map(lambda t: (t.replace("\n", " ") + "\n").encode("utf-8")),
    min_size=0,
    max_size=20,
)


class TestExitCodeSemantics:
    """Property: exit code 0 ↔ success=True, non-zero ↔ success=False.

    Feature: agent-orchestration

    *For any* exit code returned by kiro-cli, the KiroRunner SHALL set
    success=True when exit code is 0 and success=False otherwise.

    **Validates: Requirements 5.5, 5.6**
    """

    @given(exit_code=st.integers(min_value=0, max_value=255))
    @settings(max_examples=100)
    def test_exit_code_determines_success(self, exit_code):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "ws"
            workspace.mkdir()
            task = Path(tmpdir) / "task.md"
            task.write_text("task")

            runner = KiroRunner(kiro_path="/bin/kiro", timeout_seconds=60)
            process = _make_mock_process(exit_code, [], [])
            with patch(
                "asyncio.create_subprocess_exec", return_value=process
            ):
                result = run_async(runner.run(workspace, task))

            if exit_code == 0:
                assert result.success is True
            else:
                assert result.success is False
            assert result.exit_code == exit_code


class TestOutputCaptureIntegrity:
    """Property: all output lines are captured in the result.

    Feature: agent-orchestration

    *For any* set of stdout and stderr lines produced by kiro-cli,
    the KiroRunner SHALL capture all lines in the result.

    **Validates: Requirements 5.3, 5.7**
    """

    @given(
        stdout_lines=stdout_line_strategy,
        stderr_lines=stderr_line_strategy,
    )
    @settings(max_examples=100)
    def test_all_output_lines_captured(self, stdout_lines, stderr_lines):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "ws"
            workspace.mkdir()
            task = Path(tmpdir) / "task.md"
            task.write_text("task")

            runner = KiroRunner(kiro_path="/bin/kiro", timeout_seconds=60)
            process = _make_mock_process(0, stdout_lines, stderr_lines)
            with patch(
                "asyncio.create_subprocess_exec", return_value=process
            ):
                result = run_async(runner.run(workspace, task))

            expected_stdout_parts = [
                line.decode("utf-8", errors="replace").rstrip("\n")
                for line in stdout_lines
            ]
            expected_stderr_parts = [
                line.decode("utf-8", errors="replace").rstrip("\n")
                for line in stderr_lines
            ]

            for part in expected_stdout_parts:
                assert part in result.stdout
            for part in expected_stderr_parts:
                assert part in result.stderr


class TestCallbackStreaming:
    """Property: every output line is forwarded to the log callback.

    Feature: agent-orchestration

    *For any* set of output lines, the KiroRunner SHALL invoke the
    log_callback once per line with the correct stream prefix.

    **Validates: Requirement 5.7**
    """

    @given(
        stdout_lines=stdout_line_strategy,
        stderr_lines=stderr_line_strategy,
    )
    @settings(max_examples=100)
    def test_callback_receives_all_lines(self, stdout_lines, stderr_lines):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "ws"
            workspace.mkdir()
            task = Path(tmpdir) / "task.md"
            task.write_text("task")

            runner = KiroRunner(kiro_path="/bin/kiro", timeout_seconds=60)
            captured: list = []
            process = _make_mock_process(0, stdout_lines, stderr_lines)
            with patch(
                "asyncio.create_subprocess_exec", return_value=process
            ):
                run_async(
                    runner.run(workspace, task, log_callback=captured.append)
                )

            total_expected = len(stdout_lines) + len(stderr_lines)
            assert len(captured) == total_expected

            stdout_callbacks = [l for l in captured if l.startswith("[stdout]")]
            stderr_callbacks = [l for l in captured if l.startswith("[stderr]")]
            assert len(stdout_callbacks) == len(stdout_lines)
            assert len(stderr_callbacks) == len(stderr_lines)


class TestResultStructure:
    """Property: KiroResult always has valid field types and ranges.

    Feature: agent-orchestration

    *For any* kiro-cli execution, the returned KiroResult SHALL have
    correctly typed fields and non-negative duration.

    **Validates: Requirements 5.3, 5.5, 5.6**
    """

    @given(
        exit_code=st.integers(min_value=0, max_value=255),
        stdout_lines=stdout_line_strategy,
        stderr_lines=stderr_line_strategy,
    )
    @settings(max_examples=100)
    def test_result_fields_are_well_typed(
        self, exit_code, stdout_lines, stderr_lines
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "ws"
            workspace.mkdir()
            task = Path(tmpdir) / "task.md"
            task.write_text("task")

            runner = KiroRunner(kiro_path="/bin/kiro", timeout_seconds=60)
            process = _make_mock_process(exit_code, stdout_lines, stderr_lines)
            with patch(
                "asyncio.create_subprocess_exec", return_value=process
            ):
                result = run_async(runner.run(workspace, task))

            assert isinstance(result, KiroResult)
            assert isinstance(result.success, bool)
            assert isinstance(result.exit_code, int)
            assert isinstance(result.stdout, str)
            assert isinstance(result.stderr, str)
            assert isinstance(result.duration_seconds, float)
            assert result.duration_seconds >= 0


class TestTimeoutProperty:
    """Property: timeout always produces a failed result with exit_code -1.

    Feature: agent-orchestration

    *For any* timeout value, when kiro-cli exceeds the timeout the
    KiroRunner SHALL kill the process and return a failure result.

    **Validates: Requirement 5.4**
    """

    @given(timeout=st.integers(min_value=1, max_value=3))
    @settings(max_examples=10, deadline=None)
    def test_timeout_always_fails(self, timeout):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "ws"
            workspace.mkdir()
            task = Path(tmpdir) / "task.md"
            task.write_text("task")

            runner = KiroRunner(kiro_path="/bin/kiro", timeout_seconds=timeout)
            process = AsyncMock()
            process.kill = MagicMock()

            stdout_reader = AsyncMock()
            stderr_reader = AsyncMock()

            async def hang():
                await asyncio.sleep(1000)
                return b""

            stdout_reader.readline = hang
            stderr_reader.readline = hang
            process.stdout = stdout_reader
            process.stderr = stderr_reader
            process.wait = AsyncMock(side_effect=asyncio.sleep(1000))

            with patch(
                "asyncio.create_subprocess_exec", return_value=process
            ):
                result = run_async(runner.run(workspace, task))

            assert result.success is False
            assert result.exit_code == -1
            assert "timed out" in result.stderr
            process.kill.assert_called()


class TestOSErrorProperty:
    """Property: OS errors always produce a failed result.

    Feature: agent-orchestration

    *For any* OS error message, the KiroRunner SHALL return a failure
    result with exit_code -1 and the error message in stderr.

    **Validates: Requirement 5.6**
    """

    @given(
        error_message=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
            min_size=1,
            max_size=100,
        )
    )
    @settings(max_examples=50)
    def test_os_error_always_fails(self, error_message):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "ws"
            workspace.mkdir()
            task = Path(tmpdir) / "task.md"
            task.write_text("task")

            runner = KiroRunner(kiro_path="/bin/kiro", timeout_seconds=60)
            with patch(
                "asyncio.create_subprocess_exec",
                side_effect=OSError(error_message),
            ):
                result = run_async(runner.run(workspace, task))

            assert result.success is False
            assert result.exit_code == -1
            assert "Failed to start kiro-cli" in result.stderr
            assert result.duration_seconds >= 0
