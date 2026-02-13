"""CLI interface for MiniClaw."""

import asyncio
import os
import uuid
from pathlib import Path

from groq import AsyncGroq

from .agent import AgentConfig, AgentLoop, StopReason
from .logging import configure_logger, get_logger
from .memory import FactExtractor, ForgetTool, MemoryManager, MemoryStore, RememberTool
from .sandbox import SandboxConfig, SandboxManager
from .session import SessionConfig, SessionManager
from .tools import BashTool, ToolRegistry, WebFetchTool, WebSearchTool

MEMORY_DB_PATH = Path.home() / ".miniclaw" / "memory.db"


BANNER = """
╔══════════════════════════════════════════╗
║           🦀 MiniClaw v0.1.0             ║
║    Educational Sandbox Assistant         ║
╚══════════════════════════════════════════╝

Commands:
  /exit, /quit  - Exit the CLI
  /reset        - Reset session (destroy container)
  /help         - Show this help

Type your message and press Enter.
"""


def _config_from_env() -> tuple[AgentConfig, SandboxConfig]:
    """Load configuration from environment variables."""
    agent_config = AgentConfig(
        model=os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile"),
    )

    sandbox_config = SandboxConfig(
        timeout=int(os.getenv("SANDBOX_TIMEOUT", "30")),
        memory_limit=os.getenv("SANDBOX_MEMORY", "512m"),
        cpu_limit=float(os.getenv("SANDBOX_CPUS", "1")),
    )

    return agent_config, sandbox_config


