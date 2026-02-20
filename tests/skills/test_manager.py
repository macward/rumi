"""Tests for SkillManager class."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rumi.skills.base import SkillContext, SkillSource
from rumi.skills.manager import SkillManager, SkillsConfig


def create_skill_dir(base: Path, name: str, description: str, **kwargs) -> Path:
    """Helper to create a skill directory with SKILL.md."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True)

    tags = kwargs.get("tags", [])
    enabled = kwargs.get("enabled", True)
    version = kwargs.get("version", "0.1.0")
    body = kwargs.get("body", f"Instructions for {name}")

    tags_str = ", ".join(tags) if tags else ""
    content = f"""---
name: {name}
description: {description}
version: {version}
tags: [{tags_str}]
enabled: {str(enabled).lower()}
---

{body}
"""
    (skill_dir / "SKILL.md").write_text(content)
    return skill_dir


class TestSkillsConfig:
    """Tests for SkillsConfig dataclass."""

    def test_defaults(self):
        """Default config uses home directory for user skills and package bundled dir."""
        config = SkillsConfig()

        assert config.bundled_dir is not None
        assert "bundled" in str(config.bundled_dir)
        assert config.user_dir == Path.home() / ".rumi" / "skills"
        assert config.max_skills_in_prompt == 20
        assert config.disabled_skills == []

    def test_custom_config(self, tmp_path):
        """Custom config values."""
        bundled = tmp_path / "bundled"
        user = tmp_path / "user"

        config = SkillsConfig(
            bundled_dir=bundled,
            user_dir=user,
            max_skills_in_prompt=10,
            disabled_skills=["skill_a"],
        )

        assert config.bundled_dir == bundled
        assert config.user_dir == user
        assert config.max_skills_in_prompt == 10
        assert config.disabled_skills == ["skill_a"]

    def test_invalid_max_skills_in_prompt(self):
        """Invalid max_skills_in_prompt raises ValueError."""
        with pytest.raises(ValueError, match="max_skills_in_prompt must be at least 1"):
            SkillsConfig(max_skills_in_prompt=0)

        with pytest.raises(ValueError, match="max_skills_in_prompt must be at least 1"):
            SkillsConfig(max_skills_in_prompt=-5)


class TestSkillManagerInit:
    """Tests for SkillManager initialization."""

    def test_default_config(self):
        """SkillManager uses default config if none provided."""
        manager = SkillManager()

        assert manager.config is not None
        assert manager.skill_count == 0

    def test_custom_config(self, tmp_path):
        """SkillManager accepts custom config."""
        config = SkillsConfig(bundled_dir=tmp_path)
        manager = SkillManager(config)

        assert manager.config == config


class TestSkillManagerDiscovery:
    """Tests for skill discovery."""

    def test_discover_bundled_skills(self, tmp_path):
        """Discover skills from bundled directory."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "summarize", "Summarize documents")
        create_skill_dir(bundled, "explain", "Explain concepts")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)

        discovered = manager.discover()

        assert len(discovered) == 2
        assert manager.skill_count == 2
        assert manager.get("summarize") is not None
        assert manager.get("explain") is not None

    def test_discover_user_skills(self, tmp_path):
        """Discover skills from user directory."""
        user = tmp_path / "user"
        bundled = tmp_path / "bundled"  # Empty bundled to isolate test
        user.mkdir()
        bundled.mkdir()

        create_skill_dir(user, "custom", "Custom user skill")

        config = SkillsConfig(bundled_dir=bundled, user_dir=user)
        manager = SkillManager(config)

        discovered = manager.discover()

        assert len(discovered) == 1
        skill = manager.get("custom")
        assert skill is not None
        assert skill.metadata.source == SkillSource.USER

    def test_user_overrides_bundled(self, tmp_path):
        """User skills override bundled skills with same name."""
        bundled = tmp_path / "bundled"
        user = tmp_path / "user"
        bundled.mkdir()
        user.mkdir()

        # Create bundled version
        create_skill_dir(bundled, "summarize", "Bundled summarize")
        # Create user version (should override)
        create_skill_dir(user, "summarize", "User summarize")

        config = SkillsConfig(bundled_dir=bundled, user_dir=user)
        manager = SkillManager(config)
        manager.discover()

        skill = manager.get("summarize")
        assert skill is not None
        assert skill.description == "User summarize"
        assert skill.metadata.source == SkillSource.USER

    def test_discover_skips_invalid(self, tmp_path):
        """Invalid skill directories are skipped."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        # Valid skill
        create_skill_dir(bundled, "valid", "Valid skill")

        # Invalid skill (missing name in frontmatter)
        invalid_dir = bundled / "invalid"
        invalid_dir.mkdir()
        (invalid_dir / "SKILL.md").write_text("""---
description: Missing name
---
Body.
""")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)

        discovered = manager.discover()

        # Only valid skill should be registered
        assert len(discovered) == 1
        assert manager.get("valid") is not None
        assert manager.get("invalid") is None

    def test_discover_empty_directory(self, tmp_path):
        """Empty directory returns no skills."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)

        discovered = manager.discover()

        assert discovered == []
        assert manager.skill_count == 0

    def test_discover_nonexistent_directory(self, tmp_path):
        """Nonexistent directory is handled gracefully."""
        config = SkillsConfig(bundled_dir=tmp_path / "nonexistent")
        manager = SkillManager(config)

        discovered = manager.discover()

        assert discovered == []


class TestSkillManagerRegistry:
    """Tests for skill registration and retrieval."""

    def test_register_and_get(self, tmp_path):
        """Register a skill and retrieve by name."""
        skill_dir = tmp_path / "myskill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("""---
