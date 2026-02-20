"""CLI commands for skill management.

Provides subcommands for listing, enabling, disabling, and creating skills.
"""

import argparse
import re
import sys
from pathlib import Path

from .config import load_config, save_config
from .manager import SkillManager


def _get_manager() -> SkillManager:
    """Create a SkillManager with config loaded from disk."""
    config = load_config()
    manager = SkillManager(config)
    manager.discover()
    return manager


def _format_source(source: str) -> str:
    """Format source for display with color hints."""
    colors = {
        "bundled": "\033[34m",  # blue
        "user": "\033[32m",     # green
        "workspace": "\033[35m",  # magenta
    }
    reset = "\033[0m"
    color = colors.get(source.lower(), "")
    return f"{color}{source}{reset}"


def _format_status(enabled: bool, config_disabled: bool) -> str:
    """Format enabled status for display."""
    if not enabled:
        return "\033[31mdisabled (in SKILL.md)\033[0m"
    if config_disabled:
        return "\033[33mdisabled (in config)\033[0m"
    return "\033[32menabled\033[0m"


def cmd_list(args: argparse.Namespace) -> int:
    """List all available skills."""
    manager = _get_manager()
    skills = manager.list_skills(include_disabled=args.all)

    if not skills:
        print("No skills found.")
        return 0

    # Header
    print(f"\n{'Name':<20} {'Source':<12} {'Status':<28} Description")
    print("-" * 80)

    for meta in sorted(skills, key=lambda s: s.name):
        config_disabled = meta.name in manager.config.disabled_skills
        status = _format_status(meta.enabled, config_disabled)
        source = _format_source(meta.source.value)

        # Truncate long descriptions
        desc = meta.description
        if len(desc) > 35:
            desc = desc[:32] + "..."

        print(f"{meta.name:<20} {source:<21} {status:<37} {desc}")

    print(f"\nTotal: {len(skills)} skill(s)")
    return 0


