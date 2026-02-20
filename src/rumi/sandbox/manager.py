"""Docker sandbox manager for secure command execution."""

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path

import docker
from docker.errors import NotFound, APIError
from docker.models.containers import Container


@dataclass
class ExecResult:
    """Result of command execution in sandbox."""

    exit_code: int
    output: str
    duration_ms: float
    truncated: bool = False


@dataclass
class SandboxConfig:
    """Configuration for sandbox containers."""

    image: str = "rumi-runner:latest"
    memory_limit: str = "512m"
    cpu_limit: float = 1.0
    pids_limit: int = 128
    timeout: int = 30
    max_output_bytes: int = 100_000
    workspace_base: Path | None = None

    def __post_init__(self) -> None:
        if self.workspace_base is None:
            self.workspace_base = Path.home() / ".rumi" / "workspace"


class SandboxManager:
    """Manages Docker containers for sandboxed command execution."""

    CONTAINER_PREFIX = "rumi-runner"

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self.config = config or SandboxConfig()
        self.client = docker.from_env()
        self._containers: dict[str, Container] = {}

    def _container_name(self, chat_id: str) -> str:
        """Generate container name for a chat_id."""
        return f"{self.CONTAINER_PREFIX}-{chat_id}"

    def _workspace_path(self, chat_id: str) -> Path:
        """Get workspace path for a chat_id."""
        assert self.config.workspace_base is not None
        path = self.config.workspace_base / chat_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_container(self, chat_id: str) -> Container | None:
        """Get existing container for chat_id, or None if not found."""
        name = self._container_name(chat_id)

        # Check cache first
        if chat_id in self._containers:
            try:
                container = self._containers[chat_id]
                container.reload()
                if container.status == "running":
                    return container
                # Container exists but not running, remove from cache
                del self._containers[chat_id]
            except NotFound:
                del self._containers[chat_id]

        # Try to find by name
        try:
            container = self.client.containers.get(name)
            if container.status == "running":
                self._containers[chat_id] = container
                return container
        except NotFound:
            pass

        return None

    def create_container(self, chat_id: str) -> Container:
        """Create a new sandbox container for chat_id."""
        name = self._container_name(chat_id)
        workspace = self._workspace_path(chat_id)

        # Remove existing container if any
        try:
            old = self.client.containers.get(name)
            old.remove(force=True)
        except NotFound:
            pass

        container = self.client.containers.run(
            self.config.image,
            name=name,
            command="sleep infinity",  # Keep container alive
            detach=True,
            # Security flags
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            pids_limit=self.config.pids_limit,
            mem_limit=self.config.memory_limit,
            nano_cpus=int(self.config.cpu_limit * 1e9),
            network_mode="none",
            user="1000:1000",
            working_dir="/workspace",
            # Workspace mount (writable)
            volumes={
                str(workspace): {"bind": "/workspace", "mode": "rw"},
            },
            # tmpfs for /tmp (read-only root needs this)
            tmpfs={"/tmp": "size=64M,mode=1777"},
        )

        self._containers[chat_id] = container
        return container

    def destroy_container(self, chat_id: str) -> bool:
        """Destroy container for chat_id. Returns True if container was found."""
        name = self._container_name(chat_id)

        # Remove from cache
        if chat_id in self._containers:
            del self._containers[chat_id]

        try:
            container = self.client.containers.get(name)
            container.remove(force=True)
            return True
        except NotFound:
            return False

    def ensure_container(self, chat_id: str) -> Container:
        """Get or create container for chat_id."""
        container = self.get_container(chat_id)
        if container is None:
            container = self.create_container(chat_id)
        return container

    async def exec_command(
        self,
        chat_id: str,
        argv: list[str],
        timeout: int | None = None,
    ) -> ExecResult:
        """Execute a command in the sandbox container."""
        if timeout is None:
            timeout = self.config.timeout

        container = self.ensure_container(chat_id)

        start_time = time.monotonic()

        try:
            # Run in thread pool since docker-py is sync
            loop = asyncio.get_event_loop()
            exit_code, output = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: container.exec_run(
                        argv,
                        user="1000:1000",
                        workdir="/workspace",
                    ),
                ),
                timeout=timeout,
            )

            duration_ms = (time.monotonic() - start_time) * 1000

            # Decode output
            output_str = output.decode("utf-8", errors="replace")

            # Truncate if needed
            truncated = len(output_str) > self.config.max_output_bytes
            if truncated:
                output_str = output_str[: self.config.max_output_bytes] + "\n... [truncated]"

            return ExecResult(
                exit_code=exit_code,
                output=output_str,
                duration_ms=duration_ms,
                truncated=truncated,
            )

        except asyncio.TimeoutError:
            duration_ms = (time.monotonic() - start_time) * 1000
            return ExecResult(
                exit_code=-1,
                output=f"Command timed out after {timeout}s",
                duration_ms=duration_ms,
                truncated=False,
            )
        except APIError as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            return ExecResult(
                exit_code=-1,
                output=f"Docker API error: {e}",
                duration_ms=duration_ms,
                truncated=False,
            )

    def cleanup_all(self) -> int:
        """Remove all rumi containers. Returns count of removed containers."""
        count = 0
        for container in self.client.containers.list(all=True):
            if container.name.startswith(self.CONTAINER_PREFIX):
                container.remove(force=True)
                count += 1
        self._containers.clear()
        return count
