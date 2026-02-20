# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Rumi is an educational personal server assistant that executes real tools safely using Docker sandboxing. It's an AI agent (chatbot) that runs bash commands inside isolated containers.

## Architecture

```
Input (CLI/Telegram) → Agent Loop → ToolRegistry → SandboxManager → Docker Container
                         ↓
                    LLM (Groq API)
```

### Core Components
- **Agent Loop**: think → act → observe cycle with circuit breakers
- **SandboxManager**: Creates/destroys Docker containers per session (`rumi-runner-{chat_id}`)
- **ToolRegistry**: Manages available tools (bash, web_fetch)
- **SessionManager**: Handles per-session state and locks

### Execution Model
- One active execution per `chat_id` (session lock)
- Concurrent messages return: "⏳ ya estoy trabajando"
- Container created on-demand, destroyed on session expiry or `/reset`

### Docker Sandbox Security Flags
```
--read-only --cap-drop=ALL --security-opt=no-new-privileges
--pids-limit=128 --cpus=1 --memory=512m
--user=1000:1000 --workdir=/workspace --network=none
```

### Workspace
Per-session volume mount: `~/.rumi/workspace/{chat_id}` → `/workspace`

## Tools

### bash tool
- Executed via `docker exec`
- Parsed with `shlex.split()`, `shell=False`
- **No support for**: pipes, redirections, `&&`, `;`
- Strict allowlist validation
- Hard timeout

### web_fetch
- Runs on host (not in container)
- SSRF blocking: loopback, private IPs, link-local
- Byte limit and timeout

## Circuit Breakers

Loop stops when:
- Same tool_call repeated 2 times
- 3 consecutive errors
- max_turns reached

## Observability

JSONL logs with: `container_id`, `argv`, duration, `exit_code`, `truncated`, `stopped_reason`

## Development Phases

1. **Core + Parser** - Stable loop, CLI, logs
2. **Docker Sandbox** - rumi-runner image, SandboxManager, bash via docker exec
3. **web_fetch seguro** - SSRF-protected fetch
4. **Sessions persistentes** - Persistent session storage
5. **Telegram** - Bot integration with /stop, /reset commands

## Key Design Decisions

- Container has no network access
- No curl in the runner image
- No `bash -c` (prevents shell injection)
- Unique workspace per session
- File operations via container commands (cat, tee) not separate tools

## Vibe Workspace

vibe: rumi
