"""Telegram bot integration for Rumi."""

import logging
import os
import re
from pathlib import Path
from typing import Any

from groq import AsyncGroq
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..agent import AgentConfig, AgentLoop, StopReason
from ..logging import get_logger
from ..memory import FactExtractor, ForgetTool, MemoryManager, MemoryStore, RememberTool
from ..sandbox import SandboxConfig, SandboxManager
from ..session import SessionConfig, SessionManager
from ..skills import SkillExecutorTool, SkillManager
from ..tools import BashTool, ToolRegistry, WebFetchTool, WebSearchTool

MEMORY_DB_PATH = Path.home() / ".rumi" / "memory.db"


logger = logging.getLogger(__name__)


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


WELCOME_MESSAGE = """
🦀 *Rumi*

Soy un asistente que puede ejecutar comandos en un entorno seguro.

*Comandos disponibles:*
/start - Mostrar este mensaje
/reset - Reiniciar sesión (limpia historial y contenedor)
/stop - Cancelar operación en curso

*Notas:*
• Los comandos se ejecutan en un contenedor Docker aislado
• Sin acceso a red desde el contenedor
• Los archivos persisten en /workspace durante la sesión

Escríbeme lo que necesitas y te ayudaré.
"""

MAX_MESSAGE_LENGTH = 4096


def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    # Characters that need escaping in MarkdownV2
    special_chars = r"_*[]()~`>#+-=|{}.!"
    pattern = f"([{re.escape(special_chars)}])"
    return re.sub(pattern, r"\\\1", text)


