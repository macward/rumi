"""Agent loop implementation."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from groq import AsyncGroq

from ..conversation_logger import ConversationLogger, get_conversation_logger
from ..tools import ToolRegistry
from .prompt import build_system_prompt, format_tool_result

if TYPE_CHECKING:
    from ..memory import MemoryManager


class StopReason(Enum):
    """Reasons for stopping the agent loop."""

    COMPLETE = "complete"
    MAX_TURNS = "max_turns"
    REPEATED_CALL = "repeated_call"
    CONSECUTIVE_ERRORS = "consecutive_errors"


@dataclass
class AgentConfig:
    """Configuration for the agent loop."""

    model: str = "llama-3.1-70b-versatile"
    max_turns: int = 10
    max_consecutive_errors: int = 3
    max_repeated_calls: int = 2
    available_skills_block: str = ""


@dataclass
class AgentResult:
    """Result from running the agent loop."""

    response: str
    stop_reason: StopReason
    turns: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class AgentLoop:
    """Main agent loop: think → act → observe."""

    def __init__(
        self,
        registry: ToolRegistry,
        config: AgentConfig | None = None,
        groq_client: AsyncGroq | None = None,
        memory: MemoryManager | None = None,
        conversation_logger: ConversationLogger | None = None,
    ) -> None:
        self.registry = registry
        self.config = config or AgentConfig()
        self.client = groq_client or AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))
        self.memory = memory
        self.conv_logger = conversation_logger or get_conversation_logger()
        self._last_tool_call: str | None = None
        self._repeated_count: int = 0
        self._consecutive_errors: int = 0

    def _reset_state(self) -> None:
        """Reset loop state for a new run."""
        self._last_tool_call = None
        self._repeated_count = 0
        self._consecutive_errors = 0

    def _check_repeated_call(self, tool_call: dict[str, Any]) -> bool:
        """Check if this is a repeated tool call."""
        call_sig = json.dumps(tool_call, sort_keys=True)
        if call_sig == self._last_tool_call:
            self._repeated_count += 1
            return self._repeated_count >= self.config.max_repeated_calls
        self._last_tool_call = call_sig
        self._repeated_count = 1
        return False

    async def run(
        self,
        message: str,
        chat_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> AgentResult:
        """Run the agent loop for a user message.

        Args:
            message: The current user message.
            chat_id: Optional session identifier.
            history: Optional conversation history to inject between
                     system prompt and current message.

        Returns:
            AgentResult with response and metadata.
        """
        self._reset_state()

        # Load memory block if available
        memory_block = ""
        if self.memory:
            facts = self.memory.load_all()
            memory_block = self.memory.format_for_prompt(facts)

        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_system_prompt(
                    self.registry.get_tools_schema(),
                    self.config.available_skills_block,
                    memory_block,
                ),
            },
        ]

        if history:
            messages.extend(history)

        messages.append({"role": "user", "content": message})

        # Log user message
        if chat_id:
            self.conv_logger.log_user_message(chat_id, message)

        tool_calls_log: list[dict[str, Any]] = []
        final_response = ""

        for turn in range(self.config.max_turns):
            # Log LLM request
            if chat_id:
                self.conv_logger.log_llm_request(
                    chat_id,
                    model=self.config.model,
                    messages_count=len(messages),
                    has_tools=bool(self.registry.get_tools_schema()),
                )

            # Think: Call LLM
            response = await self.client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                tools=self.registry.get_tools_schema() or None,
                tool_choice="auto" if self.registry.get_tools_schema() else None,
            )

            assistant_message = response.choices[0].message

            # Log LLM response
            if chat_id:
                self.conv_logger.log_llm_response(
                    chat_id,
                    has_content=bool(assistant_message.content),
                    tool_calls_count=len(assistant_message.tool_calls or []),
                    finish_reason=response.choices[0].finish_reason,
                )

            # Check if LLM wants to call tools
            if assistant_message.tool_calls:
                # Only include fields accepted by Groq API (exclude 'annotations')
                msg_dict: dict[str, Any] = {
                    "role": assistant_message.role,
                    "content": assistant_message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in assistant_message.tool_calls
                    ],
                }
                messages.append(msg_dict)

                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        tool_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = {}

                    call_record = {"name": tool_name, "args": tool_args}
                    tool_calls_log.append(call_record)

                    # Log tool call
                    if chat_id:
                        self.conv_logger.log_tool_call(
                            chat_id,
                            tool_name=tool_name,
                            tool_args=tool_args,
                            tool_call_id=tool_call.id,
                        )

                    # Circuit breaker: repeated calls
                    if self._check_repeated_call(call_record):
                        return AgentResult(
                            response="Stopped: repeated tool call detected",
                            stop_reason=StopReason.REPEATED_CALL,
                            turns=turn + 1,
                            tool_calls=tool_calls_log,
                        )

                    # Act: Execute tool
                    start_time = time.time()
                    result = await self.registry.dispatch(tool_name, tool_args)
                    duration_ms = (time.time() - start_time) * 1000

                    # Log tool result
                    if chat_id:
                        self.conv_logger.log_tool_result(
                            chat_id,
                            tool_name=tool_name,
                            success=result.success,
                            output=result.output,
                            error=result.error,
                            tool_call_id=tool_call.id,
                            duration_ms=duration_ms,
                        )

                    # Track errors
                    if not result.success:
                        self._consecutive_errors += 1
                        if self._consecutive_errors >= self.config.max_consecutive_errors:
                            return AgentResult(
                                response=f"Stopped: {self.config.max_consecutive_errors} consecutive errors",
                                stop_reason=StopReason.CONSECUTIVE_ERRORS,
                                turns=turn + 1,
                                tool_calls=tool_calls_log,
                            )
                    else:
                        self._consecutive_errors = 0

                    # Observe: Add result to conversation
                    tool_response = format_tool_result(
                        tool_name, result.success, result.output, result.error
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_response,
                    })
            else:
                # No tool calls - LLM is done
                final_response = assistant_message.content or ""

                # Log assistant response and agent stop
                if chat_id:
                    self.conv_logger.log_assistant_message(chat_id, final_response)
                    self.conv_logger.log_agent_stop(
                        chat_id,
                        stop_reason=StopReason.COMPLETE.value,
                        turns=turn + 1,
                        tool_calls_total=len(tool_calls_log),
                    )

                return AgentResult(
                    response=final_response,
                    stop_reason=StopReason.COMPLETE,
                    turns=turn + 1,
                    tool_calls=tool_calls_log,
                )

        # Max turns reached
        if chat_id:
            self.conv_logger.log_agent_stop(
                chat_id,
                stop_reason=StopReason.MAX_TURNS.value,
                turns=self.config.max_turns,
                tool_calls_total=len(tool_calls_log),
            )

        return AgentResult(
            response=final_response or "Max turns reached",
            stop_reason=StopReason.MAX_TURNS,
            turns=self.config.max_turns,
            tool_calls=tool_calls_log,
        )

    async def on_session_end(self, messages: list[dict[str, Any]]) -> list[Any]:
        """Hook called when a session ends to extract and save facts.

        This should be called when:
        - CLI: user exits the REPL (Ctrl+C, 'exit', etc.)
        - Telegram: /reset command or session timeout

        Args:
            messages: The conversation messages to analyze.

        Returns:
            List of extracted facts (empty if no memory manager or no facts).
        """
        if not self.memory:
            return []

        return await self.memory.extract_from_conversation(messages)
