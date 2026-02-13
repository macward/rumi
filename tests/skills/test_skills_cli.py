"""Tests for skills CLI commands."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from miniclaw.skills.cli import (
    cmd_list,
    cmd_enable,
    cmd_disable,
    cmd_info,
    cmd_create,
    run_skills_cli,
    create_parser,
    _validate_skill_name,
    _to_class_name,
)
from miniclaw.skills.config import SkillsConfig


def create_skill_dir(base: Path, name: str, description: str, **kwargs) -> Path:
    """Helper to create a skill directory with SKILL.md."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True)

    tags = kwargs.get("tags", [])
    enabled = kwargs.get("enabled", True)
    version = kwargs.get("version", "0.1.0")

    tags_str = ", ".join(tags) if tags else ""
    content = f"""---
name: {name}
description: {description}
version: {version}
tags: [{tags_str}]
enabled: {str(enabled).lower()}
---

Instructions for {name}.
"""
    (skill_dir / "SKILL.md").write_text(content)
    return skill_dir


class TestSkillsListCommand:
    """Tests for 'miniclaw skills list' command."""

    def test_list_shows_skills(self, tmp_path: Path, capsys):
        """List command shows discovered skills."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "summarize", "Summarize documents")
        create_skill_dir(bundled, "explain", "Explain concepts")

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            result = run_skills_cli(["list"])

        assert result == 0
        captured = capsys.readouterr()
        assert "summarize" in captured.out
        assert "explain" in captured.out
        assert "2 skill(s)" in captured.out

    def test_list_excludes_disabled_by_default(self, tmp_path: Path, capsys):
        """List command excludes disabled skills by default."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "enabled_skill", "Enabled")
        create_skill_dir(bundled, "disabled_skill", "Disabled", enabled=False)

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            result = run_skills_cli(["list"])

        assert result == 0
        captured = capsys.readouterr()
        assert "enabled_skill" in captured.out
        assert "disabled_skill" not in captured.out

    def test_list_all_includes_disabled(self, tmp_path: Path, capsys):
        """List --all includes disabled skills."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "enabled_skill", "Enabled")
        create_skill_dir(bundled, "disabled_skill", "Disabled", enabled=False)

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            result = run_skills_cli(["list", "--all"])

        assert result == 0
        captured = capsys.readouterr()
        assert "enabled_skill" in captured.out
        assert "disabled_skill" in captured.out

    def test_list_empty(self, tmp_path: Path, capsys):
        """List command with no skills."""
        config = SkillsConfig(bundled_dir=tmp_path / "empty", user_dir=None)

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            result = run_skills_cli(["list"])

        assert result == 0
        captured = capsys.readouterr()
        assert "No skills found" in captured.out


class TestSkillsEnableCommand:
    """Tests for 'miniclaw skills enable' command."""

    def test_enable_skill(self, tmp_path: Path, capsys):
        """Enable command removes skill from disabled list."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "test_skill", "Test")

        config_path = tmp_path / "config.json"
        config = SkillsConfig(
            bundled_dir=bundled,
            user_dir=None,
            disabled_skills=["test_skill"],
        )

        saved_config = None

        def mock_save(cfg, path=None):
            nonlocal saved_config
            saved_config = cfg

        with (
            patch("miniclaw.skills.cli.load_config", return_value=config),
            patch("miniclaw.skills.cli.save_config", mock_save),
        ):
            result = run_skills_cli(["enable", "test_skill"])

        assert result == 0
        assert "test_skill" not in saved_config.disabled_skills
        captured = capsys.readouterr()
        assert "Enabled skill: test_skill" in captured.out

    def test_enable_already_enabled(self, tmp_path: Path, capsys):
        """Enable command on already enabled skill."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "test_skill", "Test")

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            result = run_skills_cli(["enable", "test_skill"])

        assert result == 0
        captured = capsys.readouterr()
        assert "already enabled" in captured.out

    def test_enable_nonexistent_skill(self, tmp_path: Path, capsys):
        """Enable command on nonexistent skill."""
        config = SkillsConfig(bundled_dir=tmp_path / "empty", user_dir=None)

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            result = run_skills_cli(["enable", "nonexistent"])

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.out

    def test_enable_skill_disabled_in_skill_md(self, tmp_path: Path, capsys):
        """Enable command fails for skills disabled in SKILL.md."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "disabled_skill", "Test", enabled=False)

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            result = run_skills_cli(["enable", "disabled_skill"])

        assert result == 1
        captured = capsys.readouterr()
        assert "disabled in its SKILL.md" in captured.out


