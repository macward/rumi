"""Bash tool for executing commands in the sandbox."""

import re
import shlex
from typing import Any

from ..sandbox import SandboxManager
from .base import Tool, ToolResult


# Commands allowed to execute (verified to exist in miniclaw-runner image)
ALLOWED_COMMANDS = frozenset({
    # File operations
    "ls", "cat", "head", "tail", "less", "more",
    "cp", "mv", "rm", "mkdir", "rmdir", "touch",
    "find", "which",  # locate/whereis not installed
    "stat", "du", "df",  # file not installed
    # Text processing
    "grep", "egrep", "fgrep", "sed", "awk", "gawk",
    "cut", "sort", "uniq", "wc", "tr", "tee",
    "diff", "comm", "join", "paste",
    # File content
    "echo", "printf", "yes",
    "base64", "md5sum", "sha256sum",
    # Directory navigation (cd is builtin, use sh -c if needed)
    "pwd", "basename", "dirname", "realpath",
    # Utilities
    "date", "cal", "expr", "seq", "sleep",
    "true", "false", "test", "[",
    "env", "printenv", "id", "whoami",
    # Compression
    "tar", "gzip", "gunzip", "zcat",
    # Shell (for sh -c 'command')
    "sh",
})

# Patterns that indicate shell metacharacters we don't allow
FORBIDDEN_PATTERNS = [
    r"\|",      # Pipes
    r"&&",      # AND operator
    r"\|\|",    # OR operator
    r";",       # Command separator
    r">",       # Output redirection
    r"<",       # Input redirection
    r">>",      # Append redirection
    r"\$\(",    # Command substitution
    r"`",       # Backtick substitution
    r"\$\{",    # Variable expansion with braces
]


class BashTool(Tool):
    """Tool for executing bash commands in a sandboxed container."""

    def __init__(
        self,
        sandbox: SandboxManager,
        timeout: int = 30,
        max_output_chars: int = 50_000,
    ) -> None:
        self._sandbox = sandbox
        self._timeout = timeout
        self._max_output = max_output_chars

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return (
            "Execute a bash command in a sandboxed container. "
            "The container has no network access and limited resources. "
            "Files persist in /workspace during the session."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "The command to execute. Must be a simple command without pipes, "
                        "redirections, or chained commands. Examples: 'ls -la', 'cat file.txt', "
                        "'mkdir mydir', 'echo hello > file.txt' is NOT allowed."
                    ),
                },
            },
            "required": ["command"],
        }

    def _validate_command(self, command: str) -> tuple[bool, str | None]:
        """Validate command against security rules.

        Returns (valid, error_message).
        """
        # Check for forbidden patterns
        for pattern in FORBIDDEN_PATTERNS:
            if re.search(pattern, command):
                return False, f"Shell operators not allowed: {pattern}"

        # Parse command to get argv
        try:
            argv = shlex.split(command)
        except ValueError as e:
            return False, f"Invalid command syntax: {e}"

        if not argv:
            return False, "Empty command"

        # Check if command is in allowlist
        base_cmd = argv[0]
        if base_cmd not in ALLOWED_COMMANDS:
            return False, f"Command not allowed: {base_cmd}"

        # Special handling for sh -c
        if base_cmd == "sh" and len(argv) >= 3 and argv[1] == "-c":
            # For sh -c, we need to validate the inner command too
            inner_cmd = argv[2]

            # Check inner command for forbidden patterns
            for pattern in FORBIDDEN_PATTERNS:
                if re.search(pattern, inner_cmd):
                    return False, f"Shell operators not allowed in sh -c: {pattern}"

            # Parse inner command to check base command
            try:
                inner_argv = shlex.split(inner_cmd)
                if inner_argv and inner_argv[0] not in ALLOWED_COMMANDS:
                    return False, f"Command not allowed in sh -c: {inner_argv[0]}"
            except ValueError:
                # If we can't parse, be conservative
                pass

        return True, None

    async def execute(self, command: str, chat_id: str | None = None) -> ToolResult:
        """Execute a command in the sandbox."""
        # Validate command
        valid, error = self._validate_command(command)
        if not valid:
            return ToolResult(
                success=False,
                output="",
                error=error,
            )

        # Parse to argv
        try:
            argv = shlex.split(command)
        except ValueError as e:
            return ToolResult(
                success=False,
                output="",
                error=f"Failed to parse command: {e}",
            )

        # Use default chat_id if not provided
        if chat_id is None:
            chat_id = "default"

        # Execute in sandbox
        result = await self._sandbox.exec_command(
            chat_id=chat_id,
            argv=argv,
            timeout=self._timeout,
        )

        # Truncate output if needed
        output = result.output
        truncated = result.truncated
        if len(output) > self._max_output:
            output = output[: self._max_output] + "\n... [output truncated]"
            truncated = True

        # Determine success
        success = result.exit_code == 0

        return ToolResult(
            success=success,
            output=output,
            error=f"Exit code: {result.exit_code}" if not success else None,
            metadata={
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "truncated": truncated,
            },
        )
