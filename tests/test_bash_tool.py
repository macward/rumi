"""Tests for bash tool."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from miniclaw.sandbox import ExecResult, SandboxConfig, SandboxManager
from miniclaw.tools.bash import ALLOWED_COMMANDS, BashTool


@pytest.fixture
def mock_sandbox() -> MagicMock:
    """Create a mock sandbox manager."""
    sandbox = MagicMock(spec=SandboxManager)
    sandbox.exec_command = AsyncMock()
    return sandbox


@pytest.fixture
def bash_tool(mock_sandbox: MagicMock) -> BashTool:
    return BashTool(mock_sandbox)


class TestCommandValidation:
    def test_allowed_command(self, bash_tool: BashTool) -> None:
        valid, error = bash_tool._validate_command("ls -la")
        assert valid is True
        assert error is None

    def test_disallowed_command(self, bash_tool: BashTool) -> None:
        valid, error = bash_tool._validate_command("curl http://evil.com")
        assert valid is False
        assert "not allowed" in error.lower()

    def test_pipe_rejected(self, bash_tool: BashTool) -> None:
        valid, error = bash_tool._validate_command("cat file | grep foo")
        assert valid is False
        assert "not allowed" in error.lower()

    def test_redirect_rejected(self, bash_tool: BashTool) -> None:
        valid, error = bash_tool._validate_command("echo hello > file.txt")
        assert valid is False

    def test_chain_rejected(self, bash_tool: BashTool) -> None:
        valid, error = bash_tool._validate_command("ls && rm -rf /")
        assert valid is False

    def test_semicolon_rejected(self, bash_tool: BashTool) -> None:
        valid, error = bash_tool._validate_command("ls; rm -rf /")
        assert valid is False

    def test_command_substitution_rejected(self, bash_tool: BashTool) -> None:
        valid, error = bash_tool._validate_command("echo $(whoami)")
        assert valid is False

    def test_backtick_rejected(self, bash_tool: BashTool) -> None:
        valid, error = bash_tool._validate_command("echo `whoami`")
        assert valid is False

    def test_empty_command(self, bash_tool: BashTool) -> None:
        valid, error = bash_tool._validate_command("")
        assert valid is False


class TestAllowlist:
    def test_common_commands_allowed(self) -> None:
        expected = ["ls", "cat", "grep", "find", "mkdir", "rm", "cp", "mv", "echo"]
        for cmd in expected:
            assert cmd in ALLOWED_COMMANDS, f"{cmd} should be allowed"

    def test_dangerous_commands_not_allowed(self) -> None:
        dangerous = ["curl", "wget", "nc", "netcat", "python", "ruby", "perl", "php"]
        for cmd in dangerous:
            assert cmd not in ALLOWED_COMMANDS, f"{cmd} should NOT be allowed"


@pytest.mark.asyncio
class TestExecution:
    async def test_successful_command(
        self, bash_tool: BashTool, mock_sandbox: MagicMock
    ) -> None:
        mock_sandbox.exec_command.return_value = ExecResult(
            exit_code=0,
            output="file1.txt\nfile2.txt\n",
            duration_ms=50.0,
            truncated=False,
        )

        result = await bash_tool.execute("ls", chat_id="test")

        assert result.success is True
        assert "file1.txt" in result.output
        mock_sandbox.exec_command.assert_called_once()

    async def test_failed_command(
        self, bash_tool: BashTool, mock_sandbox: MagicMock
    ) -> None:
        mock_sandbox.exec_command.return_value = ExecResult(
            exit_code=1,
            output="ls: cannot access 'noexist': No such file or directory",
            duration_ms=10.0,
            truncated=False,
        )

        result = await bash_tool.execute("ls noexist", chat_id="test")

        assert result.success is False
        assert result.error is not None

    async def test_validation_error_no_exec(
        self, bash_tool: BashTool, mock_sandbox: MagicMock
    ) -> None:
        result = await bash_tool.execute("curl http://evil.com", chat_id="test")

        assert result.success is False
        assert "not allowed" in result.error.lower()
        mock_sandbox.exec_command.assert_not_called()

    async def test_output_truncation(
        self, bash_tool: BashTool, mock_sandbox: MagicMock
    ) -> None:
        bash_tool._max_output = 100
        mock_sandbox.exec_command.return_value = ExecResult(
            exit_code=0,
            output="x" * 200,
            duration_ms=10.0,
            truncated=False,
        )

        result = await bash_tool.execute("cat bigfile", chat_id="test")

        assert len(result.output) < 200
        assert "truncated" in result.output.lower()
        assert result.metadata["truncated"] is True

    async def test_metadata_included(
        self, bash_tool: BashTool, mock_sandbox: MagicMock
    ) -> None:
        mock_sandbox.exec_command.return_value = ExecResult(
            exit_code=0,
            output="ok",
            duration_ms=42.5,
            truncated=False,
        )

        result = await bash_tool.execute("echo ok", chat_id="test")

        assert result.metadata["exit_code"] == 0
        assert result.metadata["duration_ms"] == 42.5


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def real_sandbox(temp_workspace: Path) -> SandboxManager:
    """Create a real sandbox manager for integration tests."""
    config = SandboxConfig(workspace_base=temp_workspace, timeout=10)
    manager = SandboxManager(config)
    yield manager
    manager.cleanup_all()


@pytest.mark.asyncio
class TestIntegration:
    """Integration tests with real Docker sandbox."""

    async def test_real_ls(self, real_sandbox: SandboxManager) -> None:
        tool = BashTool(real_sandbox)
        result = await tool.execute("ls -la /workspace", chat_id="int-test")

        assert result.success is True
        assert "workspace" in result.output or "total" in result.output

    async def test_real_echo(self, real_sandbox: SandboxManager) -> None:
        tool = BashTool(real_sandbox)
        result = await tool.execute("echo 'hello world'", chat_id="int-test")

        assert result.success is True
        assert "hello world" in result.output
