"""Tests for CodeSkill loading and execution."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from rumi.skills import (
    CodeSkill,
    CodeSkillLoadError,
    SkillContext,
    SkillMetadata,
    SkillResult,
    SkillSource,
    is_code_skill,
    load_code_skill,
)


class TestIsCodeSkill:
    """Tests for is_code_skill detection."""

    def test_returns_true_when_skill_py_exists(self, tmp_path: Path) -> None:
        """Should return True if skill.py exists."""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "skill.py").write_text("# code")
        (skill_dir / "SKILL.md").write_text("---\nname: test\n---\n")

        assert is_code_skill(skill_dir) is True

    def test_returns_false_when_only_skill_md(self, tmp_path: Path) -> None:
        """Should return False if only SKILL.md exists."""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: test\n---\n")

        assert is_code_skill(skill_dir) is False

    def test_returns_false_for_empty_dir(self, tmp_path: Path) -> None:
        """Should return False for empty directory."""
        skill_dir = tmp_path / "empty"
        skill_dir.mkdir()

        assert is_code_skill(skill_dir) is False


class TestLoadCodeSkill:
    """Tests for load_code_skill function."""

    def test_loads_valid_code_skill(self, tmp_path: Path) -> None:
        """Should load a valid CodeSkill from skill.py."""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()

        # Create SKILL.md
        (skill_dir / "SKILL.md").write_text(
            """---
name: test_skill
description: A test skill
version: 1.0.0
tags: [test]
---

# Test Skill Instructions
"""
        )

        # Create skill.py with a valid CodeSkill
        (skill_dir / "skill.py").write_text(
            '''
from rumi.skills import CodeSkill, SkillContext, SkillResult

class TestSkill(CodeSkill):
    async def execute(self, ctx: SkillContext) -> SkillResult:
        return SkillResult(success=True, output="test output")
'''
        )

        skill = load_code_skill(skill_dir, source=SkillSource.USER)

        assert isinstance(skill, CodeSkill)
        assert skill.name == "test_skill"
        assert skill.description == "A test skill"
        assert skill.metadata.version == "1.0.0"
        assert skill.metadata.source == SkillSource.USER
        assert "Test Skill Instructions" in skill.instructions

    def test_raises_error_when_no_skill_py(self, tmp_path: Path) -> None:
        """Should raise CodeSkillLoadError if skill.py is missing."""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: test\n---\n")

        with pytest.raises(CodeSkillLoadError, match="No skill.py found"):
            load_code_skill(skill_dir)

    def test_raises_error_when_no_skill_md(self, tmp_path: Path) -> None:
        """Should raise CodeSkillLoadError if SKILL.md is missing."""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "skill.py").write_text("# code")

        with pytest.raises(CodeSkillLoadError, match="requires SKILL.md"):
            load_code_skill(skill_dir)

    def test_raises_error_when_no_codeskill_class(self, tmp_path: Path) -> None:
        """Should raise error if skill.py has no CodeSkill subclass."""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n"
        )
        (skill_dir / "skill.py").write_text(
            """
class NotASkill:
    pass
"""
        )

        with pytest.raises(CodeSkillLoadError, match="No CodeSkill subclass found"):
            load_code_skill(skill_dir)

    def test_raises_error_when_multiple_codeskill_classes(
        self, tmp_path: Path
    ) -> None:
        """Should raise error if skill.py has multiple CodeSkill subclasses."""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n"
        )
        (skill_dir / "skill.py").write_text(
            '''
from rumi.skills import CodeSkill, SkillContext, SkillResult

class SkillOne(CodeSkill):
    async def execute(self, ctx: SkillContext) -> SkillResult:
        return SkillResult(success=True, output="one")

class SkillTwo(CodeSkill):
    async def execute(self, ctx: SkillContext) -> SkillResult:
        return SkillResult(success=True, output="two")
'''
        )

        with pytest.raises(CodeSkillLoadError, match="Multiple CodeSkill subclasses"):
            load_code_skill(skill_dir)

    def test_raises_error_when_class_not_subclass(self, tmp_path: Path) -> None:
        """Should raise error if class doesn't properly extend CodeSkill."""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n"
        )
        # Define a class that looks like CodeSkill but isn't
        (skill_dir / "skill.py").write_text(
            """
class CodeSkill:  # Shadow the real CodeSkill
    pass

class MySkill(CodeSkill):
    pass
"""
        )

        with pytest.raises(CodeSkillLoadError, match="No CodeSkill subclass found"):
            load_code_skill(skill_dir)

    def test_raises_error_on_syntax_error(self, tmp_path: Path) -> None:
        """Should raise error if skill.py has syntax errors."""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n"
        )
        (skill_dir / "skill.py").write_text("def broken(")

        with pytest.raises(CodeSkillLoadError, match="Error executing"):
            load_code_skill(skill_dir)


