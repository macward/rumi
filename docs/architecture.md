# Rumi Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INPUT LAYER                                 │
│  ┌─────────────┐    ┌─────────────────┐                            │
│  │    CLI      │    │    Telegram     │                            │
│  │  (cli.py)   │    │   (bot.py)      │                            │
│  └──────┬──────┘    └────────┬────────┘                            │
│         │                    │                                      │
│         └────────┬───────────┘                                      │
│                  ▼                                                  │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │              SessionManager (session/manager.py)              │ │
│  │  - Per-chat locks (prevents concurrent execution)             │ │
│  │  - Conversation history                                       │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       AGENT LAYER                                   │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                  AgentLoop (agent/loop.py)                    │ │
│  │                                                               │ │
│  │   ┌─────────┐    ┌─────────┐    ┌─────────┐                  │ │
│  │   │  THINK  │───▶│   ACT   │───▶│ OBSERVE │──┐               │ │
│  │   │  (LLM)  │    │ (tools) │    │(results)│  │               │ │
│  │   └─────────┘    └─────────┘    └─────────┘  │               │ │
│  │        ▲                                      │               │ │
│  │        └──────────────────────────────────────┘               │ │
│  │                                                               │ │
│  │   Circuit Breakers:                                          │ │
│  │   - max_turns (10)                                           │ │
│  │   - repeated_calls (2)                                       │ │
│  │   - consecutive_errors (3)                                   │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                              │                                      │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                ToolRegistry (tools/registry.py)               │ │
│  │   dispatch(tool_name, args) → ToolResult                     │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       TOOLS LAYER                                   │
│  ┌─────────────────────────┐    ┌─────────────────────────────────┐│
│  │   BashTool (bash.py)    │    │   WebFetchTool (web_fetch.py)   ││
│  │                         │    │                                 ││
│  │ - Command allowlist     │    │ - SSRF protection               ││
│  │ - Pattern validation    │    │ - DNS resolution check          ││
│  │ - shlex.split() parsing │    │ - Redirect validation           ││
│  │                         │    │ - Runs on HOST (not container)  ││
│  └───────────┬─────────────┘    └─────────────────────────────────┘│
│              │                                                      │
│              ▼                                                      │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │             SandboxManager (sandbox/manager.py)               │ │
│  │                                                               │ │
│  │  Container: rumi-runner-{chat_id}                        │ │
│  │  - read_only=True                                            │ │
│  │  - cap_drop=["ALL"]                                          │ │
│  │  - network_mode="none"                                       │ │
│  │  - user=1000:1000                                            │ │
│  │  - mem_limit=512m, cpus=1                                    │ │
│  │                                                               │ │
│  │  Mounts:                                                     │ │
│  │  - ~/.rumi/workspace/{chat_id} → /workspace (rw)         │ │
│  │  - tmpfs → /tmp (64MB)                                       │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    DOCKER CONTAINER                                 │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │              rumi-runner:latest (Alpine 3.19)             │ │
│  │                                                               │ │
│  │  Installed: bash, coreutils, findutils, grep, sed, gawk      │ │
│  │  Removed:   wget, curl, nc (no network tools)                │ │
│  │  User:      runner (1000:1000)                               │ │
│  │  Network:   NONE (air-gapped)                                │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

## Data Flow: Command Execution

```
User: "list files"
        │
        ▼
┌──────────────────────────────────────────────────────────┐
│ AgentLoop.run()                                          │
│   1. Build messages with system prompt                   │
│   2. Call Groq LLM (llama-3.1-70b-versatile)            │
│   3. LLM returns tool_call: bash(command="ls -la")      │
└───────────────────────┬──────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│ BashTool.execute()                                       │
│   1. _validate_command("ls -la")                        │
│      - Check FORBIDDEN_PATTERNS (pipes, &&, etc)        │
│      - shlex.split() → ["ls", "-la"]                    │
│      - Verify "ls" in ALLOWED_COMMANDS                  │
│   2. Call sandbox.exec_command()                        │
└───────────────────────┬──────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│ SandboxManager.exec_command()                            │
│   1. ensure_container(chat_id)                          │
│      - Get existing or create new                       │
│   2. container.exec_run(["ls", "-la"])                  │
│      - Runs inside Docker container                     │
│   3. Return ExecResult(exit_code, output, duration)     │
└───────────────────────┬──────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│ AgentLoop (continued)                                    │
│   4. Format tool result                                 │
│   5. Add to messages                                    │
│   6. Call LLM again with result                         │
│   7. LLM generates final response                       │
│   8. Return AgentResult                                 │
└──────────────────────────────────────────────────────────┘
```

## Security Boundaries