name: myskill
description: My skill
---
Body.
""")

        manager = SkillManager()
        skill = manager.load_skill(skill_dir)
        manager.register(skill)

        retrieved = manager.get("myskill")
        assert retrieved is skill

    def test_get_nonexistent(self):
        """Get returns None for unregistered skill."""
        manager = SkillManager()
        assert manager.get("nonexistent") is None

    def test_unregister(self, tmp_path):
        """Unregister removes skill from registry."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "remove_me", "To be removed")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        assert manager.get("remove_me") is not None

        manager.unregister("remove_me")

        assert manager.get("remove_me") is None

    def test_unregister_nonexistent(self):
        """Unregister nonexistent skill is no-op."""
        manager = SkillManager()
        manager.unregister("nonexistent")  # Should not raise


class TestSkillManagerListSkills:
    """Tests for list_skills method."""

    def test_list_skills(self, tmp_path):
        """List all enabled skills."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "skill_a", "Skill A")
        create_skill_dir(bundled, "skill_b", "Skill B")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        skills = manager.list_skills()

        assert len(skills) == 2
        names = [s.name for s in skills]
        assert "skill_a" in names
        assert "skill_b" in names

    def test_list_excludes_disabled(self, tmp_path):
        """Disabled skills are excluded from list."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "enabled", "Enabled skill")
        create_skill_dir(bundled, "disabled", "Disabled skill", enabled=False)

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        skills = manager.list_skills(include_disabled=False)

        assert len(skills) == 1
        assert skills[0].name == "enabled"

    def test_list_includes_disabled(self, tmp_path):
        """Include disabled skills when requested."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "enabled", "Enabled skill")
        create_skill_dir(bundled, "disabled", "Disabled skill", enabled=False)

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        skills = manager.list_skills(include_disabled=True)

        assert len(skills) == 2

    def test_list_excludes_config_disabled(self, tmp_path):
        """Skills in disabled_skills config are excluded."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "skill_a", "Skill A")
        create_skill_dir(bundled, "skill_b", "Skill B")

        config = SkillsConfig(bundled_dir=bundled, disabled_skills=["skill_a"])
        manager = SkillManager(config)
        manager.discover()

        skills = manager.list_skills()

        assert len(skills) == 1
        assert skills[0].name == "skill_b"


