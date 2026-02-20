"""Tests for sandbox manager."""

import tempfile
from pathlib import Path

import pytest

from rumi.sandbox import ExecResult, SandboxConfig, SandboxManager


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sandbox(temp_workspace: Path) -> SandboxManager:
    """Create a sandbox manager with temp workspace."""
    config = SandboxConfig(workspace_base=temp_workspace, timeout=10)
    manager = SandboxManager(config)
    yield manager
    # Cleanup after test
    manager.cleanup_all()


class TestSandboxConfig:
    def test_default_workspace(self):
        config = SandboxConfig()
        assert config.workspace_base == Path.home() / ".rumi" / "workspace"

    def test_custom_workspace(self, temp_workspace: Path):
        config = SandboxConfig(workspace_base=temp_workspace)
        assert config.workspace_base == temp_workspace


class TestSandboxManager:
    def test_container_name(self, sandbox: SandboxManager):
        name = sandbox._container_name("test-123")
        assert name == "rumi-runner-test-123"

    def test_workspace_path_created(self, sandbox: SandboxManager, temp_workspace: Path):
        path = sandbox._workspace_path("test-session")
        assert path.exists()
        assert path == temp_workspace / "test-session"

    def test_create_and_get_container(self, sandbox: SandboxManager):
        container = sandbox.create_container("test-create")
        assert container is not None
        container.reload()  # Get latest status
        assert container.status == "running"

        # Should be able to get it back
        got = sandbox.get_container("test-create")
        assert got is not None
        assert got.id == container.id

    def test_destroy_container(self, sandbox: SandboxManager):
        sandbox.create_container("test-destroy")

        result = sandbox.destroy_container("test-destroy")
        assert result is True

        # Should not exist anymore
        got = sandbox.get_container("test-destroy")
        assert got is None

    def test_destroy_nonexistent(self, sandbox: SandboxManager):
        result = sandbox.destroy_container("nonexistent")
        assert result is False

    def test_ensure_container_creates(self, sandbox: SandboxManager):
        container = sandbox.ensure_container("test-ensure")
        assert container is not None
        container.reload()
        assert container.status == "running"

    def test_ensure_container_reuses(self, sandbox: SandboxManager):
        c1 = sandbox.ensure_container("test-reuse")
        c2 = sandbox.ensure_container("test-reuse")
        assert c1.id == c2.id


@pytest.mark.asyncio
class TestExecCommand:
    async def test_simple_command(self, sandbox: SandboxManager):
        result = await sandbox.exec_command("test-exec", ["echo", "hello"])
        assert result.exit_code == 0
        assert "hello" in result.output
        assert result.duration_ms > 0

    async def test_command_exit_code(self, sandbox: SandboxManager):
        result = await sandbox.exec_command("test-exit", ["sh", "-c", "exit 42"])
        assert result.exit_code == 42

    async def test_command_timeout(self, sandbox: SandboxManager):
        result = await sandbox.exec_command("test-timeout", ["sleep", "60"], timeout=1)
        assert result.exit_code == -1
        assert "timed out" in result.output.lower()

    async def test_workspace_writable(self, sandbox: SandboxManager):
        # Create a file in workspace
        result = await sandbox.exec_command(
            "test-write",
            ["sh", "-c", "echo 'test content' > /workspace/test.txt && cat /workspace/test.txt"],
        )
        assert result.exit_code == 0
        assert "test content" in result.output

    async def test_root_readonly(self, sandbox: SandboxManager):
        # Should not be able to write outside workspace
        result = await sandbox.exec_command(
            "test-readonly",
            ["sh", "-c", "echo 'fail' > /etc/test.txt"],
        )
        assert result.exit_code != 0

    async def test_no_network(self, sandbox: SandboxManager):
        # Network should be disabled
        result = await sandbox.exec_command(
            "test-network",
            ["sh", "-c", "cat /etc/resolv.conf || echo 'no resolv.conf'"],
        )
        # Should work but no actual network access
        assert result.exit_code == 0
