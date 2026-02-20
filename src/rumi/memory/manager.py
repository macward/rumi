"""Memory manager for orchestrating fact storage and retrieval."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .models import Fact
from .store import MemoryStore

if TYPE_CHECKING:
    from .extractor import FactExtractor


class MemoryManager:
    """Orchestrates memory operations: loading, formatting, and storage.

    This is the main interface for the memory system, coordinating
    between the store and other components.
    """

    def __init__(
        self,
        store: MemoryStore,
        extractor: FactExtractor | None = None,
    ) -> None:
        """Initialize the manager with a store and optional extractor.

        Args:
            store: The MemoryStore for persistence.
            extractor: Optional FactExtractor for automatic extraction.
        """
        self.store = store
        self.extractor = extractor

    def load_all(self) -> list[Fact]:
        """Load all facts from storage.

        Returns:
            List of all stored facts.
        """
        return self.store.get_all()

    def format_for_prompt(self, facts: list[Fact]) -> str:
        """Format facts as a block for injection into the system prompt.

        Args:
            facts: List of facts to format.

        Returns:
            XML-formatted memory block, or empty string if no facts.
        """
        if not facts:
            return ""

        lines = [f"- {fact.key}: {fact.value}" for fact in facts]
        content = "\n".join(lines)

        return f"""<memory>
Lo que sabés del usuario:
{content}
</memory>"""

    async def extract_from_conversation(
        self, messages: list[dict[str, Any]]
    ) -> list[Fact]:
        """Extract and save facts from a conversation.

        This method is called at session end to automatically extract
        facts from the conversation using the LLM.

        Args:
            messages: The conversation messages to analyze.

        Returns:
            List of newly extracted facts (empty if no extractor or no facts).
        """
        if not self.extractor:
            return []

        facts = await self.extractor.extract(messages)

        if facts:
            self.store.save_facts(facts)

        return facts