class TestSkillManagerPromptGeneration:
    """Tests for get_available_skills_prompt method."""

    def test_empty_when_no_skills(self):
        """Empty string when no skills registered."""
        manager = SkillManager()
        prompt = manager.get_available_skills_prompt()
        assert prompt == ""

    def test_generates_xml_block(self, tmp_path):
        """Generate proper XML structure."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "summarize", "Summarize documents")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        prompt = manager.get_available_skills_prompt()

        assert "<available_skills>" in prompt
        assert "</available_skills>" in prompt
        assert "<skill>" in prompt
        assert "<name>summarize</name>" in prompt
        assert "<description>Summarize documents</description>" in prompt

    def test_multiple_skills(self, tmp_path):
        """Multiple skills in prompt."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "summarize", "Summarize docs")
        create_skill_dir(bundled, "explain", "Explain concepts")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        prompt = manager.get_available_skills_prompt()

        assert prompt.count("<skill>") == 2
        assert "summarize" in prompt
        assert "explain" in prompt

    def test_respects_max_limit(self, tmp_path):
        """Respects max_skills_in_prompt limit."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        # Create 5 skills
        for i in range(5):
            create_skill_dir(bundled, f"skill_{i}", f"Skill {i}")

        config = SkillsConfig(bundled_dir=bundled, max_skills_in_prompt=3)
        manager = SkillManager(config)
        manager.discover()

        prompt = manager.get_available_skills_prompt()

        # Only 3 skills should be included
        assert prompt.count("<skill>") == 3


class TestSkillManagerExecution:
    """Tests for skill execution."""

    @pytest.fixture
    def manager_with_skill(self, tmp_path) -> SkillManager:
        """Create manager with one skill."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(
            bundled, "test_skill", "Test skill", body="Execute these instructions"
        )

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()
        return manager

    @pytest.fixture
    def mock_context(self) -> SkillContext:
        """Create mock execution context."""
        return SkillContext(
            tools=MagicMock(),
            session=MagicMock(),
            chat_id="test_chat",
            user_message="Test message",
        )

    @pytest.mark.asyncio
    async def test_execute_success(self, manager_with_skill, mock_context):
        """Execute skill successfully."""
        result = await manager_with_skill.execute("test_skill", mock_context)

        assert result.success is True
        assert "Execute these instructions" in result.output

    @pytest.mark.asyncio
    async def test_execute_not_found(self, manager_with_skill, mock_context):
        """Execute returns error for unknown skill."""
        result = await manager_with_skill.execute("nonexistent", mock_context)

        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_execute_disabled_skill(self, tmp_path, mock_context):
        """Execute returns error for disabled skill."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "disabled", "Disabled skill", enabled=False)

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        result = await manager.execute("disabled", mock_context)

        assert result.success is False
        assert "disabled" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_config_disabled(self, tmp_path, mock_context):
        """Execute returns error for config-disabled skill."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "blocked", "Blocked skill")

        config = SkillsConfig(bundled_dir=bundled, disabled_skills=["blocked"])
        manager = SkillManager(config)
        manager.discover()

        result = await manager.execute("blocked", mock_context)

        assert result.success is False
        assert "disabled" in result.error.lower()