def truncate_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> str:
    """Truncate message to fit Telegram limits."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 20] + "\n... [truncado]"


def format_response(response: str, stop_reason: StopReason, turns: int) -> str:
    """Format agent response for Telegram."""
    text = response

    if stop_reason == StopReason.MAX_TURNS:
        text += f"\n\n⚠️ Alcancé el máximo de turnos ({turns})"
    elif stop_reason == StopReason.REPEATED_CALL:
        text += "\n\n⚠️ Detecté un loop, me detuve"
    elif stop_reason == StopReason.CONSECUTIVE_ERRORS:
        text += "\n\n⚠️ Demasiados errores consecutivos"

    return truncate_message(text)


class TelegramBot:
    """Telegram bot for Rumi."""

    def __init__(
        self,
        token: str | None = None,
        agent_config: AgentConfig | None = None,
        sandbox_config: SandboxConfig | None = None,
        session_config: SessionConfig | None = None,
        memory_db_path: Path | None = None,
    ) -> None:
        self.token = token or os.getenv("TELEGRAM_TOKEN")
        if not self.token:
            raise ValueError("TELEGRAM_TOKEN not set")

        # Load config from env if not provided
        if agent_config is None or sandbox_config is None:
            env_agent, env_sandbox = _config_from_env()
            agent_config = agent_config or env_agent
            sandbox_config = sandbox_config or env_sandbox

        self.agent_config = agent_config
        self.sandbox = SandboxManager(sandbox_config)
        self.sessions = SessionManager(session_config, sandbox=self.sandbox)

        # Setup memory system
        db_path = memory_db_path or MEMORY_DB_PATH
        self.memory_store = MemoryStore(db_path)
        self.memory_store.init_db()

        # Create extractor with LLM client
        groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
        extractor = FactExtractor(groq_client, model=agent_config.model)
        self.memory_manager = MemoryManager(self.memory_store, extractor=extractor)

        # Create tool registry
        self.registry = ToolRegistry()
        self.registry.register(BashTool(self.sandbox))
        self.registry.register(WebFetchTool())
        # Register web search if Tavily API key is available
        if os.getenv("TAVILY_API_KEY"):
            try:
                self.registry.register(WebSearchTool())
            except ImportError:
                pass  # tavily-python not installed, skip
        # Register memory tools
        self.registry.register(RememberTool(self.memory_store))
        self.registry.register(ForgetTool(self.memory_store))

        # Initialize skill system
        self.skill_manager = SkillManager()
        self.skill_manager.discover()

        # Register skill executor tool
        skill_executor = SkillExecutorTool(self.skill_manager, tools=self.registry)
        self.registry.register(skill_executor)

        # Add available skills to agent config
        available_skills_block = self.skill_manager.get_available_skills_prompt()
        if available_skills_block:
            self.agent_config.available_skills_block = available_skills_block

        self.json_logger = get_logger()
        self._app: Application | None = None

    def _get_chat_id(self, update: Update) -> str:
        """Get chat_id as string from update."""
        assert update.effective_chat is not None
        return str(update.effective_chat.id)

    async def _handle_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command."""
        assert update.message is not None
        chat_id = self._get_chat_id(update)

        self.json_logger.log("telegram_start", chat_id=chat_id)

        await update.message.reply_text(
            WELCOME_MESSAGE,
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _handle_reset(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /reset command."""
        assert update.message is not None
        chat_id = self._get_chat_id(update)

        # Extract facts before reset
        messages = self.sessions.get_messages(chat_id, limit=100, for_llm=True)
        if messages:
            agent = AgentLoop(
                self.registry, self.agent_config, memory=self.memory_manager
            )
            facts = await agent.on_session_end(messages)
            if facts:
                await update.message.reply_text(
                    f"📝 Guardé {len(facts)} nuevo(s) hecho(s) en memoria."
                )

        await self.sessions.destroy_session(chat_id)

        self.json_logger.log("telegram_reset", chat_id=chat_id)

        await update.message.reply_text(
            "✨ Sesión reiniciada. Contenedor y historial limpiados."
        )

    async def _handle_stop(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /stop command."""
        assert update.message is not None
        chat_id = self._get_chat_id(update)

        # We can't really stop an in-progress LLM call, but we can release the lock
        if self.sessions.is_busy(chat_id):
            self.sessions.release(chat_id)
            await update.message.reply_text("⏹ Operación cancelada.")
        else:
            await update.message.reply_text("No hay operación en curso.")

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle incoming messages."""
        assert update.message is not None
        assert update.message.text is not None

        chat_id = self._get_chat_id(update)
        message = update.message.text

        # Try to acquire session
        acquired, error = await self.sessions.acquire(chat_id)
        if not acquired:
            await update.message.reply_text(error or "Ocupado")
            return

        try:
            # Log incoming message
            self.json_logger.log(
                "telegram_message",
                chat_id=chat_id,
                message_length=len(message),
            )
            self.sessions.add_message(chat_id, "user", message)

            # Get conversation history (exclude current message)
            all_messages = self.sessions.get_messages(chat_id, limit=20, for_llm=True)
            history = all_messages[:-1] or None

            # Send typing indicator
            await update.message.chat.send_action("typing")

            # Create agent with memory and run with history
            agent = AgentLoop(
                self.registry, self.agent_config, memory=self.memory_manager
            )
            result = await agent.run(message, chat_id=chat_id, history=history)

            # Log result
            self.json_logger.log_agent_stop(
                result.stop_reason.value,
                chat_id=chat_id,
                turns=result.turns,
            )
            self.sessions.add_message(chat_id, "assistant", result.response)

            # Format and send response
            response_text = format_response(
                result.response,
                result.stop_reason,
                result.turns,
            )

            await update.message.reply_text(response_text)

        except Exception as e:
            logger.exception("Error processing message")
            self.json_logger.log("telegram_error", chat_id=chat_id, error=str(e))
            await update.message.reply_text(f"❌ Error: {e}")

        finally:
            self.sessions.release(chat_id)

    async def _post_init(self, application: Application) -> None:
        """Called after Application.initialize()."""
        self.sessions.start_cleanup_task()

    async def _post_shutdown(self, application: Application) -> None:
        """Called after Application.shutdown()."""
        self.sessions.stop_cleanup_task()

    def build_app(self) -> Application:
        """Build the Telegram application."""
        self._app = (
            Application.builder()
            .token(self.token)
            .post_init(self._post_init)
            .post_shutdown(self._post_shutdown)
            .build()
        )

        # Add handlers
        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(CommandHandler("reset", self._handle_reset))
        self._app.add_handler(CommandHandler("stop", self._handle_stop))
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        return self._app

    async def start(self) -> None:
        """Start the bot."""
        app = self.build_app()

        # Start session cleanup task
        self.sessions.start_cleanup_task()

        logger.info("Starting Telegram bot...")
        await app.initialize()
        await app.start()
        await app.updater.start_polling()  # type: ignore

    async def stop(self) -> None:
        """Stop the bot."""
        self.sessions.stop_cleanup_task()

        if self._app:
            await self._app.updater.stop()  # type: ignore
            await self._app.stop()
            await self._app.shutdown()

        # Close memory store
        self.memory_store.close()

    def run(self) -> None:
        """Run the bot (blocking)."""
        # Cleanup stale containers on startup
        stale_count = self.sandbox.cleanup_all()
        if stale_count > 0:
            logger.info(f"Cleaned up {stale_count} stale container(s)")

        app = self.build_app()

        logger.info("Starting Telegram bot...")
        app.run_polling()


async def run_telegram_bot() -> None:
    """Run the Telegram bot."""
    from ..logging import configure_logger

    configure_logger()

    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("❌ Error: TELEGRAM_TOKEN environment variable not set")
        return

    bot = TelegramBot(token=token)
    await bot.start()

    try:
        # Keep running
        import asyncio
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await bot.stop()
