"""Memory manager for orchestrating fact storage and retrieval."""

from .models import Fact
from .store import MemoryStore


class MemoryManager:
    """Orchestrates memory operations: loading, formatting, and storage.

    This is the main interface for the memory system, coordinating
    between the store and other components.
    """

    def __init__(self, store: MemoryStore) -> None:
        """Initialize the manager with a store.

        Args:
            store: The MemoryStore for persistence.
        """
        self.store = store

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