class TestSkillManagerRefresh:
    """Tests for refresh method."""

    def test_refresh_clears_and_rediscovers(self, tmp_path):
        """Refresh clears registry and rediscovers."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "initial", "Initial skill")

        config = SkillsConfig(bundled_dir=bundled)
        manager = SkillManager(config)
        manager.discover()

        assert manager.skill_count == 1

        # Add another skill
        create_skill_dir(bundled, "new_skill", "New skill")

        manager.refresh()

        assert manager.skill_count == 2
        assert manager.get("new_skill") is not None


class TestSkillManagerWorkspaceDiscovery:
    """Tests for workspace directory discovery and precedence."""

    def test_discover_workspace_skills(self, tmp_path):
        """Discover skills from workspace directory."""
        bundled = tmp_path / "bundled"
        workspace = tmp_path / "workspace"
        bundled.mkdir()
        workspace.mkdir()

        create_skill_dir(workspace, "project_skill", "Project-specific skill")

        config = SkillsConfig(
            bundled_dir=bundled, user_dir=None, workspace_dir=workspace
        )
        manager = SkillManager(config)

        discovered = manager.discover()

        assert len(discovered) == 1
        skill = manager.get("project_skill")
        assert skill is not None
        assert skill.metadata.source == SkillSource.WORKSPACE

    def test_workspace_overrides_user(self, tmp_path):
        """Workspace skills override user skills with same name."""
        bundled = tmp_path / "bundled"
        user = tmp_path / "user"
        workspace = tmp_path / "workspace"
        bundled.mkdir()
        user.mkdir()
        workspace.mkdir()

        # Create user version
        create_skill_dir(user, "summarize", "User summarize")
        # Create workspace version (should override)
        create_skill_dir(workspace, "summarize", "Workspace summarize")

        config = SkillsConfig(
            bundled_dir=bundled, user_dir=user, workspace_dir=workspace
        )
        manager = SkillManager(config)
        manager.discover()

        skill = manager.get("summarize")
        assert skill is not None
        assert skill.description == "Workspace summarize"
        assert skill.metadata.source == SkillSource.WORKSPACE

    def test_workspace_overrides_bundled(self, tmp_path):
        """Workspace skills override bundled skills with same name."""
        bundled = tmp_path / "bundled"
        workspace = tmp_path / "workspace"
        bundled.mkdir()
        workspace.mkdir()

        # Create bundled version
        create_skill_dir(bundled, "explain", "Bundled explain")
        # Create workspace version (should override)
        create_skill_dir(workspace, "explain", "Workspace explain")

        config = SkillsConfig(
            bundled_dir=bundled, user_dir=None, workspace_dir=workspace
        )
        manager = SkillManager(config)
        manager.discover()

        skill = manager.get("explain")
        assert skill is not None
        assert skill.description == "Workspace explain"
        assert skill.metadata.source == SkillSource.WORKSPACE

    def test_full_precedence_chain(self, tmp_path):
        """Test full precedence: workspace > user > bundled."""
        bundled = tmp_path / "bundled"
        user = tmp_path / "user"
        workspace = tmp_path / "workspace"
        bundled.mkdir()
        user.mkdir()
        workspace.mkdir()

        # Create all three versions
        create_skill_dir(bundled, "skill", "Bundled skill")
        create_skill_dir(user, "skill", "User skill")
        create_skill_dir(workspace, "skill", "Workspace skill")

        config = SkillsConfig(
            bundled_dir=bundled, user_dir=user, workspace_dir=workspace
        )
        manager = SkillManager(config)
        manager.discover()

        skill = manager.get("skill")
        assert skill is not None
        # Workspace has highest priority
        assert skill.description == "Workspace skill"
        assert skill.metadata.source == SkillSource.WORKSPACE

    def test_mixed_skills_from_all_sources(self, tmp_path):
        """Skills from all sources coexist when names differ."""
        bundled = tmp_path / "bundled"
        user = tmp_path / "user"
        workspace = tmp_path / "workspace"
        bundled.mkdir()
        user.mkdir()
        workspace.mkdir()

        create_skill_dir(bundled, "bundled_only", "From bundled")
        create_skill_dir(user, "user_only", "From user")
        create_skill_dir(workspace, "workspace_only", "From workspace")

        config = SkillsConfig(
            bundled_dir=bundled, user_dir=user, workspace_dir=workspace
        )
        manager = SkillManager(config)
        manager.discover()

        assert manager.skill_count == 3
        assert manager.get("bundled_only").metadata.source == SkillSource.BUNDLED
        assert manager.get("user_only").metadata.source == SkillSource.USER
        assert manager.get("workspace_only").metadata.source == SkillSource.WORKSPACE

    def test_workspace_none_is_skipped(self, tmp_path):
        """None workspace_dir is gracefully skipped."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "test", "Test skill")

        config = SkillsConfig(
            bundled_dir=bundled, user_dir=None, workspace_dir=None
        )
        manager = SkillManager(config)
        manager.discover()

        assert manager.skill_count == 1

    def test_workspace_nonexistent_is_skipped(self, tmp_path):
        """Nonexistent workspace_dir is gracefully skipped."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "test", "Test skill")

        config = SkillsConfig(
            bundled_dir=bundled,
            user_dir=None,
            workspace_dir=tmp_path / "nonexistent",
        )
        manager = SkillManager(config)
        manager.discover()

        assert manager.skill_count == 1


class TestSkillManagerMatch:
    """Tests for the match() method."""

    def test_match_returns_matching_skills(self, tmp_path):
        """Match returns skills that can handle the query."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "summarize", "Summarize long documents", tags=["text"])
        create_skill_dir(bundled, "explain", "Explain complex concepts", tags=["learning"])

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        matches = manager.match("summarize this document")

        assert len(matches) >= 1
        names = [skill.name for skill, _ in matches]
        assert "summarize" in names

    def test_match_sorts_by_score_descending(self, tmp_path):
        """Match results are sorted by score, highest first."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "summarize", "Summarize documents quickly")
        create_skill_dir(bundled, "document_analysis", "Analyze document structure")

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        matches = manager.match("summarize")

        # First match should have highest score
        if len(matches) > 1:
            scores = [score for _, score in matches]
            assert scores == sorted(scores, reverse=True)

    def test_match_respects_threshold(self, tmp_path):
        """Match filters out skills below threshold."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "summarize", "Summarize documents")
        create_skill_dir(bundled, "unrelated", "Something completely different")

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        # High threshold should exclude low-scoring skills
        matches = manager.match("summarize this text", threshold=0.4)

        names = [skill.name for skill, _ in matches]
        assert "summarize" in names
        # "unrelated" should be filtered out due to low score

    def test_match_excludes_disabled_skills(self, tmp_path):
        """Match excludes disabled skills."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "summarize", "Summarize documents")
        create_skill_dir(bundled, "disabled_sum", "Summarize disabled", enabled=False)

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        matches = manager.match("summarize")

        names = [skill.name for skill, _ in matches]
        assert "summarize" in names
        assert "disabled_sum" not in names

    def test_match_excludes_config_disabled_skills(self, tmp_path):
        """Match excludes skills in disabled_skills config."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "summarize", "Summarize documents")
        create_skill_dir(bundled, "blocked_sum", "Summarize blocked")

        config = SkillsConfig(
            bundled_dir=bundled, user_dir=None, disabled_skills=["blocked_sum"]
        )
        manager = SkillManager(config)
        manager.discover()

        matches = manager.match("summarize")

        names = [skill.name for skill, _ in matches]
        assert "summarize" in names
        assert "blocked_sum" not in names

    def test_match_returns_empty_for_no_matches(self, tmp_path):
        """Match returns empty list when nothing matches."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "summarize", "Summarize documents")

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        # Query that shouldn't match anything with default threshold
        matches = manager.match("xyz123 completely unrelated gibberish", threshold=0.5)

        assert matches == []

    def test_match_with_no_skills(self, tmp_path):
        """Match returns empty list when no skills registered."""
        config = SkillsConfig(bundled_dir=tmp_path / "empty", user_dir=None)
        manager = SkillManager(config)

        matches = manager.match("anything")

        assert matches == []

    def test_match_custom_threshold(self, tmp_path):
        """Match accepts custom threshold."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()

        create_skill_dir(bundled, "summarize", "Summarize documents")

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        # Very low threshold should include more results
        matches_low = manager.match("documents", threshold=0.01)
        # Very high threshold should include fewer results
        matches_high = manager.match("documents", threshold=0.9)

        assert len(matches_low) >= len(matches_high)


