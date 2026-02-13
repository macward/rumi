"""Tests for bundled skills."""

from pathlib import Path

import pytest

from miniclaw.skills import SkillManager, SkillsConfig
from miniclaw.skills.base import SkillContext, SkillSource
from miniclaw.session.manager import SessionState
from miniclaw.tools import ToolRegistry


# Path to the actual bundled skills
BUNDLED_DIR = Path(__file__).parent.parent.parent / "src" / "miniclaw" / "skills" / "bundled"


class TestBundledSkillsDiscovery:
    """Tests for discovering bundled skills."""

    def test_bundled_dir_exists(self):
        """Bundled skills directory exists."""
        assert BUNDLED_DIR.exists()
        assert BUNDLED_DIR.is_dir()

    def test_missing_bundled_dir_graceful_degradation(self, tmp_path):
        """Manager handles missing bundled directory gracefully."""
        nonexistent = tmp_path / "nonexistent"
        config = SkillsConfig(bundled_dir=nonexistent)
        manager = SkillManager(config)

        # Should not raise, just return empty
        discovered = manager.discover()

        assert discovered == []
        assert manager.skill_count == 0

    def test_summarize_skill_exists(self):
        """summarize skill directory exists."""
        summarize_dir = BUNDLED_DIR / "summarize"
        assert summarize_dir.exists()
        assert (summarize_dir / "SKILL.md").exists()

    def test_explain_skill_exists(self):
        """explain skill directory exists."""
        explain_dir = BUNDLED_DIR / "explain"
        assert explain_dir.exists()
        assert (explain_dir / "SKILL.md").exists()

    def test_default_config_finds_bundled(self):
        """Default SkillsConfig points to bundled directory."""
        config = SkillsConfig()
        assert config.bundled_dir is not None
        assert "bundled" in str(config.bundled_dir)

    def test_manager_discovers_bundled_skills(self):
        """SkillManager discovers both bundled skills."""
        config = SkillsConfig(bundled_dir=BUNDLED_DIR)
        manager = SkillManager(config)

        discovered = manager.discover()

        skill_names = [m.name for m in discovered]
        assert "summarize" in skill_names
        assert "explain" in skill_names
        assert len(skill_names) >= 2


class TestBundledSkillsContent:
    """Tests for bundled skill content and metadata."""

    @pytest.fixture
    def manager(self) -> SkillManager:
        """Create manager with bundled skills."""
        config = SkillsConfig(bundled_dir=BUNDLED_DIR)
        manager = SkillManager(config)
        manager.discover()
        return manager

    def test_summarize_metadata(self, manager):
        """summarize skill has correct metadata."""
        skill = manager.get("summarize")

        assert skill is not None
        assert skill.name == "summarize"
        assert "summarize" in skill.description.lower() or "file" in skill.description.lower()
        assert skill.metadata.source == SkillSource.BUNDLED
        assert skill.enabled is True

    def test_explain_metadata(self, manager):
        """explain skill has correct metadata."""
        skill = manager.get("explain")

        assert skill is not None
        assert skill.name == "explain"
        assert "explain" in skill.description.lower() or "code" in skill.description.lower()
        assert skill.metadata.source == SkillSource.BUNDLED
        assert skill.enabled is True

    def test_summarize_requires_bash(self, manager):
        """summarize skill requires bash tool."""
        skill = manager.get("summarize")
        assert "bash" in skill.metadata.tools_required

    def test_explain_requires_bash(self, manager):
        """explain skill requires bash tool."""
        skill = manager.get("explain")
        assert "bash" in skill.metadata.tools_required

    def test_skills_appear_in_prompt(self, manager):
        """Both skills appear in available_skills prompt."""
        prompt = manager.get_available_skills_prompt()

        assert "<available_skills>" in prompt
        assert "summarize" in prompt
        assert "explain" in prompt
        assert "</available_skills>" in prompt


class TestBundledSkillsExecution:
    """Tests for executing bundled skills."""

    @pytest.fixture
    def manager(self) -> SkillManager:
        """Create manager with bundled skills."""
        config = SkillsConfig(bundled_dir=BUNDLED_DIR)
        manager = SkillManager(config)
        manager.discover()
        return manager

    @pytest.fixture
    def context(self) -> SkillContext:
        """Create minimal execution context."""
        return SkillContext(
            tools=ToolRegistry(),
            session=SessionState(chat_id="test-bundled"),
            chat_id="test-bundled",
            user_message="Test execution",
        )

    @pytest.mark.asyncio
    async def test_execute_summarize(self, manager, context):
        """Can execute summarize skill."""
        result = await manager.execute("summarize", context)

        assert result.success is True
        assert result.output != ""
        assert "summarize" in result.output.lower() or "file" in result.output.lower()
        assert result.metadata is not None
        assert result.metadata["skill_name"] == "summarize"

    @pytest.mark.asyncio
    async def test_execute_explain(self, manager, context):
        """Can execute explain skill."""
        result = await manager.execute("explain", context)

        assert result.success is True
        assert result.output != ""
        assert "explain" in result.output.lower() or "code" in result.output.lower()
        assert result.metadata is not None
        assert result.metadata["skill_name"] == "explain"


class TestBundledSkillsIntegration:
    """Integration tests with SkillExecutorTool."""

    @pytest.mark.asyncio
    async def test_executor_tool_with_bundled_skills(self):
        """SkillExecutorTool can invoke bundled skills."""
        from miniclaw.skills import SkillExecutorTool

        config = SkillsConfig(bundled_dir=BUNDLED_DIR)
        manager = SkillManager(config)
        manager.discover()

        tool = SkillExecutorTool(manager)

        result = await tool.execute(skill_name="summarize", chat_id="test")
        assert result.success is True

        result = await tool.execute(skill_name="explain", chat_id="test")
        assert result.success is True