class CLI:
    """Interactive command-line interface for MiniClaw."""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        config: AgentConfig | None = None,
        sandbox: SandboxManager | None = None,
        memory_db_path: Path | None = None,
    ) -> None:
        # Load config from env if not provided
        if config is None or sandbox is None:
            agent_config, sandbox_config = _config_from_env()
            config = config or agent_config
            if sandbox is None:
                sandbox = SandboxManager(sandbox_config)

        self.sandbox = sandbox
        self.sessions = SessionManager(sandbox=sandbox)

        # Setup memory system
        db_path = memory_db_path or MEMORY_DB_PATH
        self.memory_store = MemoryStore(db_path)
        self.memory_store.init_db()

        # Create extractor with LLM client for automatic extraction
        groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
        extractor = FactExtractor(groq_client, model=config.model)
        self.memory_manager = MemoryManager(self.memory_store, extractor=extractor)

        # Register tools with sandbox
        if registry is None:
            registry = ToolRegistry()
            registry.register(BashTool(sandbox))
            registry.register(WebFetchTool())
            # Register web search if Tavily API key is available
            if os.getenv("TAVILY_API_KEY"):
                try:
                    registry.register(WebSearchTool())
                except ImportError:
                    pass  # tavily-python not installed, skip
            # Register memory tools
            registry.register(RememberTool(self.memory_store))
            registry.register(ForgetTool(self.memory_store))

        self.registry = registry
        self.config = config
        self.chat_id = self._new_chat_id()
        self.agent: AgentLoop | None = None
        self.logger = get_logger()
        self._conversation_history: list[dict] = []

    def _new_chat_id(self) -> str:
        """Generate a new chat ID."""
        return f"cli-{uuid.uuid4().hex[:8]}"

    def _init_agent(self) -> None:
        """Initialize or reinitialize the agent."""
        self.agent = AgentLoop(
            self.registry, self.config, memory=self.memory_manager
        )
        self.logger.set_chat_id(self.chat_id)
        self.logger.log("session_start", chat_id=self.chat_id)
        self._conversation_history = []

    async def _reset(self) -> None:
        """Reset the session and destroy container."""
        old_chat_id = self.chat_id

        # Extract facts before resetting
        if self.agent and self._conversation_history:
            await self.agent.on_session_end(self._conversation_history)

        # Destroy old session and container
        await self.sessions.destroy_session(old_chat_id)

        self.chat_id = self._new_chat_id()
        self._init_agent()
        self.logger.log("session_reset", old_chat_id=old_chat_id, chat_id=self.chat_id)
        print(f"\n✓ Session reset. Container destroyed. New chat_id: {self.chat_id}")

    def _format_response(self, response: str, stop_reason: StopReason, turns: int) -> str:
        """Format the agent's response for display."""
        output = ["\n" + "─" * 40]
        output.append(response)
        output.append("─" * 40)

        if stop_reason != StopReason.COMPLETE:
            output.append(f"⚠ Stopped: {stop_reason.value} (turns: {turns})")

        return "\n".join(output)

    async def _process_message(self, message: str) -> None:
        """Process a user message through the agent."""
        if self.agent is None:
            self._init_agent()

        assert self.agent is not None

        try:
            result = await self.agent.run(message, chat_id=self.chat_id)

            # Track conversation for extraction at session end
            self._conversation_history.append({"role": "user", "content": message})
            self._conversation_history.append(
                {"role": "assistant", "content": result.response}
            )

            print(self._format_response(result.response, result.stop_reason, result.turns))

            self.logger.log_agent_stop(
                result.stop_reason.value,
                chat_id=self.chat_id,
                turns=result.turns,
            )

        except Exception as e:
            error_msg = f"Error: {e}"
            print(f"\n❌ {error_msg}")
            self.logger.log("error", chat_id=self.chat_id, error=str(e))

    async def _handle_command(self, command: str) -> bool:
        """Handle a special command. Returns True if should continue, False to exit."""
        cmd = command.lower().strip()

        if cmd in ("/exit", "/quit", "exit", "quit"):
            # Extract facts before exit
            if self.agent and self._conversation_history:
                print("\n📝 Extracting memories...")
                facts = await self.agent.on_session_end(self._conversation_history)
                if facts:
                    print(f"   Saved {len(facts)} new fact(s)")

            print("\n👋 Goodbye!")
            # Cleanup container on exit
            await self.sessions.destroy_session(self.chat_id)
            self.logger.log("session_end", chat_id=self.chat_id)
            return False

        if cmd == "/reset":
            await self._reset()
            return True

        if cmd == "/help":
            print(BANNER)
            return True

        return True  # Unknown command, continue

    async def run(self) -> None:
        """Run the interactive CLI."""
        print(BANNER)
        print(f"Session: {self.chat_id}\n")

        self._init_agent()

        try:
            while True:
                try:
                    user_input = input("you> ").strip()

                    if not user_input:
                        continue

                    # Handle special commands
                    if user_input.startswith("/") or user_input.lower() in ("exit", "quit"):
                        if not await self._handle_command(user_input):
                            break
                        continue

                    # Process through agent
                    await self._process_message(user_input)

                except KeyboardInterrupt:
                    print("\n\n⚡ Interrupted")
                    try:
                        confirm = input("Exit? (y/n): ").strip().lower()
                        if confirm in ("y", "yes"):
                            # Extract facts on interrupt exit
                            if self.agent and self._conversation_history:
                                print("📝 Extracting memories...")
                                facts = await self.agent.on_session_end(
                                    self._conversation_history
                                )
                                if facts:
                                    print(f"   Saved {len(facts)} new fact(s)")
                            print("👋 Goodbye!")
                            self.logger.log("session_interrupt", chat_id=self.chat_id)
                            break
                    except (KeyboardInterrupt, EOFError):
                        print("\n👋 Goodbye!")
                        break

                except EOFError:
                    print("\n👋 Goodbye!")
                    break
        finally:
            # Always cleanup container on exit
            await self.sessions.destroy_session(self.chat_id)
            # Close memory store
            self.memory_store.close()


async def run_cli() -> None:
    """Run the CLI with default configuration."""
    # Configure logging
    configure_logger()

    # Check for API key
    if not os.getenv("GROQ_API_KEY"):
        print("❌ Error: GROQ_API_KEY environment variable not set")
        print("Please set it in your .env file or environment")
        return

    # Create CLI with sandbox
    agent_config, sandbox_config = _config_from_env()
    sandbox = SandboxManager(sandbox_config)

    # Cleanup stale containers on startup
    stale_count = sandbox.cleanup_all()
    if stale_count > 0:
        print(f"🧹 Cleaned up {stale_count} stale container(s)")

    cli = CLI(config=agent_config, sandbox=sandbox)
    await cli.run()
