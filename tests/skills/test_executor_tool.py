"""Tests for SkillExecutorTool class."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from rumi.skills.executor_tool import SkillExecutorTool
from rumi.skills.manager import SkillManager, SkillsConfig


def create_skill_dir(base: Path, name: str, description: str, body: str = "") -> Path:
    """Helper to create a skill directory with SKILL.md."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True)
    content = f"""---
name: {name}
description: {description}
---

{body or f"Instructions for {name}"}
"""
    (skill_dir / "SKILL.md").write_text(content)
    return skill_dir


class TestSkillExecutorToolProperties:
    """Tests for SkillExecutorTool properties."""

    def test_name(self, tmp_path):
        """Tool name is 'use_skill'."""
        config = SkillsConfig(bundled_dir=tmp_path)
        manager = SkillManager(config)
        tool = SkillExecutorTool(manager)

        assert tool.name == "use_skill"

    def test_description(self, tmp_path):
        """Tool has descriptive description."""
        config = SkillsConfig(bundled_dir=tmp_path)
        manager = SkillManager(config)
        tool = SkillExecutorTool(manager)

        assert "skill" in tool.description.lower()
        assert "available_skills" in tool.description

    def test_parameters_schema(self, tmp_path):
        """Parameters schema is correct."""
        config = SkillsConfig(bundled_dir=tmp_path)
        manager = SkillManager(config)
        tool = SkillExecutorTool(manager)

        params = tool.parameters

        assert params["type"] == "object"
        assert "skill_name" in params["properties"]
        assert "skill_input" in params["properties"]
        assert params["required"] == ["skill_name"]

    def test_get_schema(self, tmp_path):
        """get_schema returns proper function schema."""
        config = SkillsConfig(bundled_dir=tmp_path)
        manager = SkillManager(config)
        tool = SkillExecutorTool(manager)

        schema = tool.get_schema()

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "use_skill"
        assert "parameters" in schema["function"]


class TestSkillExecutorToolExecution:
    """Tests for SkillExecutorTool.execute()."""

    @pytest.fixture
    def manager_with_skill(self, tmp_path) -> SkillManager:
        """Create manager with test skill."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "summarize", "Summarize documents", "Follow these steps to summarize...")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()
        return manager

    @pytest.mark.asyncio
    async def test_execute_success(self, manager_with_skill):
        """Execute skill successfully."""
        tool = SkillExecutorTool(manager_with_skill)

        result = await tool.execute(skill_name="summarize", chat_id="test-123")

        assert result.success is True
        assert "Follow these steps to summarize" in result.output
        assert result.metadata is not None
        assert result.metadata["skill_name"] == "summarize"

    @pytest.mark.asyncio
    async def test_execute_with_input(self, manager_with_skill):
        """Execute skill with input context."""
        tool = SkillExecutorTool(manager_with_skill)

        result = await tool.execute(
            skill_name="summarize",
            skill_input="Please summarize the README.md file",
            chat_id="test-123",
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_missing_skill_name(self, manager_with_skill):
        """Execute without skill_name returns error."""
        tool = SkillExecutorTool(manager_with_skill)

        result = await tool.execute(skill_name=None, chat_id="test")

        assert result.success is False
        assert "skill_name" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_nonexistent_skill(self, manager_with_skill):
        """Execute nonexistent skill returns error."""
        tool = SkillExecutorTool(manager_with_skill)

        result = await tool.execute(skill_name="nonexistent", chat_id="test")

        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_disabled_skill(self, tmp_path):
        """Execute disabled skill returns error."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        skill_dir = bundled / "disabled_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: disabled_skill
description: A disabled skill
enabled: false
---

Body.
""")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        tool = SkillExecutorTool(manager)
        result = await tool.execute(skill_name="disabled_skill", chat_id="test")

        assert result.success is False
        assert "disabled" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_with_tools_registry(self, manager_with_skill):
        """Execute with ToolRegistry in context."""
        mock_registry = MagicMock()
        tool = SkillExecutorTool(manager_with_skill, tools=mock_registry)

        result = await tool.execute(skill_name="summarize", chat_id="test")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_with_session(self, manager_with_skill):
        """Execute with session state."""
        from rumi.session.manager import SessionState

        session = SessionState(chat_id="test-session")
        tool = SkillExecutorTool(manager_with_skill)

        result = await tool.execute(
            skill_name="summarize",
            chat_id="test-session",
            session=session,
        )

        assert result.success is True


class TestSkillExecutorToolValidation:
    """Tests for argument validation."""

    @pytest.mark.asyncio
    async def test_validate_args_valid(self, tmp_path):
        """Valid arguments pass validation."""
        config = SkillsConfig(bundled_dir=tmp_path)
        manager = SkillManager(config)
        tool = SkillExecutorTool(manager)

        valid, error = tool.validate_args({"skill_name": "test"})
        assert valid is True
        assert error is None

    @pytest.mark.asyncio
    async def test_validate_args_with_input(self, tmp_path):
        """Arguments with input pass validation."""
        config = SkillsConfig(bundled_dir=tmp_path)
        manager = SkillManager(config)
        tool = SkillExecutorTool(manager)

        valid, error = tool.validate_args({"skill_name": "test", "skill_input": "context"})
        assert valid is True

    @pytest.mark.asyncio
    async def test_validate_args_missing_required(self, tmp_path):
        """Missing required argument fails validation."""
        config = SkillsConfig(bundled_dir=tmp_path)
        manager = SkillManager(config)
        tool = SkillExecutorTool(manager)

        valid, error = tool.validate_args({})
        assert valid is False
        assert "skill_name" in error


class TestSkillExecutorToolIntegration:
    """Integration tests with SkillManager."""

    def test_skill_manager_property(self, tmp_path):
        """Can access skill_manager property."""
        config = SkillsConfig(bundled_dir=tmp_path)
        manager = SkillManager(config)
        tool = SkillExecutorTool(manager)

        assert tool.skill_manager is manager

    @pytest.mark.asyncio
    async def test_multiple_skills(self, tmp_path):
        """Execute different skills."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "skill_a", "First skill", "Do A")
        create_skill_dir(bundled, "skill_b", "Second skill", "Do B")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        tool = SkillExecutorTool(manager)

        result_a = await tool.execute(skill_name="skill_a", chat_id="test")
        result_b = await tool.execute(skill_name="skill_b", chat_id="test")

        assert result_a.success is True
        assert "Do A" in result_a.output

        assert result_b.success is True
        assert "Do B" in result_b.output
