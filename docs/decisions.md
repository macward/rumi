# Architecture Decision Records

## ADR-001: Docker for Command Sandboxing

**Status**: Accepted
**Date**: 2026-02

### Context
Rumi needs to execute arbitrary user commands safely. Options considered:
1. chroot jails
2. Linux namespaces directly
3. Docker containers
4. Firecracker microVMs

### Decision
Use Docker containers with strict security flags.

### Rationale
- **docker-py**: Mature Python SDK, well-documented
- **Familiar**: Most developers understand Docker
- **Sufficient isolation**: For educational use case, Docker isolation is adequate
- **Easy cleanup**: Containers can be removed instantly
- **Resource limits**: Built-in support for memory/CPU/PIDs limits

### Consequences
- Requires Docker daemon on host
- ~100ms overhead for container creation
- Must maintain custom runner image

---

## ADR-002: Command Allowlist over Blocklist

**Status**: Accepted
**Date**: 2026-02

### Context
Need to restrict which commands can be executed in the sandbox.

### Decision
Use explicit allowlist (`ALLOWED_COMMANDS`) instead of blocklist.

### Rationale
- **Fail-closed**: Unknown commands are blocked by default
- **Auditable**: Easy to review what's permitted
- **Defense in depth**: Even if container escapes, command restrictions apply

### Consequences
- Must explicitly add each new command
- Users may request commands not on the list
- `sh -c` requires special handling

---

## ADR-003: No Shell Interpretation (shell=False)

**Status**: Accepted
**Date**: 2026-02

### Context
Commands could be executed via `shell=True` (interpret shell syntax) or `shell=False` (direct exec).

### Decision
Always use `shell=False` with `shlex.split()` to parse commands into argv.

### Rationale
- **Prevents injection**: No shell metacharacter interpretation
- **Explicit parsing**: We control exactly what runs
- **Consistent behavior**: Same parsing rules everywhere

### Consequences
- Pipes, redirections, `&&` chains don't work
- Users must use `sh -c "..."` for shell features (validated separately)
- Some convenience lost for power users

---

## ADR-004: web_fetch Runs on Host

**Status**: Accepted
**Date**: 2026-02

### Context
The web_fetch tool needs network access. Options:
1. Run inside container with selective network
2. Run on host with SSRF protection

### Decision
Run web_fetch on the host Python process with SSRF protection.

### Rationale
- **Container stays air-gapped**: No network exceptions needed
- **SSRF protection**: Validate DNS resolution before connecting
- **Simpler networking**: No Docker network configuration

### Consequences
- Must implement thorough SSRF protection
- Host IP stack is exposed to responses
- Redirect following requires validation

---

## ADR-005: SSRF Protection via DNS Pre-Resolution

**Status**: Accepted
**Date**: 2026-02

### Context
web_fetch must not connect to internal/private IPs.

### Decision
Resolve DNS first, validate IP against blocklist, then connect.

### Rationale
- **Catches DNS rebinding**: URL host is validated at fetch time
- **Catches redirects**: Event hook validates redirect URLs
- **Comprehensive blocklist**: All RFC 1918/5735 ranges covered

### Blocked Networks
- 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
- 169.254.0.0/16 (link-local)
- 0.0.0.0/8, 100.64.0.0/10 (special)
- IPv6 equivalents (::1, fc00::/7, fe80::/10)

### Consequences
- Cannot fetch from legitimate internal services
- DNS resolution adds latency
- httpx event hooks required for redirect validation

---

## ADR-006: One Container Per Session

**Status**: Accepted
**Date**: 2026-02

### Context
How to manage container lifecycle across user sessions.

### Decision
Create one container per `chat_id`, keep alive during session, destroy on `/reset`.

### Rationale
- **Isolation**: Each user gets separate filesystem
- **Performance**: Container reuse avoids startup latency
- **Clean slate**: `/reset` gives fresh environment

### Naming Convention
`rumi-runner-{chat_id}`

### Consequences
- Must track container state per session
- Orphan containers possible if process crashes
- `cleanup_all()` needed for maintenance

---

## ADR-007: Circuit Breakers in Agent Loop

**Status**: Accepted
**Date**: 2026-02

### Context
LLM might loop infinitely calling tools.

### Decision
Implement three circuit breakers:
1. **max_turns** (10): Hard limit on iterations
2. **repeated_call** (2): Same tool call twice = stop
3. **consecutive_errors** (3): Three failures in a row = stop

### Rationale
- **Cost control**: Prevents runaway API usage
- **UX**: Better to stop than spin forever
- **Debuggable**: Stop reason is reported

