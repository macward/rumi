"""Tests for skills configuration loading and management."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from rumi.skills import (
    SkillsConfig,
    SkillManager,
    SkillContext,
    load_config,
    save_config,
)


class TestSkillsConfig:
    """Tests for SkillsConfig dataclass."""

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        config = SkillsConfig()

        assert config.bundled_dir is not None
        assert "bundled" in str(config.bundled_dir)
        assert config.user_dir == Path.home() / ".rumi" / "skills"
        assert config.max_skills_in_prompt == 20
        assert config.disabled_skills == []
        assert config.skill_settings == {}

    def test_custom_values(self, tmp_path: Path) -> None:
        """Should accept custom values."""
        config = SkillsConfig(
            bundled_dir=tmp_path / "bundled",
            user_dir=tmp_path / "user",
            max_skills_in_prompt=10,
            disabled_skills=["skill1", "skill2"],
            skill_settings={"summarize": {"max_words": 300}},
        )

        assert config.bundled_dir == tmp_path / "bundled"
        assert config.user_dir == tmp_path / "user"
        assert config.max_skills_in_prompt == 10
        assert config.disabled_skills == ["skill1", "skill2"]
        assert config.skill_settings == {"summarize": {"max_words": 300}}

    def test_invalid_max_skills(self) -> None:
        """Should reject max_skills_in_prompt < 1."""
        with pytest.raises(ValueError, match="must be at least 1"):
            SkillsConfig(max_skills_in_prompt=0)

    def test_get_skill_settings(self) -> None:
        """Should return settings for specific skill."""
        config = SkillsConfig(
            skill_settings={
                "summarize": {"max_words": 300},
                "explain": {"verbose": True},
            }
        )

        assert config.get_skill_settings("summarize") == {"max_words": 300}
        assert config.get_skill_settings("explain") == {"verbose": True}
        assert config.get_skill_settings("unknown") == {}

    def test_is_skill_disabled(self) -> None:
        """Should check if skill is disabled."""
        config = SkillsConfig(disabled_skills=["skill1", "skill2"])

        assert config.is_skill_disabled("skill1") is True
        assert config.is_skill_disabled("skill2") is True
        assert config.is_skill_disabled("skill3") is False


class TestLoadConfig:
    """Tests for load_config function."""

    def test_loads_from_file(self, tmp_path: Path) -> None:
        """Should load config from JSON file."""
        config_path = tmp_path / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "skills": {
                        "dirs": [str(tmp_path / "my-skills")],
                        "disabled": ["git_review"],
                        "max_in_prompt": 15,
                        "settings": {"summarize": {"max_words": 500}},
                    }
                }
            )
        )

        config = load_config(config_path)

        assert config.user_dir == tmp_path / "my-skills"
        assert config.disabled_skills == ["git_review"]
        assert config.max_skills_in_prompt == 15
        assert config.skill_settings == {"summarize": {"max_words": 500}}

    def test_returns_defaults_when_file_missing(self, tmp_path: Path) -> None:
        """Should return defaults when file doesn't exist."""
        config = load_config(tmp_path / "nonexistent.json")

        assert config.disabled_skills == []
        assert config.max_skills_in_prompt == 20

    def test_returns_defaults_on_invalid_json(self, tmp_path: Path) -> None:
        """Should return defaults on invalid JSON."""
        config_path = tmp_path / "config.json"
        config_path.write_text("not valid json {{{")

        config = load_config(config_path)

        assert config.disabled_skills == []

    def test_partial_config(self, tmp_path: Path) -> None:
        """Should handle partial config gracefully."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"skills": {"disabled": ["one"]}}))

        config = load_config(config_path)

        assert config.disabled_skills == ["one"]
        assert config.max_skills_in_prompt == 20  # default
        assert config.skill_settings == {}  # default

    def test_empty_config(self, tmp_path: Path) -> None:
        """Should handle empty config."""
        config_path = tmp_path / "config.json"
        config_path.write_text("{}")

        config = load_config(config_path)

        assert config.disabled_skills == []
        assert config.max_skills_in_prompt == 20


class TestSaveConfig:
    """Tests for save_config function."""

    def test_saves_to_file(self, tmp_path: Path) -> None:
        """Should save config to JSON file."""
        config_path = tmp_path / "config.json"
        config = SkillsConfig(
            user_dir=tmp_path / "skills",
            disabled_skills=["skill1"],
            max_skills_in_prompt=10,
            skill_settings={"test": {"key": "value"}},
        )

        save_config(config, config_path)

        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert "skills" in data
        assert data["skills"]["disabled"] == ["skill1"]
        assert data["skills"]["max_in_prompt"] == 10
        assert data["skills"]["settings"] == {"test": {"key": "value"}}

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Should create parent directories if needed."""
        config_path = tmp_path / "nested" / "dir" / "config.json"
        config = SkillsConfig(disabled_skills=["test"])

        save_config(config, config_path)

        assert config_path.exists()

    def test_roundtrip(self, tmp_path: Path) -> None:
        """Save and load should preserve config."""
        config_path = tmp_path / "config.json"
        original = SkillsConfig(
            disabled_skills=["a", "b"],
            max_skills_in_prompt=5,
            skill_settings={"x": {"y": 1}},
        )

        save_config(original, config_path)
        loaded = load_config(config_path)

        assert loaded.disabled_skills == original.disabled_skills
        assert loaded.max_skills_in_prompt == original.max_skills_in_prompt
        assert loaded.skill_settings == original.skill_settings


