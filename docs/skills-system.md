# Skills System

The Skills System provides reusable knowledge and orchestration patterns that guide the LLM in completing complex tasks. Unlike Tools (atomic capabilities), Skills represent strategies and workflows.

## Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SKILLS SYSTEM                               │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    SkillManager                              │   │
│  │  - discover(): Scan directories for skills                   │   │
│  │  - register(): Add skill to registry                         │   │
│  │  - match(): Find skills for a query (scoring)                │   │
│  │  - execute(): Run a skill with context                       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│                              ▼                                      │
│  ┌──────────────────┐    ┌──────────────────┐                      │
│  │   PromptSkill    │    │    CodeSkill     │                      │
│  │  (SKILL.md only) │    │ (SKILL.md + .py) │                      │
│  │                  │    │                  │                      │
│  │ Returns          │    │ Orchestrates     │                      │
│  │ instructions     │    │ tools + LLM      │                      │
│  └──────────────────┘    └──────────────────┘                      │
│                                                                     │
│  Discovery Order (priority):                                        │
│  1. bundled/  (lowest)  → Package skills                           │
│  2. user/     (medium)  → ~/.rumi/skills                       │
│  3. workspace (highest) → Project-specific                         │
└─────────────────────────────────────────────────────────────────────┘
```

## Skill Types

### PromptSkill

A PromptSkill is defined by a single `SKILL.md` file with YAML frontmatter and markdown instructions.

**Directory structure:**
```
my_skill/
└── SKILL.md
```

**SKILL.md format:**
```markdown
---
name: summarize
description: Summarize documents and code
version: 1.0.0
tags: [text, analysis]
tools_required: [bash]
enabled: true
---

# Summarize Skill

Instructions for the LLM when this skill is activated.

## Steps
1. Read the file using bash
2. Analyze the content
3. Generate a summary
```

**Frontmatter fields:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| name | string | yes | Unique skill identifier |
| description | string | yes | Short description for listing |
| version | string | no | Semantic version (default: 0.1.0) |
| tags | list | no | Keywords for matching |
| tools_required | list | no | Tools that must be available |
| enabled | bool | no | Whether skill is active (default: true) |

### CodeSkill

A CodeSkill adds a `skill.py` file with a Python class that can orchestrate tools and call the LLM.

**Directory structure:**
```
my_code_skill/
├── SKILL.md
└── skill.py
```

**skill.py format:**
```python
from rumi.skills import CodeSkill, SkillContext, SkillResult

class MyCodeSkillSkill(CodeSkill):
    """Description of the skill."""

    async def execute(self, ctx: SkillContext) -> SkillResult:
        # Access tools
        result = await ctx.tools.dispatch("bash", {"command": "ls"})

        # Access LLM (if provided)
        if ctx.llm:
            response = await ctx.llm.complete("Summarize this")

        # Access settings
        max_words = ctx.config.get("max_words", 300)

        return SkillResult(
            success=True,
            output="Skill completed successfully",
        )
```

## Configuration

Skills configuration is stored in `~/.rumi/config.json`:

```json
{
  "skills": {
    "dirs": ["~/.rumi/skills"],
    "disabled": ["skill_to_disable"],
    "max_in_prompt": 20,
    "settings": {
      "summarize": {
        "max_words": 500
      }
    }
  }
}
```

## CLI Commands

```bash
# List available skills
rumi skills list
rumi skills list --all  # Include disabled

# Enable/disable skills
rumi skills enable <name>
rumi skills disable <name>

# Show skill details
rumi skills info <name>

# Create new skill from template
rumi skills create my_skill
rumi skills create my_skill --code  # With skill.py
rumi skills create my_skill -d "My description"
```

## API Usage

### SkillManager

```python
from rumi.skills import SkillManager, SkillsConfig

# Initialize
config = SkillsConfig(
    bundled_dir=Path("skills/bundled"),
    user_dir=Path.home() / ".rumi" / "skills",
    workspace_dir=Path("./skills"),
)
manager = SkillManager(config)
manager.discover()

# Find matching skills
matches = manager.match("summarize this file")
for skill, score in matches:
    print(f"{skill.name}: {score:.2f}")

# Execute a skill
result = await manager.execute("summarize", ctx)
if result.success:
    print(result.output)
```

### SkillExecutorTool

The `SkillExecutorTool` bridges skills with the ToolRegistry, allowing the LLM to invoke skills:

```python
from rumi.skills import SkillExecutorTool

executor = SkillExecutorTool(manager, tools=registry)
registry.register(executor)

# LLM can now call: use_skill(skill_name="summarize")
```

## Cache System

The SkillManager maintains an mtime-based cache for efficient refresh:

```python
# Full refresh (re-scan all directories)
manager.refresh()

# Incremental refresh (only reload modified skills)
changed = manager.refresh_changed()
print(f"Reloaded: {changed}")

# Clear cache completely
manager.clear_cache()

# Check mtime of a skill
mtime = manager.get_skill_mtime("summarize")
```

## Tools Required Validation

Skills can declare required tools in `tools_required`. The SkillManager validates these before execution:

```python
# Check for missing tools
missing = manager.get_missing_tools("summarize", registry.list_tools())
if missing:
    print(f"Missing tools: {missing}")

# execute() automatically validates and returns error if tools missing
result = await manager.execute("summarize", ctx)
if not result.success:
    print(result.error)  # "Skill 'summarize' requires unavailable tools: bash"
```

## Directory Precedence

Skills are loaded in order of precedence (lowest to highest):

1. **bundled_dir**: Package-included skills (lowest priority)
2. **user_dir**: User's personal skills (~/.rumi/skills)
3. **workspace_dir**: Project-specific skills (highest priority)

If two skills have the same name, the higher priority source wins.

## Bundled Skills

Rumi includes two bundled skills:

### summarize
- **Description**: Summarize documents and code
- **Tags**: text, analysis, documentation
- **Tools Required**: bash
- **Use**: Reads files and generates summaries

### explain
- **Description**: Explain how code works
- **Tags**: learning, code-review, documentation
- **Tools Required**: bash
- **Use**: Analyzes code and provides explanations

## Best Practices

1. **Keep skills focused**: One responsibility per skill
2. **Use descriptive names**: `code_review` not `cr`
3. **Declare tools_required**: Helps validation and documentation
4. **Test with mocks**: Mock ToolRegistry in tests
5. **Use workspace skills**: For project-specific workflows
