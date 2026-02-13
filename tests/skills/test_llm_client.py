"""Tests for LLMClient implementations."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from miniclaw.skills import GroqLLMClient, LLMClient


class TestGroqLLMClient:
    """Tests for GroqLLMClient wrapper."""

    def test_implements_llm_client_protocol(self) -> None:
        """GroqLLMClient should implement the LLMClient Protocol."""
        mock_groq = MagicMock()
        client = GroqLLMClient(mock_groq)

        # Check that it has the required method
        assert hasattr(client, "complete")
        assert callable(client.complete)

    def test_stores_model(self) -> None:
        """Should store the model name."""
        mock_groq = MagicMock()
        client = GroqLLMClient(mock_groq, model="test-model")

        assert client.model == "test-model"

    def test_default_model(self) -> None:
        """Should use default model if not specified."""
        mock_groq = MagicMock()
        client = GroqLLMClient(mock_groq)

        assert client.model == "llama-3.1-70b-versatile"

    @pytest.mark.asyncio
    async def test_complete_with_prompt_only(self) -> None:
        """Should call Groq with just user prompt."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "LLM response"

        mock_groq = MagicMock()
        mock_groq.chat.completions.create = AsyncMock(return_value=mock_response)

        client = GroqLLMClient(mock_groq, model="test-model")
        result = await client.complete("Hello")

        assert result == "LLM response"
        mock_groq.chat.completions.create.assert_called_once_with(
            model="test-model",
            messages=[{"role": "user", "content": "Hello"}],
        )

    @pytest.mark.asyncio
    async def test_complete_with_system_prompt(self) -> None:
        """Should include system prompt when provided."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response with system"

        mock_groq = MagicMock()
        mock_groq.chat.completions.create = AsyncMock(return_value=mock_response)

        client = GroqLLMClient(mock_groq)
        result = await client.complete("User message", system="You are a helper")

        assert result == "Response with system"
        mock_groq.chat.completions.create.assert_called_once()

        # Verify messages include system and user
        call_kwargs = mock_groq.chat.completions.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0] == {"role": "system", "content": "You are a helper"}
        assert messages[1] == {"role": "user", "content": "User message"}

    @pytest.mark.asyncio
    async def test_complete_returns_empty_on_none_content(self) -> None:
        """Should return empty string if content is None."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None

        mock_groq = MagicMock()
        mock_groq.chat.completions.create = AsyncMock(return_value=mock_response)

        client = GroqLLMClient(mock_groq)
        result = await client.complete("Hello")

        assert result == ""


class TestLLMClientProtocol:
    """Tests that verify LLMClient Protocol compliance."""

    def test_mock_llm_client_works_with_type_hints(self) -> None:
        """A mock LLMClient should satisfy the Protocol type."""

        class MockLLMClient:
            async def complete(self, prompt: str, system: str | None = None) -> str:
                return f"Mock response to: {prompt}"

        # This should work without type errors
        client: LLMClient = MockLLMClient()
        assert hasattr(client, "complete")

    @pytest.mark.asyncio
    async def test_mock_llm_can_be_used_in_place_of_real_client(self) -> None:
        """A mock should be usable wherever LLMClient is expected."""

        class MockLLMClient:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str | None]] = []

            async def complete(self, prompt: str, system: str | None = None) -> str:
                self.calls.append((prompt, system))
                return f"Mocked: {prompt}"

        mock = MockLLMClient()

        # Use it like an LLMClient
        result = await mock.complete("Test prompt", system="System")

        assert result == "Mocked: Test prompt"
        assert mock.calls == [("Test prompt", "System")]


class TestSkillExecutorToolWithLLM:
    """Tests for SkillExecutorTool with LLM integration."""

    @pytest.mark.asyncio
    async def test_executor_passes_llm_to_context(self) -> None:
        """SkillExecutorTool should pass LLM to SkillContext."""
        from pathlib import Path
        from miniclaw.skills import SkillManager, SkillsConfig, SkillExecutorTool

        # Create a mock LLM
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(return_value="LLM response")

        # Create a CodeSkill that uses LLM
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "skills" / "llm_skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: llm_skill\ndescription: Uses LLM\n---\n"
            )
            (skill_dir / "skill.py").write_text(
                '''
from miniclaw.skills import CodeSkill, SkillContext, SkillResult

class LLMSkill(CodeSkill):
    async def execute(self, ctx: SkillContext) -> SkillResult:
        if ctx.llm is None:
            return SkillResult(success=False, output="", error="No LLM")
        response = await ctx.llm.complete("Hello")
        return SkillResult(success=True, output=response)
'''
            )

            config = SkillsConfig(bundled_dir=Path(tmp) / "skills", user_dir=None)
            manager = SkillManager(config)
            manager.discover()

            # Create executor WITH LLM
            executor = SkillExecutorTool(manager, llm=mock_llm)

            result = await executor.execute(
                skill_name="llm_skill", chat_id="test-123"
            )

            assert result.success is True
            assert result.output == "LLM response"
            mock_llm.complete.assert_called_once_with("Hello")

    @pytest.mark.asyncio
    async def test_executor_without_llm_passes_none(self) -> None:
        """SkillExecutorTool without LLM should pass None to context."""
        from pathlib import Path
        from miniclaw.skills import SkillManager, SkillsConfig, SkillExecutorTool

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "skills" / "check_llm"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: check_llm\ndescription: Checks LLM\n---\n"
            )
            (skill_dir / "skill.py").write_text(
                '''
from miniclaw.skills import CodeSkill, SkillContext, SkillResult

class CheckLLMSkill(CodeSkill):
    async def execute(self, ctx: SkillContext) -> SkillResult:
        has_llm = ctx.llm is not None
        return SkillResult(success=True, output=f"has_llm={has_llm}")
'''
            )

            config = SkillsConfig(bundled_dir=Path(tmp) / "skills", user_dir=None)
            manager = SkillManager(config)
            manager.discover()

            # Create executor WITHOUT LLM
            executor = SkillExecutorTool(manager)

            result = await executor.execute(
                skill_name="check_llm", chat_id="test-123"
            )

            assert result.success is True
            assert result.output == "has_llm=False"