class TestSkillsDisableCommand:
    """Tests for 'miniclaw skills disable' command."""

    def test_disable_skill(self, tmp_path: Path, capsys):
        """Disable command adds skill to disabled list."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "test_skill", "Test")

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)
        saved_config = None

        def mock_save(cfg, path=None):
            nonlocal saved_config
            saved_config = cfg

        with (
            patch("miniclaw.skills.cli.load_config", return_value=config),
            patch("miniclaw.skills.cli.save_config", mock_save),
        ):
            result = run_skills_cli(["disable", "test_skill"])

        assert result == 0
        assert "test_skill" in saved_config.disabled_skills
        captured = capsys.readouterr()
        assert "Disabled skill: test_skill" in captured.out

    def test_disable_already_disabled(self, tmp_path: Path, capsys):
        """Disable command on already disabled skill."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(bundled, "test_skill", "Test")

        config = SkillsConfig(
            bundled_dir=bundled,
            user_dir=None,
            disabled_skills=["test_skill"],
        )

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            result = run_skills_cli(["disable", "test_skill"])

        assert result == 0
        captured = capsys.readouterr()
        assert "already disabled" in captured.out

    def test_disable_nonexistent_skill(self, tmp_path: Path, capsys):
        """Disable command on nonexistent skill."""
        config = SkillsConfig(bundled_dir=tmp_path / "empty", user_dir=None)

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            result = run_skills_cli(["disable", "nonexistent"])

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.out