def cmd_enable(args: argparse.Namespace) -> int:
    """Enable a disabled skill."""
    config = load_config()
    manager = SkillManager(config)
    manager.discover()

    skill = manager.get(args.name)
    if skill is None:
        print(f"Error: Skill '{args.name}' not found.")
        return 1

    if not skill.enabled:
        print(f"Error: Skill '{args.name}' is disabled in its SKILL.md (enabled: false).")
        print("Edit the SKILL.md to enable it.")
        return 1

    if args.name not in config.disabled_skills:
        print(f"Skill '{args.name}' is already enabled.")
        return 0

    config.disabled_skills.remove(args.name)
    save_config(config)
    print(f"Enabled skill: {args.name}")
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    """Disable a skill."""
    config = load_config()
    manager = SkillManager(config)
    manager.discover()

    skill = manager.get(args.name)
    if skill is None:
        print(f"Error: Skill '{args.name}' not found.")
        return 1

    if args.name in config.disabled_skills:
        print(f"Skill '{args.name}' is already disabled.")
        return 0

    config.disabled_skills.append(args.name)
    save_config(config)
    print(f"Disabled skill: {args.name}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    """Show detailed info about a skill."""
    manager = _get_manager()

    skill = manager.get(args.name)
    if skill is None:
        print(f"Error: Skill '{args.name}' not found.")
        return 1

    meta = skill.metadata
    config_disabled = meta.name in manager.config.disabled_skills

    print(f"\nSkill: {meta.name}")
    print("-" * 40)
    print(f"Description: {meta.description}")
    print(f"Version: {meta.version}")
    print(f"Source: {_format_source(meta.source.value)}")
    print(f"Status: {_format_status(meta.enabled, config_disabled)}")

    if meta.tags:
        print(f"Tags: {', '.join(meta.tags)}")

    if meta.tools_required:
        print(f"Required tools: {', '.join(meta.tools_required)}")

    if meta.path:
        print(f"Path: {meta.path}")

    mtime = manager.get_skill_mtime(meta.name)
    if mtime:
        from datetime import datetime
        dt = datetime.fromtimestamp(mtime)
        print(f"Last modified: {dt.strftime('%Y-%m-%d %H:%M:%S')}")

    return 0


SKILL_MD_TEMPLATE = '''---
name: {name}
description: {description}
version: 0.1.0
tags: []
enabled: true
---

# {name}

Instructions for the LLM when this skill is activated.

## When to use

Describe when this skill should be invoked.

## Steps

1. First step
2. Second step
3. ...
'''

CODE_SKILL_TEMPLATE = '''"""CodeSkill implementation for {name}."""

from rumi.skills import CodeSkill, SkillContext, SkillResult


class {class_name}(CodeSkill):
    """{description}"""

    async def execute(self, ctx: SkillContext) -> SkillResult:
        """Execute the skill.

        Args:
            ctx: Execution context with tools, session, LLM access.

        Returns:
            SkillResult with output or error.
        """
        # Access tools via ctx.tools
        # Access LLM via ctx.llm.complete(prompt)
        # Access settings via ctx.config

        # Example: return a simple result
        return SkillResult(
            success=True,
            output="Skill executed successfully.",
        )
'''


def _validate_skill_name(name: str) -> str | None:
    """Validate skill name.

    Returns error message if invalid, None if valid.
    """
    if not name:
        return "Skill name cannot be empty"

    if not re.match(r'^[a-z][a-z0-9_]*$', name):
        return "Skill name must start with lowercase letter and contain only a-z, 0-9, _"

    if len(name) > 50:
        return "Skill name must be 50 characters or less"

    return None


def _to_class_name(name: str) -> str:
    """Convert skill name to PascalCase class name.

    Example: my_skill -> MySkillSkill
    """
    parts = name.split('_')
    return ''.join(word.capitalize() for word in parts) + 'Skill'


def cmd_create(args: argparse.Namespace) -> int:
    """Create a new skill from template."""
    name = args.name

    # Validate name
    error = _validate_skill_name(name)
    if error:
        print(f"Error: {error}")
        return 1

    # Determine target directory
    config = load_config()
    user_dir = config.user_dir or (Path.home() / ".rumi" / "skills")
    skill_dir = user_dir / name

    # Check if already exists
    if skill_dir.exists():
        print(f"Error: Skill directory already exists: {skill_dir}")
        return 1

    # Check if name conflicts with existing skill
    manager = SkillManager(config)
    manager.discover()
    if manager.get(name) is not None:
        print(f"Error: A skill named '{name}' already exists.")
        return 1

    # Create directory
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Get description from args or use placeholder
    description = args.description or f"Description for {name}"

    # Create SKILL.md
    skill_md_content = SKILL_MD_TEMPLATE.format(
        name=name,
        description=description,
    )
    (skill_dir / "SKILL.md").write_text(skill_md_content)

    # Create skill.py if --code flag
    if args.code:
        class_name = _to_class_name(name)
        skill_py_content = CODE_SKILL_TEMPLATE.format(
            name=name,
            class_name=class_name,
            description=description,
        )
        (skill_dir / "skill.py").write_text(skill_py_content)

    # Print success message
    print(f"\n✓ Created skill: {name}")
    print(f"  Location: {skill_dir}")
    print("\nFiles created:")
    print(f"  - SKILL.md (skill definition)")
    if args.code:
        print(f"  - skill.py (CodeSkill implementation)")

    print("\nNext steps:")
    print(f"  1. Edit {skill_dir / 'SKILL.md'} to customize instructions")
    if args.code:
        print(f"  2. Implement your skill logic in {skill_dir / 'skill.py'}")
    print(f"  3. Run 'rumi skills list' to verify the skill is discovered")

    return 0


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for skills CLI."""
    parser = argparse.ArgumentParser(
        prog="rumi skills",
        description="Manage Rumi skills",
    )

    subparsers = parser.add_subparsers(dest="command", help="Sub-command help")

    # list command
    list_parser = subparsers.add_parser("list", help="List available skills")
    list_parser.add_argument(
        "-a", "--all",
        action="store_true",
        help="Include disabled skills",
    )

    # enable command
    enable_parser = subparsers.add_parser("enable", help="Enable a skill")
    enable_parser.add_argument("name", help="Name of the skill to enable")

    # disable command
    disable_parser = subparsers.add_parser("disable", help="Disable a skill")
    disable_parser.add_argument("name", help="Name of the skill to disable")

    # info command
    info_parser = subparsers.add_parser("info", help="Show detailed skill info")
    info_parser.add_argument("name", help="Name of the skill")

    # create command
    create_parser = subparsers.add_parser("create", help="Create a new skill")
    create_parser.add_argument("name", help="Name for the new skill (lowercase, underscores)")
    create_parser.add_argument(
        "-d", "--description",
        help="Description of the skill",
    )
    create_parser.add_argument(
        "--code",
        action="store_true",
        help="Create a CodeSkill with skill.py template",
    )

    return parser


def run_skills_cli(argv: list[str] | None = None) -> int:
    """Run the skills CLI with given arguments.

    Args:
        argv: Command-line arguments. Uses sys.argv[1:] if None.

    Returns:
        Exit code (0 for success, non-zero for error).
    """
    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    commands = {
        "list": cmd_list,
        "enable": cmd_enable,
        "disable": cmd_disable,
        "info": cmd_info,
        "create": cmd_create,
    }

    handler = commands.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(run_skills_cli())
