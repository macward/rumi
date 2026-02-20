"""LLM client implementations for CodeSkills.

This module provides concrete implementations of the LLMClient Protocol,
allowing CodeSkills to access the LLM without depending on a specific provider.
"""

from typing import Any

from groq import AsyncGroq


class GroqLLMClient:
    """LLMClient implementation that wraps AsyncGroq.

    This wrapper allows CodeSkills to call the LLM without directly
    depending on Groq. It implements the LLMClient Protocol.

    Example:
        from groq import AsyncGroq
        from rumi.skills.llm_client import GroqLLMClient

        groq = AsyncGroq(api_key="...")
        llm = GroqLLMClient(groq, model="llama-3.1-70b-versatile")

        # Use in SkillContext
        ctx = SkillContext(tools=..., session=..., chat_id=..., llm=llm)
    """

    def __init__(
        self,
        client: AsyncGroq,
        model: str = "llama-3.1-70b-versatile",
    ) -> None:
        """Initialize the Groq LLM client wrapper.

        Args:
            client: The AsyncGroq client instance to wrap.
            model: The model to use for completions.
        """
        self._client = client
        self._model = model

    async def complete(self, prompt: str, system: str | None = None) -> str:
        """Complete a prompt and return the text response.

        Args:
            prompt: The user prompt to complete.
            system: Optional system prompt to set context.

        Returns:
            The LLM's text response.
        """
        messages: list[dict[str, Any]] = []

        if system:
            messages.append({"role": "system", "content": system})

        messages.append({"role": "user", "content": prompt})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
        )

        return response.choices[0].message.content or ""

    @property
    def model(self) -> str:
        """Return the model being used."""
        return self._model
