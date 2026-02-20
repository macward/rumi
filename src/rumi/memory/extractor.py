"""Fact extraction from conversations using LLM."""

import json
import logging
from typing import Any

from groq import AsyncGroq

from .models import Fact

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """Analiza esta conversación y extrae hechos estables sobre el usuario que valga la pena recordar para futuras conversaciones.

Retorna SOLO JSON válido:
{
  "facts": [
    {"key": "<categoría>", "value": "<hecho en tercera persona>"},
    ...
  ]
}

Reglas:
- Solo hechos ESTABLES (no estados temporales como "está cansado")
- Values en TERCERA PERSONA ("trabaja en Google", no "trabajo en Google")
- Keys descriptivas y en español: nombre, trabajo, ubicacion, hobby, proyecto, preferencia, tecnologia, idioma, etc.
- NO hay lista fija de keys — usá la que mejor describa el hecho
- Si no hay hechos nuevos, retorna {"facts": []}
- No extraigas preguntas ni hipótesis como hechos

Ejemplos de keys válidas:
  nombre, edad, trabajo, ubicacion, hobby, mascota, familia,
  proyecto_actual, stack_tecnologico, preferencia_editor,
  idioma, zona_horaria, objetivo, rutina, ...

Conversación a analizar:
"""


class FactExtractor:
    """Extracts facts from conversations using LLM."""

    def __init__(
        self,
        llm_client: AsyncGroq,
        model: str = "llama-3.1-70b-versatile",
    ) -> None:
        """Initialize the extractor.

        Args:
            llm_client: The Groq client for LLM calls.
            model: The model to use for extraction.
        """
        self.client = llm_client
        self.model = model

    async def extract(self, messages: list[dict[str, Any]]) -> list[Fact]:
        """Extract facts from a conversation.

        Args:
            messages: The conversation messages to analyze.

        Returns:
            List of extracted facts, empty if none found or on error.
        """
        if not messages:
            return []

        # Format conversation for the prompt
        conversation_text = self._format_conversation(messages)
        full_prompt = EXTRACTION_PROMPT + conversation_text

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": full_prompt}],
                temperature=0.1,  # Low temperature for consistent extraction
            )

            content = response.choices[0].message.content or ""
            return self._parse_response(content)

        except Exception as e:
            logger.warning(f"Fact extraction failed: {e}")
            return []

    def _format_conversation(self, messages: list[dict[str, Any]]) -> str:
        """Format messages into a readable conversation string."""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if role == "user":
                lines.append(f"Usuario: {content}")
            elif role == "assistant":
                lines.append(f"Asistente: {content}")
            # Skip system and tool messages
        return "\n".join(lines)

    def _parse_response(self, content: str) -> list[Fact]:
        """Parse LLM response into facts.

        Args:
            content: The raw LLM response.

        Returns:
            List of facts, empty on parse error.
        """
        try:
            # Try to extract JSON from the response
            # The LLM might wrap it in markdown code blocks
            json_str = content.strip()
            if json_str.startswith("```"):
                # Remove markdown code block
                lines = json_str.split("\n")
                json_lines = []
                in_block = False
                for line in lines:
                    if line.startswith("```"):
                        in_block = not in_block
                        continue
                    if in_block or not line.startswith("```"):
                        json_lines.append(line)
                json_str = "\n".join(json_lines)

            data = json.loads(json_str)

            if not isinstance(data, dict) or "facts" not in data:
                logger.warning("Invalid response structure: missing 'facts' key")
                return []

            facts = []
            for item in data["facts"]:
                if isinstance(item, dict) and "key" in item and "value" in item:
                    facts.append(
                        Fact(
                            key=str(item["key"]),
                            value=str(item["value"]),
                            source="auto",
                        )
                    )
                else:
                    logger.warning(f"Skipping invalid fact item: {item}")

            return facts

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse extraction response: {e}")
            return []
        except Exception as e:
            logger.warning(f"Unexpected error parsing response: {e}")
            return []