### Consequences
- May stop prematurely on legitimate long tasks
- Users need to understand circuit breaker messages

---

## ADR-008: Groq + Llama 3.1 70B as LLM Backend

**Status**: Accepted
**Date**: 2026-02

### Context
Need an LLM with tool calling support.

### Decision
Use Groq API with `llama-3.1-70b-versatile` model.

### Rationale
- **Free tier**: Good for educational project
- **Fast inference**: Groq's LPU gives low latency
- **Tool calling**: Native function calling support
- **Open weights**: Llama is open source

### Consequences
- Dependent on Groq service availability
- May need to adjust prompts for model quirks
- Rate limits on free tier

---

## ADR-009: Alpine as Runner Base Image

**Status**: Accepted
**Date**: 2026-02

### Context
Need a minimal base image for the sandbox.

### Decision
Use Alpine Linux 3.19 with explicit package list.

### Rationale
- **Small size**: ~5MB base
- **Security**: Minimal attack surface
- **Explicit tools**: We install only what's needed

### Removed Tools
- wget (default in Alpine)
- curl
- nc (netcat from busybox)

### Consequences
- Must explicitly remove network tools
- Some GNU coreutils behaviors differ
- apk for package management

---

## ADR-010: JSONL Structured Logging

**Status**: Accepted
**Date**: 2026-02

### Context
Need observability for debugging and auditing.

### Decision
Use JSONL format for all logs with structured fields.

### Fields
- `container_id`, `chat_id`
- `argv`, `command`
- `exit_code`, `duration_ms`
- `truncated`, `stopped_reason`

### Rationale
- **Parseable**: Easy to grep, jq, analyze
- **Structured**: Fields are consistent
- **Auditable**: Full command history

### Consequences
- Logs are not human-readable without tooling
- Must ensure no sensitive data in logs

---

## ADR-011: Skills System with Two Skill Types

**Status**: Accepted
**Date**: 2026-02

### Context
Need extensibility mechanism for complex tasks that go beyond single tool calls.

### Decision
Implement two skill types:
1. **PromptSkill**: SKILL.md only - injects instructions into conversation
2. **CodeSkill**: SKILL.md + skill.py - programmatic orchestration

### Rationale
- **PromptSkill simplicity**: Non-programmers can create skills with markdown
- **CodeSkill power**: Developers can orchestrate tools and LLM calls
- **Unified metadata**: Both types share SKILL.md frontmatter format
- **Progressive complexity**: Start with PromptSkill, upgrade to CodeSkill when needed

### Consequences
- Must maintain two loading paths
- CodeSkill requires dynamic module loading (importlib)
- skill.py class name must match pattern: `{Name}Skill`

---

## ADR-012: Three-Tier Skill Discovery

**Status**: Accepted
**Date**: 2026-02

### Context
Skills should be customizable at project, user, and system levels.

### Decision
Load skills from three directories with increasing precedence:
1. **bundled** (lowest): Package-included skills
2. **user** (medium): ~/.rumi/skills/
3. **workspace** (highest): Project-specific

### Rationale
- **Override mechanism**: User can customize bundled skills
- **Project isolation**: Workspace skills don't affect other projects
- **No merge conflicts**: Higher priority replaces, doesn't merge

### Consequences
- Must track source of each skill
- Same skill name in multiple dirs = only highest priority loaded
- Refresh must re-scan all directories

---

## ADR-013: mtime-Based Skill Cache

**Status**: Accepted
**Date**: 2026-02

### Context
Scanning directories and parsing SKILL.md on every request is wasteful.

### Decision
Track mtime of SKILL.md files and only reload when changed.

### Implementation
- `_mtimes: dict[str, float]` - cached modification times
- `_skill_paths: dict[str, Path]` - skill directory paths
- `refresh_changed()` - only reload modified skills
- `clear_cache()` - full cache invalidation

### Rationale
- **Performance**: Avoid reparsing unchanged files
- **Development friendly**: Changes detected automatically
- **Simple invalidation**: mtime comparison is reliable

### Consequences
- Cache state must be cleaned on unregister
- Deleted skills detected via missing SKILL.md
- stat() calls on refresh (minimal overhead)

---

## ADR-014: tools_required Validation

**Status**: Accepted
**Date**: 2026-02

### Context
Skills may depend on specific tools being available.

### Decision
Validate `tools_required` against ToolRegistry before execution.

### Implementation
- SKILL.md frontmatter: `tools_required: [bash, custom_tool]`
- `get_missing_tools(name, available)` returns missing tool names
- `execute()` returns error if tools missing