class TestSkillsInfoCommand:
    """Tests for 'miniclaw skills info' command."""

    def test_info_shows_details(self, tmp_path: Path, capsys):
        """Info command shows skill details."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        create_skill_dir(
            bundled,
            "test_skill",
            "A test skill",
            version="1.0.0",
            tags=["test", "example"],
        )

        config = SkillsConfig(bundled_dir=bundled, user_dir=None)

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            result = run_skills_cli(["info", "test_skill"])

        assert result == 0
        captured = capsys.readouterr()
        assert "test_skill" in captured.out
        assert "A test skill" in captured.out
        assert "1.0.0" in captured.out
        assert "test" in captured.out
        assert "example" in captured.out

    def test_info_nonexistent_skill(self, tmp_path: Path, capsys):
        """Info command on nonexistent skill."""
        config = SkillsConfig(bundled_dir=tmp_path / "empty", user_dir=None)

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            result = run_skills_cli(["info", "nonexistent"])

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.out


class TestSkillsCLIHelp:
    """Tests for CLI help and argument parsing."""

    def test_no_command_shows_help(self, capsys):
        """No command shows help."""
        with patch("miniclaw.skills.cli.load_config"):
            result = run_skills_cli([])

        assert result == 0
        captured = capsys.readouterr()
        assert "Manage MiniClaw skills" in captured.out

    def test_parser_structure(self):
        """Parser has expected subcommands."""
        parser = create_parser()

        # Check subparsers exist
        assert parser._subparsers is not None

        # Parse valid commands without error
        args = parser.parse_args(["list"])
        assert args.command == "list"

        args = parser.parse_args(["enable", "test"])
        assert args.command == "enable"
        assert args.name == "test"

        args = parser.parse_args(["disable", "test"])
        assert args.command == "disable"
        assert args.name == "test"

        args = parser.parse_args(["info", "test"])
        assert args.command == "info"
        assert args.name == "test"

        args = parser.parse_args(["create", "my_skill"])
        assert args.command == "create"
        assert args.name == "my_skill"

        args = parser.parse_args(["create", "my_skill", "--code"])
        assert args.code is True


class TestSkillsCreateCommand:
    """Tests for 'miniclaw skills create' command."""

    def test_create_prompt_skill(self, tmp_path: Path, capsys):
        """Create command creates PromptSkill directory and SKILL.md."""
        user_dir = tmp_path / "user_skills"

        config = SkillsConfig(
            bundled_dir=tmp_path / "bundled",
            user_dir=user_dir,
        )

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            result = run_skills_cli(["create", "my_skill"])

        assert result == 0
        captured = capsys.readouterr()
        assert "Created skill: my_skill" in captured.out

        # Check directory was created
        skill_dir = user_dir / "my_skill"
        assert skill_dir.exists()
        assert (skill_dir / "SKILL.md").exists()
        assert not (skill_dir / "skill.py").exists()

        # Check SKILL.md content
        content = (skill_dir / "SKILL.md").read_text()
        assert "name: my_skill" in content
        assert "description:" in content

    def test_create_code_skill(self, tmp_path: Path, capsys):
        """Create --code creates CodeSkill with skill.py."""
        user_dir = tmp_path / "user_skills"

        config = SkillsConfig(
            bundled_dir=tmp_path / "bundled",
            user_dir=user_dir,
        )

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            result = run_skills_cli(["create", "my_code_skill", "--code"])

        assert result == 0

        skill_dir = user_dir / "my_code_skill"
        assert (skill_dir / "SKILL.md").exists()
        assert (skill_dir / "skill.py").exists()

        # Check skill.py content
        py_content = (skill_dir / "skill.py").read_text()
        assert "class MyCodeSkillSkill(CodeSkill):" in py_content
        assert "async def execute" in py_content

    def test_create_with_description(self, tmp_path: Path, capsys):
        """Create with --description sets the description."""
        user_dir = tmp_path / "user_skills"

        config = SkillsConfig(
            bundled_dir=tmp_path / "bundled",
            user_dir=user_dir,
        )

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            result = run_skills_cli([
                "create", "desc_skill",
                "-d", "A custom description"
            ])

        assert result == 0

        content = (user_dir / "desc_skill" / "SKILL.md").read_text()
        assert "description: A custom description" in content

    def test_create_invalid_name(self, tmp_path: Path, capsys):
        """Create fails with invalid skill name."""
        config = SkillsConfig(
            bundled_dir=tmp_path / "bundled",
            user_dir=tmp_path / "user",
        )

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            # Name starting with number
            result = run_skills_cli(["create", "123skill"])
            assert result == 1

            # Name with uppercase
            result = run_skills_cli(["create", "MySkill"])
            assert result == 1

            # Name with special chars
            result = run_skills_cli(["create", "my-skill"])
            assert result == 1

    def test_create_existing_directory(self, tmp_path: Path, capsys):
        """Create fails if directory already exists."""
        user_dir = tmp_path / "user_skills"
        skill_dir = user_dir / "existing"
        skill_dir.mkdir(parents=True)

        config = SkillsConfig(
            bundled_dir=tmp_path / "bundled",
            user_dir=user_dir,
        )

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            result = run_skills_cli(["create", "existing"])

        assert result == 1
        captured = capsys.readouterr()
        assert "already exists" in captured.out

    def test_create_name_conflicts_with_skill(self, tmp_path: Path, capsys):
        """Create fails if skill name already registered."""
        bundled = tmp_path / "bundled"
        bundled.mkdir()
        user_dir = tmp_path / "user_skills"

        # Create existing skill in bundled
        create_skill_dir(bundled, "conflict_name", "Existing skill")

        config = SkillsConfig(
            bundled_dir=bundled,
            user_dir=user_dir,
        )

        with patch("miniclaw.skills.cli.load_config", return_value=config):
            result = run_skills_cli(["create", "conflict_name"])

        assert result == 1
        captured = capsys.readouterr()
        assert "already exists" in captured.out


class TestSkillNameValidation:
    """Tests for skill name validation helpers."""

    def test_validate_valid_names(self):
        """Valid names pass validation."""
        assert _validate_skill_name("myskill") is None
        assert _validate_skill_name("my_skill") is None
        assert _validate_skill_name("skill123") is None
        assert _validate_skill_name("my_skill_v2") is None

    def test_validate_invalid_names(self):
        """Invalid names return error message."""
        assert _validate_skill_name("") is not None  # empty
        assert _validate_skill_name("123skill") is not None  # starts with number
        assert _validate_skill_name("MySkill") is not None  # uppercase
        assert _validate_skill_name("my-skill") is not None  # hyphen
        assert _validate_skill_name("my skill") is not None  # space
        assert _validate_skill_name("a" * 51) is not None  # too long

    def test_to_class_name(self):
        """Class name conversion works correctly."""
        assert _to_class_name("my_skill") == "MySkillSkill"
        assert _to_class_name("summarize") == "SummarizeSkill"
        assert _to_class_name("code_review") == "CodeReviewSkill"
        assert _to_class_name("a_b_c") == "ABCSkill"
