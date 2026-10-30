"""
Shell Tool — Executes only pre-approved, safe shell commands.
All other commands are blocked for security.
"""
import subprocess
import shlex
import re

from app.core.logging import logger

# Strict allowlist — only these command prefixes are permitted
ALLOWED_COMMANDS = [
    "df -h", "df -H",
    "free -h", "free -m",
    "uptime",
    "ps aux",
    "netstat -tlnp",
    "ss -tlnp",
    "systemctl status",
    "journalctl -n",
    "cat /var/log/syslog",
    "echo",
    "hostname",
    "uname -a",
    "date",
    "whoami",
    "ls -la",
    "pwd",
]


_SENSITIVE_COMMAND_PATTERNS = [
    re.compile(r"(gh[pousr]_|github_pat_)[A-Za-z0-9_]+", re.IGNORECASE),
    re.compile(r"(Bearer\s+)[^\s\"']+", re.IGNORECASE),
    re.compile(
        r"(?i)((?:token|secret|api[_-]?key|password|credential|access[_-]?key)\s*[:=]\s*)"
        r"(?:\"[^\"]*\"|'[^']*'|[^\s\"']+)"
    ),
]


def _redact_command_for_log(command: str) -> str:
    """Redact token-like values before writing shell commands to logs."""
    redacted = command
    for pattern in _SENSITIVE_COMMAND_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", redacted)
    return redacted[:200]


def _is_allowed(command: str) -> bool:
    """Validate complete argv; prefix matching permits extra privileged flags."""
    if not isinstance(command, str) or len(command) > 2000:
        return False
    if any(character in command for character in "\n\r\x00;|&><`$"):
        return False
    try:
        args = shlex.split(command)
    except ValueError:
        return False
    if not args:
        return False
    if args[0] == "echo":
        return True  # Literal argv only, never shell expansion.
    if args[:2] == ["journalctl", "-n"]:
        return len(args) == 3 and bool(re.fullmatch(r"[0-9]{1,4}", args[2])) and 1 <= int(args[2]) <= 1000
    if args[:2] == ["systemctl", "status"]:
        return len(args) == 3 and bool(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@-]{0,127}", args[2]))
    return args in [shlex.split(allowed) for allowed in ALLOWED_COMMANDS
                    if allowed not in {"echo", "journalctl -n", "systemctl status"}]


def execute_safe_shell_command(command: str) -> str:
    """
    Execute a pre-approved shell command.
    Rejects any command not in the allowlist.
    """
    if not _is_allowed(command):
        logger.warning("shell.blocked", command_preview=_redact_command_for_log(str(command)))
        return (
            f"🚫 Command blocked: '{_redact_command_for_log(str(command))}'\n"
            f"Only the following commands are permitted:\n"
            + "\n".join(f"  - {c}" for c in ALLOWED_COMMANDS)
        )
    try:
        logger.info("shell.execute", command_preview=_redact_command_for_log(command))
        args = shlex.split(command)
        if args[0] in {"systemctl", "journalctl"}:
            args.append("--no-pager")
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout or result.stderr
        return _redact_output(output.strip()) or "(command produced no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds."
    except Exception as e:
        logger.warning("shell.failed", error_type=e.__class__.__name__)
        return "Error executing command. Check the audit log for details."


def _redact_output(output: str) -> str:
    for pattern in _SENSITIVE_COMMAND_PATTERNS:
        output = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]", output)
    return output
