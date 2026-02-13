"""Tests for skills base interfaces."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from miniclaw.skills.base import (
    LLMClient,
    Skill,
    SkillContext,
    SkillMetadata,
    SkillResult,
    SkillSource,
)


class TestSkillSource:
    """Tests for SkillSource enum."""

    def test_values(self):
        """Verify all expected values exist."""
        assert SkillSource.BUNDLED.value == "bundled"
        assert SkillSource.USER.value == "user"
        assert SkillSource.WORKSPACE.value == "workspace"

    def test_priority_ordering(self):
        """Workspace > User > Bundled."""
        assert SkillSource.WORKSPACE.priority > SkillSource.USER.priority
        assert SkillSource.USER.priority > SkillSource.BUNDLED.priority

    def test_all_sources_have_priority(self):
        """Every source has a defined priority."""
        for source in SkillSource:
            assert isinstance(source.priority, int)


class TestSkillMetadata:
    """Tests for SkillMetadata dataclass."""

    def test_minimal_creation(self):
        """Create with only required fields."""
        meta = SkillMetadata(name="test", description="A test skill")
        assert meta.name == "test"
        assert meta.description == "A test skill"
        assert meta.version == "0.1.0"
        assert meta.tags == []
        assert meta.tools_required == []
        assert meta.enabled is True
        assert meta.source == SkillSource.BUNDLED
        assert meta.path is None

    def test_full_creation(self):
        """Create with all fields specified."""
        path = Path("/skills/test")
        meta = SkillMetadata(
            name="summarize",
            description="Summarize documents",
            version="1.2.0",
            tags=["text", "productivity"],
            tools_required=["bash"],
            enabled=False,
            source=SkillSource.USER,
            path=path,
        )
        assert meta.name == "summarize"
        assert meta.version == "1.2.0"
        assert meta.tags == ["text", "productivity"]
        assert meta.tools_required == ["bash"]
        assert meta.enabled is False
        assert meta.source == SkillSource.USER
        assert meta.path == path

    def test_matches_keywords_name_match(self):
        """Name match gives high score."""
        meta = SkillMetadata(name="summarize", description="Process documents")
        score = meta.matches_keywords("please summarize this file")
        assert score >= 0.5

    def test_matches_keywords_description_match(self):
        """Description word matches contribute."""
        meta = SkillMetadata(name="doc_processor", description="summarize documents")
        score = meta.matches_keywords("summarize documents please")
        assert 0.0 < score < 1.0

    def test_matches_keywords_tag_match(self):
        """Tag match adds score."""
        meta = SkillMetadata(
            name="myskill",
            description="do something",
            tags=["productivity"],
        )
        score = meta.matches_keywords("productivity tool")
        assert score > 0.0

    def test_matches_keywords_no_match(self):
        """No matches returns low score."""
        meta = SkillMetadata(name="summarize", description="Extract key points")
        score = meta.matches_keywords("send an email")
        assert score == 0.0

    def test_matches_keywords_case_insensitive(self):
        """Matching is case insensitive."""
        meta = SkillMetadata(name="Summarize", description="Documents")
        score = meta.matches_keywords("SUMMARIZE this")
        assert score >= 0.5

    def test_matches_keywords_max_score(self):
        """Score is capped at 1.0."""
        meta = SkillMetadata(
            name="summarize",
            description="summarize documents",
            tags=["summarize"],
        )
        score = meta.matches_keywords("summarize summarize summarize")
        assert score <= 1.0


class TestSkillResult:
    """Tests for SkillResult dataclass."""

    def test_success_result(self):
        """Create successful result."""
        result = SkillResult(success=True, output="Done!")
        assert result.success is True
        assert result.output == "Done!"
        assert result.error is None
        assert result.metadata is None
        assert result.prompt_injection is None

    def test_error_result(self):
        """Create error result."""
        result = SkillResult(
            success=False,
            output="",
            error="Something went wrong",
        )
        assert result.success is False
        assert result.error == "Something went wrong"

    def test_result_with_metadata(self):
        """Result can include metadata."""
        result = SkillResult(
            success=True,
            output="Summary here",
            metadata={"word_count": 150, "sections": 3},
        )
        assert result.metadata == {"word_count": 150, "sections": 3}

    def test_result_with_prompt_injection(self):
        """CodeSkill can add prompt injection."""
        result = SkillResult(
            success=True,
            output="Analysis complete",
            prompt_injection="Remember to format as markdown",
        )
        assert result.prompt_injection == "Remember to format as markdown"


class TestSkillContext:
    """Tests for SkillContext dataclass."""

    def test_minimal_context(self):
        """Create with required fields only."""
        tools = MagicMock()
        session = MagicMock()

        ctx = SkillContext(
            tools=tools,
            session=session,
            chat_id="user123",
            user_message="Hello",
        )

        assert ctx.tools is tools
        assert ctx.session is session
        assert ctx.chat_id == "user123"
        assert ctx.user_message == "Hello"
        assert ctx.llm is None
        assert ctx.config == {}

    def test_empty_chat_id_rejected(self):
        """Empty chat_id raises ValueError."""
        with pytest.raises(ValueError, match="chat_id cannot be empty"):
            SkillContext(
                tools=MagicMock(),
                session=MagicMock(),
                chat_id="",
                user_message="Hello",
            )

    def test_whitespace_chat_id_rejected(self):
        """Whitespace-only chat_id raises ValueError."""
        with pytest.raises(ValueError, match="chat_id cannot be empty"):
            SkillContext(
                tools=MagicMock(),
                session=MagicMock(),
                chat_id="   ",
                user_message="Hello",
            )

    def test_full_context(self):
        """Create with all fields."""
        tools = MagicMock()
        session = MagicMock()
        llm = MagicMock(spec=LLMClient)
        config = {"max_words": 500}

        ctx = SkillContext(
            tools=tools,
            session=session,
            chat_id="user456",
            user_message="Summarize this",
            llm=llm,
            config=config,
        )

        assert ctx.llm is llm
        assert ctx.config == {"max_words": 500}


class TestSkillABC:
    """Tests for Skill abstract base class."""

    def test_cannot_instantiate_directly(self):
        """Skill is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            Skill()

    def test_concrete_skill_implementation(self):
        """Can create concrete skill subclass."""

        class TestSkill(Skill):
            def __init__(self):
                self._metadata = SkillMetadata(
                    name="test_skill",
                    description="A test skill",
                )

            @property
            def metadata(self) -> SkillMetadata:
                return self._metadata

            async def execute(self, ctx: SkillContext) -> SkillResult:
                return SkillResult(success=True, output="Executed!")

        skill = TestSkill()
        assert skill.name == "test_skill"
        assert skill.description == "A test skill"
        assert skill.enabled is True

    @pytest.mark.asyncio
    async def test_concrete_skill_execute(self):
        """Concrete skill can be executed."""

        class EchoSkill(Skill):
            def __init__(self):
                self._metadata = SkillMetadata(name="echo", description="Echo input")

            @property
            def metadata(self) -> SkillMetadata:
                return self._metadata

            async def execute(self, ctx: SkillContext) -> SkillResult:
                return SkillResult(
                    success=True,
                    output=f"Echo: {ctx.user_message}",
                )

        skill = EchoSkill()
        ctx = SkillContext(
            tools=MagicMock(),
            session=MagicMock(),
            chat_id="test",
            user_message="Hello World",
        )

        result = await skill.execute(ctx)
        assert result.success is True
        assert result.output == "Echo: Hello World"

    def test_can_handle_default_implementation(self):
        """Default can_handle uses keyword matching."""

        class MySkill(Skill):
            def __init__(self):
                self._metadata = SkillMetadata(
                    name="summarize",
                    description="Summarize documents",
                    tags=["text"],
                )

            @property
            def metadata(self) -> SkillMetadata:
                return self._metadata

            async def execute(self, ctx: SkillContext) -> SkillResult:
                return SkillResult(success=True, output="")

        skill = MySkill()

        # Should match well
        assert skill.can_handle("summarize this") >= 0.5

        # Should not match
        assert skill.can_handle("send email") == 0.0

    def test_can_handle_override(self):
        """CodeSkill can override can_handle."""

        class SmartSkill(Skill):
            def __init__(self):
                self._metadata = SkillMetadata(
                    name="smart",
                    description="Does smart things",
                )

            @property
            def metadata(self) -> SkillMetadata:
                return self._metadata

            async def execute(self, ctx: SkillContext) -> SkillResult:
                return SkillResult(success=True, output="")

            def can_handle(self, query: str) -> float:
                # Custom logic: always return 0.8 for testing
                return 0.8

        skill = SmartSkill()
        assert skill.can_handle("anything") == 0.8

    def test_disabled_skill(self):
        """Skill can be disabled via metadata."""

        class DisabledSkill(Skill):
            def __init__(self):
                self._metadata = SkillMetadata(
                    name="disabled",
                    description="This is disabled",
                    enabled=False,
                )

            @property
            def metadata(self) -> SkillMetadata:
                return self._metadata

            async def execute(self, ctx: SkillContext) -> SkillResult:
                return SkillResult(success=True, output="")

        skill = DisabledSkill()
        assert skill.enabled is False


class TestLLMClientProtocol:
    """Tests for LLMClient protocol."""

    @pytest.mark.asyncio
    async def test_mock_llm_client(self):
        """Can create mock that satisfies protocol."""
        mock_llm = AsyncMock(spec=LLMClient)
        mock_llm.complete.return_value = "Response from LLM"

        result = await mock_llm.complete("Hello", system="Be helpful")
        assert result == "Response from LLM"
        mock_llm.complete.assert_called_once_with("Hello", system="Be helpful")

    @pytest.mark.asyncio
    async def test_concrete_llm_implementation(self):
        """Can create concrete LLM client."""

        class MockLLM:
            async def complete(self, prompt: str, system: str | None = None) -> str:
                return f"Processed: {prompt}"

        llm = MockLLM()
        result = await llm.complete("Test prompt")
        assert result == "Processed: Test prompt"