```
                    TRUSTED                           UNTRUSTED
           ┌──────────────────────────────┬──────────────────────────┐
           │                              │                          │
HOST       │  Rumi Python Process     │                          │
           │  - AgentLoop                 │                          │
           │  - WebFetchTool              │                          │
           │  - SandboxManager            │                          │
           │                              │                          │
           ├──────────────────────────────┼──────────────────────────┤
           │                              │                          │
DOCKER     │                              │  rumi-runner         │
           │                              │  - User commands         │
           │                              │  - No network            │
           │                              │  - Read-only rootfs      │
           │                              │  - Capability dropped    │
           │                              │                          │
           └──────────────────────────────┴──────────────────────────┘

Security Controls:
├── Container Level
│   ├── read_only=True (immutable rootfs)
│   ├── cap_drop=["ALL"] (no Linux capabilities)
│   ├── network_mode="none" (no network access)
│   ├── security_opt=["no-new-privileges"]
│   ├── pids_limit=128 (prevent fork bombs)
│   └── mem_limit=512m, cpus=1 (resource limits)
│
├── Command Level
│   ├── ALLOWED_COMMANDS allowlist
│   ├── FORBIDDEN_PATTERNS (|, &&, ;, >, <, $())
│   └── shlex.split() (no shell interpretation)
│
└── Web Fetch Level
    ├── Scheme allowlist (http, https only)
    ├── DNS resolution before connect
    └── IP allowlist (block private ranges)
```

## Skills Layer

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SKILLS LAYER                                │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │                    SkillManager                                │ │
│  │  - discover(): Load from bundled/user/workspace               │ │
│  │  - match(): Find relevant skills by query                     │ │
│  │  - execute(): Run skill with SkillContext                     │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                              │                                      │
│              ┌───────────────┼───────────────┐                      │
│              ▼               ▼               ▼                      │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐    │
│  │  PromptSkill     │ │   CodeSkill      │ │ SkillExecutorTool│    │
│  │  (SKILL.md)      │ │  (skill.py)      │ │ (use_skill tool) │    │
│  └──────────────────┘ └──────────────────┘ └──────────────────┘    │
│                                                                     │
│  Directories (precedence: workspace > user > bundled):             │
│  ├── bundled:   src/rumi/skills/bundled/                       │
│  ├── user:      ~/.rumi/skills/                                │
│  └── workspace: <project>/.rumi/skills/                        │
└─────────────────────────────────────────────────────────────────────┘
```

## Memory Layer

```
┌─────────────────────────────────────────────────────────────────────┐
│                         MEMORY LAYER                                 │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                     MemoryManager                             │   │
│  │  - load_all(): Load facts from storage                        │   │
│  │  - format_for_prompt(): Generate <memory> block               │   │
│  │  - extract_from_conversation(): Auto-extract at session end   │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│              ┌───────────────┼───────────────┐                       │
│              ▼               ▼               ▼                       │
│  ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────────┐ │
│  │   MemoryStore    │ │  FactExtractor   │ │   Memory Tools       │ │
│  │   (SQLite)       │ │  (LLM-based)     │ │ remember / forget    │ │
│  └──────────────────┘ └──────────────────┘ └──────────────────────┘ │
│           │                                                          │
│           ▼                                                          │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │        ~/.rumi/memory.db (persistent facts)               │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  Data Flow:                                                          │
│  1. Facts loaded at agent start → injected into system prompt       │
│  2. User: "recuerda que trabajo en Google" → remember tool          │
│  3. Session end → FactExtractor extracts new facts automatically    │
└─────────────────────────────────────────────────────────────────────┘
```

## File Layout

```
src/rumi/
├── __init__.py
├── main.py              # Entry point
├── cli.py               # CLI interface
├── logging.py           # JSONL structured logging
├── agent/
│   ├── __init__.py
│   ├── loop.py          # Think-Act-Observe cycle
│   └── prompt.py        # System prompt builder
├── memory/
│   ├── __init__.py
│   ├── extractor.py     # LLM-based fact extraction
│   ├── manager.py       # MemoryManager orchestrator
│   ├── models.py        # Fact dataclass
│   ├── store.py         # SQLite storage (MemoryStore)
│   └── tools.py         # RememberTool, ForgetTool
├── sandbox/
│   ├── __init__.py
│   └── manager.py       # Docker container lifecycle
├── session/
│   ├── __init__.py
│   └── manager.py       # Per-chat state & locks
├── skills/
│   ├── __init__.py
│   ├── base.py          # Skill, SkillMetadata, SkillContext
│   ├── cli.py           # rumi skills subcommands
│   ├── code_skill.py    # CodeSkill loader
│   ├── config.py        # SkillsConfig, load/save
│   ├── executor_tool.py # SkillExecutorTool (use_skill)
│   ├── llm_client.py    # GroqLLMClient for CodeSkills
│   ├── manager.py       # SkillManager
│   ├── parser.py        # SKILL.md frontmatter parser
│   ├── prompt_skill.py  # PromptSkill implementation
│   └── bundled/         # Built-in skills
│       ├── explain/
│       │   └── SKILL.md
│       └── summarize/
│           └── SKILL.md
├── telegram/
│   ├── __init__.py
│   └── bot.py           # Telegram bot integration
└── tools/
    ├── __init__.py
    ├── base.py          # Tool/ToolResult base classes
    ├── registry.py      # Tool dispatch
    ├── bash.py          # Sandboxed bash execution
    └── web_fetch.py     # SSRF-protected HTTP fetch
```