class TestCodeSkillExecution:
    """Tests for CodeSkill execute method."""

    @pytest.mark.asyncio
    async def test_execute_returns_skill_result(self, tmp_path: Path) -> None:
        """Should execute and return SkillResult."""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: exec_test\ndescription: test\n---\n"
        )
        (skill_dir / "skill.py").write_text(
            '''
from rumi.skills import CodeSkill, SkillContext, SkillResult

class ExecSkill(CodeSkill):
    async def execute(self, ctx: SkillContext) -> SkillResult:
        return SkillResult(
            success=True,
            output=f"Hello, {ctx.user_message}",
            metadata={"processed": True}
        )
'''
        )

        skill = load_code_skill(skill_dir)

        # Create mock context
        ctx = SkillContext(
            tools=MagicMock(),
            session=MagicMock(),
            chat_id="test-123",
            user_message="world",
        )

        result = await skill.execute(ctx)

        assert result.success is True
        assert result.output == "Hello, world"
        assert result.metadata == {"processed": True}

    @pytest.mark.asyncio
    async def test_execute_can_use_tools(self, tmp_path: Path) -> None:
        """Should be able to call tools via ctx.tools."""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: tool_test\ndescription: test\n---\n"
        )
        (skill_dir / "skill.py").write_text(
            '''
from rumi.skills import CodeSkill, SkillContext, SkillResult

class ToolSkill(CodeSkill):
    async def execute(self, ctx: SkillContext) -> SkillResult:
        tool_result = await ctx.tools.dispatch("bash", {"command": "echo hi"})
        return SkillResult(success=True, output=tool_result.output)
'''
        )

        skill = load_code_skill(skill_dir)

        # Mock tool dispatch
        mock_tools = MagicMock()
        mock_tool_result = MagicMock()
        mock_tool_result.output = "hi"
        mock_tools.dispatch = AsyncMock(return_value=mock_tool_result)

        ctx = SkillContext(
            tools=mock_tools,
            session=MagicMock(),
            chat_id="test-123",
            user_message="",
        )

        result = await skill.execute(ctx)

        assert result.success is True
        assert result.output == "hi"
        mock_tools.dispatch.assert_called_once_with("bash", {"command": "echo hi"})

    @pytest.mark.asyncio
    async def test_execute_can_use_llm(self, tmp_path: Path) -> None:
        """Should be able to call LLM via ctx.llm."""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: llm_test\ndescription: test\n---\n"
        )
        (skill_dir / "skill.py").write_text(
            '''
from rumi.skills import CodeSkill, SkillContext, SkillResult

class LLMSkill(CodeSkill):
    async def execute(self, ctx: SkillContext) -> SkillResult:
        if ctx.llm is None:
            return SkillResult(success=False, output="", error="No LLM available")
        response = await ctx.llm.complete("Hello")
        return SkillResult(success=True, output=response)
'''
        )

        skill = load_code_skill(skill_dir)

        # Mock LLM
        mock_llm = MagicMock()
        mock_llm.complete = AsyncMock(return_value="LLM response")

        ctx = SkillContext(
            tools=MagicMock(),
            session=MagicMock(),
            chat_id="test-123",
            user_message="",
            llm=mock_llm,
        )

        result = await skill.execute(ctx)

        assert result.success is True
        assert result.output == "LLM response"
        mock_llm.complete.assert_called_once_with("Hello")