class TestSkillManagerCache:
    """Tests for skill caching with mtime tracking."""

    def test_discover_tracks_mtime(self, tmp_path):
        """Discover should store mtime for each skill."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "test_skill", "Test skill")

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        mtime = manager.get_skill_mtime("test_skill")
        assert mtime is not None
        assert mtime > 0

    def test_refresh_changed_reloads_modified(self, tmp_path):
        """refresh_changed should reload skills with changed mtime."""
        import time

        bundled = tmp_path / "bundled"
        bundled.mkdir()
        skill_dir = create_skill_dir(bundled, "changeable", "Original description")

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        assert manager.get("changeable").description == "Original description"
        original_mtime = manager.get_skill_mtime("changeable")

        # Ensure filesystem mtime has different granularity
        time.sleep(0.01)

        # Modify the skill
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: changeable
description: Modified description
---
New instructions.
""")

        reloaded = manager.refresh_changed()

        assert "changeable" in reloaded
        assert manager.get("changeable").description == "Modified description"
        assert manager.get_skill_mtime("changeable") > original_mtime

    def test_refresh_changed_skips_unchanged(self, tmp_path):
        """refresh_changed should not reload unchanged skills."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "static_skill", "Static description")

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        reloaded = manager.refresh_changed()

        assert reloaded == []

    def test_refresh_changed_removes_deleted(self, tmp_path):
        """refresh_changed should remove skills whose files were deleted."""
        import shutil

        bundled = tmp_path / "bundled"
        bundled.mkdir()
        skill_dir = create_skill_dir(bundled, "deletable", "Will be deleted")

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        assert manager.get("deletable") is not None

        # Delete the skill
        shutil.rmtree(skill_dir)

        manager.refresh_changed()

        assert manager.get("deletable") is None
        assert manager.get_skill_mtime("deletable") is None

    def test_clear_cache(self, tmp_path):
        """clear_cache should remove all skills and tracking data."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "skill_a", "Skill A")
        create_skill_dir(bundled, "skill_b", "Skill B")

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        assert manager.skill_count == 2

        manager.clear_cache()

        assert manager.skill_count == 0
        assert manager.get_skill_mtime("skill_a") is None
        assert manager.get_skill_mtime("skill_b") is None

    def test_unregister_cleans_cache(self, tmp_path):
        """unregister should clean up mtime and path tracking."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "remove_me", "To be removed")

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        assert manager.get_skill_mtime("remove_me") is not None

        manager.unregister("remove_me")

        assert manager.get("remove_me") is None
        assert manager.get_skill_mtime("remove_me") is None

    def test_get_skill_mtime_unknown(self, tmp_path):
        """get_skill_mtime returns None for unknown skills."""
        config = SkillsConfig(bundled_dir=tmp_path, user_dir=None)
        manager = SkillManager(config)

        assert manager.get_skill_mtime("nonexistent") is None

    def test_refresh_reloads_all(self, tmp_path):
        """refresh should clear cache and reload all skills."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "skill_one", "First skill")

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        # Add another skill
        create_skill_dir(bundled, "skill_two", "Second skill")

        manager.refresh()

        assert manager.skill_count == 2
        assert manager.get("skill_one") is not None
        assert manager.get("skill_two") is not None