class TestSkillManagerEnableDisable:
    """Tests for SkillManager enable/disable methods."""

    def test_disable_skill(self, tmp_path: Path) -> None:
        """Should add skill to disabled list."""
        skill_dir = tmp_path / "skills" / "test"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n"
        )

        config = SkillsConfig(bundled_dir=tmp_path / "skills", user_dir=None)
        manager = SkillManager(config)
        manager.discover()

        assert manager.is_skill_available("test") is True

        result = manager.disable("test")

        assert result is True
        assert manager.is_skill_available("test") is False
        assert "test" in manager.config.disabled_skills

    def test_disable_already_disabled(self, tmp_path: Path) -> None:
        """Should return False when disabling already disabled skill."""
        config = SkillsConfig(
            bundled_dir=tmp_path, user_dir=None, disabled_skills=["test"]
        )
        manager = SkillManager(config)

        result = manager.disable("test")

        assert result is False

    def test_enable_skill(self, tmp_path: Path) -> None:
        """Should remove skill from disabled list."""
        skill_dir = tmp_path / "skills" / "test"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test\ndescription: test\n---\n"
        )

        config = SkillsConfig(
            bundled_dir=tmp_path / "skills",
            user_dir=None,
            disabled_skills=["test"],
        )
        manager = SkillManager(config)
        manager.discover()

        assert manager.is_skill_available("test") is False

        result = manager.enable("test")

        assert result is True
        assert manager.is_skill_available("test") is True
        assert "test" not in manager.config.disabled_skills

    def test_enable_not_disabled(self, tmp_path: Path) -> None:
        """Should return False when enabling non-disabled skill."""
        config = SkillsConfig(bundled_dir=tmp_path, user_dir=None)
        manager = SkillManager(config)

        result = manager.enable("test")

        assert result is False


class TestSkillManagerWithSettings:
    """Tests for SkillManager with skill settings."""

    def test_get_skill_settings(self, tmp_path: Path) -> None:
        """Should return settings for skill."""
        config = SkillsConfig(
            bundled_dir=tmp_path,
            user_dir=None,
            skill_settings={"summarize": {"max_words": 300}},
        )
        manager = SkillManager(config)

        settings = manager.get_skill_settings("summarize")

        assert settings == {"max_words": 300}

    def test_get_skill_settings_unknown(self, tmp_path: Path) -> None:
        """Should return empty dict for unknown skill."""
        config = SkillsConfig(bundled_dir=tmp_path, user_dir=None)
        manager = SkillManager(config)

        settings = manager.get_skill_settings("unknown")

        assert settings == {}

    @pytest.mark.asyncio
    async def test_execute_injects_settings(self, tmp_path: Path) -> None:
        """Execute should inject skill settings into context."""
        skill_dir = tmp_path / "skills" / "settings_test"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: settings_test\ndescription: test\n---\n"
        )
        (skill_dir / "skill.py").write_text(
            '''
from rumi.skills import CodeSkill, SkillContext, SkillResult

class SettingsTestSkill(CodeSkill):
    async def execute(self, ctx: SkillContext) -> SkillResult:
        max_words = ctx.config.get("max_words", "not set")
        return SkillResult(success=True, output=f"max_words={max_words}")
'''
        )

        config = SkillsConfig(
            bundled_dir=tmp_path / "skills",
            user_dir=None,
            skill_settings={"settings_test": {"max_words": 500}},
        )
        manager = SkillManager(config)
        manager.discover()

        ctx = SkillContext(
            tools=MagicMock(),
            session=MagicMock(),
            chat_id="test",
            user_message="",
        )

        result = await manager.execute("settings_test", ctx)

        assert result.success is True
        assert result.output == "max_words=500"