class TestCodeSkillRepr:
    """Tests for CodeSkill string representation."""

    def test_repr(self, tmp_path: Path) -> None:
        """Should return readable repr."""
        skill_dir = tmp_path / "my_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: repr_test\ndescription: test\n---\n"
        )
        (skill_dir / "skill.py").write_text(
            '''
from rumi.skills import CodeSkill, SkillContext, SkillResult

class ReprSkill(CodeSkill):
    async def execute(self, ctx: SkillContext) -> SkillResult:
        return SkillResult(success=True, output="")
'''
        )

        skill = load_code_skill(skill_dir, source=SkillSource.WORKSPACE)

        assert repr(skill) == "CodeSkill(name='repr_test', source=workspace)"


class TestSkillManagerWithCodeSkills:
    """Tests for SkillManager integration with CodeSkills."""

    def test_manager_loads_code_skill(self, tmp_path: Path) -> None:
        """SkillManager should detect and load CodeSkills from skill.py."""
        from rumi.skills import SkillManager, SkillsConfig

        # Create a CodeSkill
        skill_dir = tmp_path / "skills" / "code_skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my_code_skill\ndescription: A code skill\n---\n"
        )
        (skill_dir / "skill.py").write_text(
            '''
from rumi.skills import CodeSkill, SkillContext, SkillResult

class MyCodeSkill(CodeSkill):
    async def execute(self, ctx: SkillContext) -> SkillResult:
        return SkillResult(success=True, output="code skill executed")
'''
        )

        config = SkillsConfig(bundled_dir=tmp_path / "skills", user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        skill = manager.get("my_code_skill")
        assert skill is not None
        assert isinstance(skill, CodeSkill)

    def test_manager_loads_mixed_skills(self, tmp_path: Path) -> None:
        """SkillManager should load both PromptSkills and CodeSkills."""
        from rumi.skills import SkillManager, SkillsConfig, PromptSkill

        skills_dir = tmp_path / "skills"

        # Create a PromptSkill (no skill.py)
        prompt_skill_dir = skills_dir / "prompt_skill"
        prompt_skill_dir.mkdir(parents=True)
        (prompt_skill_dir / "SKILL.md").write_text(
            "---\nname: my_prompt_skill\ndescription: A prompt skill\n---\nInstructions here"
        )

        # Create a CodeSkill (has skill.py)
        code_skill_dir = skills_dir / "code_skill"
        code_skill_dir.mkdir(parents=True)
        (code_skill_dir / "SKILL.md").write_text(
            "---\nname: my_code_skill\ndescription: A code skill\n---\n"
        )
        (code_skill_dir / "skill.py").write_text(
            '''
from rumi.skills import CodeSkill, SkillContext, SkillResult

class MyCodeSkill(CodeSkill):
    async def execute(self, ctx: SkillContext) -> SkillResult:
        return SkillResult(success=True, output="code")
'''
        )

        config = SkillsConfig(bundled_dir=skills_dir, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        assert manager.skill_count == 2

        prompt_skill = manager.get("my_prompt_skill")
        assert isinstance(prompt_skill, PromptSkill)

        code_skill = manager.get("my_code_skill")
        assert isinstance(code_skill, CodeSkill)

    @pytest.mark.asyncio
    async def test_manager_executes_code_skill(self, tmp_path: Path) -> None:
        """SkillManager.execute should work with CodeSkills."""
        from rumi.skills import SkillManager, SkillsConfig

        skill_dir = tmp_path / "skills" / "exec_test"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: exec_test\ndescription: test\n---\n"
        )
        (skill_dir / "skill.py").write_text(
            '''
from rumi.skills import CodeSkill, SkillContext, SkillResult

class ExecTestSkill(CodeSkill):
    async def execute(self, ctx: SkillContext) -> SkillResult:
        return SkillResult(
            success=True,
            output=f"Received: {ctx.user_message}",
            metadata={"type": "code_skill"}
        )
'''
        )

        config = SkillsConfig(bundled_dir=tmp_path / "skills", user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        ctx = SkillContext(
            tools=MagicMock(),
            session=MagicMock(),
            chat_id="test-exec",
            user_message="hello",
        )

        result = await manager.execute("exec_test", ctx)

        assert result.success is True
        assert result.output == "Received: hello"
        assert result.metadata["type"] == "code_skill"