### Rationale
- **Fail-fast**: Clear error instead of runtime failure
- **Documentation**: tools_required serves as documentation
- **Discoverability**: CLI can show dependencies

### Consequences
- Must pass available tools list to validation
- PromptSkills can't enforce at runtime (instructions only)
- Tests must mock tool availability

---

## ADR-015: Skills CLI for Management

**Status**: Accepted
**Date**: 2026-02

### Context
Need user-friendly way to manage skills.

### Decision
Add `rumi skills` subcommand with list/enable/disable/info/create.

### Commands
```
rumi skills list [-a/--all]
rumi skills enable <name>
rumi skills disable <name>
rumi skills info <name>
rumi skills create <name> [--code] [-d DESC]
```

### Rationale
- **Discoverability**: Users can see what's available
- **Runtime config**: Enable/disable without editing files
- **Scaffolding**: create generates proper structure

### Consequences
- Config persistence via save_config()
- Skill names must follow validation rules
- CLI has no access to runtime ToolRegistry

---

## ADR-016: Two-Layer Memory System

**Status**: Accepted
**Date**: 2026-02

### Context
Need to remember information about users across sessions and within sessions.

### Decision
Implement two memory layers:
1. **Session Memory**: Temporary conversation history per chat_id
2. **Facts Memory**: Persistent key-value facts about the user

### Rationale
- **Session memory**: Enables context within a conversation
- **Facts memory**: Enables long-term personalization
- **Separation**: Different persistence needs (TTL vs permanent)

### Consequences
- Two storage backends (JSON files vs SQLite)
- Must coordinate extraction at session end
- Memory block injected into every system prompt

---

## ADR-017: SQLite for Facts Storage

**Status**: Accepted
**Date**: 2026-02

### Context
Need persistent storage for user facts with deduplication.

### Decision
Use SQLite with `UNIQUE(key, value)` constraint.

### Schema
```sql
CREATE TABLE facts (
    id          INTEGER PRIMARY KEY,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    source      TEXT DEFAULT 'auto',
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(key, value)
)
```

### Rationale
- **Deduplication**: Natural with UNIQUE constraint
- **No dependencies**: sqlite3 is built into Python
- **Query flexibility**: Can filter by key, search, etc.
- **Upsert support**: ON CONFLICT for timestamp updates

### Consequences
- Single user only (no chat_id partitioning)
- Database file at `~/.rumi/memory.db`
- Must handle connection lifecycle

---

## ADR-018: LLM-Based Fact Extraction

**Status**: Accepted
**Date**: 2026-02

### Context
Need to automatically learn about users from conversations.

### Decision
Use LLM to extract stable facts at session end via `FactExtractor`.

### Extraction Rules
- Only **stable facts** (not temporary states)
- Values in **third person** ("works at Google")
- Dynamic keys in Spanish (nombre, trabajo, preferencia...)
- Low temperature (0.1) for consistency

### Rationale
- **Automatic**: No user action required
- **Intelligent**: LLM understands context
- **Flexible keys**: Not limited to predefined categories

### Consequences
- Additional LLM call at session end
- May extract incorrect or irrelevant facts
- JSON parsing required for response

---

## ADR-019: Explicit Memory Tools (remember/forget)

**Status**: Accepted
**Date**: 2026-02

### Context
Users should be able to explicitly control what is remembered.

### Decision
Provide `remember` and `forget` tools for explicit management.

### Tools
```python
remember(key="nombre", value="se llama Juan")  # source='explicit'
forget(key="trabajo")  # deletes all facts with that key
```

### Rationale
- **User control**: Can correct or remove facts
- **Trust**: User knows what's stored
- **Explicit source**: Distinguishes from auto-extracted

### Consequences
- Two additional tools in ToolRegistry
- ForgetTool deletes ALL facts with matching key
- No confirmation prompt on forget

---

## ADR-020: Memory Block in System Prompt

**Status**: Accepted
**Date**: 2026-02

### Context
The agent needs access to stored facts about the user.

### Decision
Inject facts as XML block at start of system prompt.

### Format
```xml
<memory>
Lo que sabés del usuario:
- nombre: se llama Juan
- trabajo: trabaja en Google
</memory>
```

### Rationale
- **Always available**: Part of every conversation
- **Structured**: Easy for LLM to parse
- **Contextual**: Spanish phrasing matches agent persona

### Consequences
- Increases prompt size with each fact
- Must limit facts to avoid token bloat
- No semantic search (all facts included)
