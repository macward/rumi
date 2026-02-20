# Rumi Project Memory

## Project Status

**Current Phase**: 5 of 5 - Telegram Integration (Complete)
**Tests**: 139 passing
**Version**: 0.1.0

### Phase Completion
- [x] Phase 1: Core + Parser - Agent loop, CLI, logging
- [x] Phase 2: Docker Sandbox - rumi-runner image, SandboxManager
- [x] Phase 3: web_fetch - SSRF-protected HTTP fetch
- [x] Phase 4: Sessions - Per-chat state and locks
- [x] Phase 5: Telegram - Bot with /stop, /reset commands

## Quick Reference

See detailed docs in `docs/`:
- `docs/architecture.md` - System diagrams and data flow
- `docs/decisions.md` - Architecture Decision Records (ADRs)

## Key Patterns

### Docker SDK (docker-py)
- Use `containers.run()` with `detach=True` for long-running containers
- Call `container.reload()` before checking status (may be 'created' initially)
- Security: `read_only=True`, `cap_drop=["ALL"]`, `network_mode="none"`
- Mount writable workspace with tmpfs for /tmp when using read-only root

### Groq API
- Use `AsyncGroq` for async operations
- Tool calls: `assistant_message.tool_calls`
- Arguments need `json.loads(tool_call.function.arguments)`

### pytest-asyncio
- `@pytest.mark.asyncio` for async tests
- `monkeypatch.setenv()` for env vars
- Real Docker tests ~1 min total - mock where possible

### SSRF Protection
- Resolve DNS first, validate IP before connecting
- Block: 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16
- Use `socket.getaddrinfo()` for DNS resolution

### Alpine Docker
- Has wget by default - must explicitly remove
- busybox provides nc - remove if no network needed
- Use `apk add --no-cache` to avoid cache bloat

## Gotchas
- `pyproject.toml` with `readme = "README.md"` fails if file doesn't exist
- Alpine example.com may not resolve - use httpbin.org for tests
- python-telegram-bot v21+ uses async Application pattern

## In Progress / TODOs
- None currently - core implementation complete
- Potential future: persistent sessions, more tools, rate limiting