class TestToolsRequiredValidation:
    """Tests for tools_required validation during execution."""

    def _create_skill_with_tools(
        self, base: Path, name: str, tools_required: list[str]
    ) -> Path:
        """Create skill with tools_required in frontmatter."""
        skill_dir = base / name
        skill_dir.mkdir(parents=True)

        tools_str = ", ".join(tools_required) if tools_required else ""
        content = f"""---
name: {name}
description: Skill requiring tools
tools_required: [{tools_str}]
---
Instructions.
"""
        (skill_dir / "SKILL.md").write_text(content)
        return skill_dir

    def test_get_missing_tools_none_missing(self, tmp_path):
        """get_missing_tools returns empty list when all tools available."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        self._create_skill_with_tools(bundled, "needs_bash", ["bash"])

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        missing = manager.get_missing_tools("needs_bash", ["bash", "web_fetch"])
        assert missing == []

    def test_get_missing_tools_some_missing(self, tmp_path):
        """get_missing_tools returns missing tools."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        self._create_skill_with_tools(bundled, "needs_many", ["bash", "unknown_tool"])

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        missing = manager.get_missing_tools("needs_many", ["bash"])
        assert "unknown_tool" in missing
        assert "bash" not in missing

    def test_get_missing_tools_nonexistent_skill(self, tmp_path):
        """get_missing_tools returns empty for nonexistent skill."""
        config = SkillsConfig(bundled_dir=tmp_path, user_dir=None)
        manager = SkillManager(config)

        missing = manager.get_missing_tools("nonexistent", ["bash"])
        assert missing == []

    def test_get_missing_tools_no_requirements(self, tmp_path):
        """get_missing_tools returns empty when no tools required."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "no_tools", "No tools needed")

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        missing = manager.get_missing_tools("no_tools", [])
        assert missing == []

    @pytest.mark.asyncio
    async def test_execute_validates_tools_required(self, tmp_path):
        """Execute fails when required tools are missing."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        self._create_skill_with_tools(bundled, "needs_tool", ["bash", "custom_tool"])

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        # Mock tools registry that only has "bash"
        mock_tools = MagicMock()
        mock_tools.list_tools.return_value = ["bash"]

        ctx = SkillContext(
            tools=mock_tools,
            session=MagicMock(),
            chat_id="test_chat",
            user_message="Test",
        )

        result = await manager.execute("needs_tool", ctx)

        assert result.success is False
        assert "custom_tool" in result.error
        assert "unavailable tools" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_succeeds_with_all_tools(self, tmp_path):
        """Execute succeeds when all required tools are available."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        self._create_skill_with_tools(bundled, "needs_bash", ["bash"])

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        # Mock tools registry that has "bash"
        mock_tools = MagicMock()
        mock_tools.list_tools.return_value = ["bash", "web_fetch"]

        ctx = SkillContext(
            tools=mock_tools,
            session=MagicMock(),
            chat_id="test_chat",
            user_message="Test",
        )

        result = await manager.execute("needs_bash", ctx)

        # PromptSkill should succeed
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_no_tools_required(self, tmp_path):
        """Execute succeeds when skill has no tools_required."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "no_tools", "No tools needed")

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        mock_tools = MagicMock()
        mock_tools.list_tools.return_value = []

        ctx = SkillContext(
            tools=mock_tools,
            session=MagicMock(),
            chat_id="test_chat",
            user_message="Test",
        )

        result = await manager.execute("no_tools", ctx)

        assert result.success is True
