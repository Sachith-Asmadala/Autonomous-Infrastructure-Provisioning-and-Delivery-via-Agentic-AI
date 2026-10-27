# backend/app/agents/tools_registry.py
"""
DevOps Tools Registry
Registers all LangChain tools available to the agent.
Tools are filtered based on user role / RBAC.
HIGH/CRITICAL risk tools are wrapped with a HITL check that raises
`HITLApprovalRequired` instead of executing directly.
"""
from __future__ import annotations

from langchain.tools import StructuredTool

from app.tools.docker_tool import (
    get_container_logs, list_containers, restart_container,
    run_container, start_container, stop_container,
)
from app.tools.github_tool import (
    get_repo_info, get_workflow_run_status, list_recent_runs,
    list_workflows, trigger_workflow,
)
from app.tools.monitoring_tool import (
    check_multiple_services, get_process_list,
    get_service_health, get_system_metrics,
)
from app.tools.shell_tool import execute_safe_shell_command


class HITLApprovalRequired(Exception):
    """
    Raised by a high-risk tool wrapper when HITL is enabled.

    The agent route catches this and persists an ApprovalRequest
    instead of executing the tool.
    """

    def __init__(self, tool_name: str, tool_input: dict, risk_level: str, summary: str):
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.risk_level = risk_level
        self.summary = summary
        super().__init__(
            f"HITL approval required for {tool_name} ({risk_level}): {summary}"
        )


def _hitl_wrap(func, tool_name: str, risk_level: str, summary_template: str):
    """
    Wrap a tool function to raise HITLApprovalRequired when HITL is enabled.
    """
    def _wrapped(**kwargs):
        from app.core.config import settings

        if settings.ENABLE_HITL:
            summary = summary_template.format(**kwargs)
            raise HITLApprovalRequired(
                tool_name=tool_name,
                tool_input=kwargs,
                risk_level=risk_level,
                summary=summary,
            )
        return func(**kwargs)

    _wrapped.__name__ = func.__name__
    _wrapped.__doc__ = func.__doc__
    return _wrapped


# ── Wrapped high-risk tools ───────────────────────────────────────────────────

_stop_container_hitl = _hitl_wrap(
    stop_container,
    tool_name="docker_stop_container",
    risk_level="high",
    summary_template="Stop container '{container_name}'",
)

_start_container_hitl = _hitl_wrap(
    start_container,
    tool_name="docker_start_container",
    risk_level="medium",
    summary_template="Start container '{container_name}'",
)

_restart_container_hitl = _hitl_wrap(
    restart_container,
    tool_name="docker_restart_container",
    risk_level="medium",
    summary_template="Restart container '{container_name}'",
)

_run_container_hitl = _hitl_wrap(
    run_container,
    tool_name="docker_run_container",
    risk_level="high",
    summary_template="Run new container '{name}' from image '{image}'",
)

_shell_command_hitl = _hitl_wrap(
    execute_safe_shell_command,
    tool_name="execute_shell_command",
    risk_level="high",
    summary_template="Execute allowlisted shell command '{command}'",
)

_trigger_workflow_hitl = _hitl_wrap(
    trigger_workflow,
    tool_name="github_trigger_workflow",
    risk_level="critical",
    summary_template="Trigger workflow '{workflow_id}' on '{ref}' in '{repo_full_name}'",
)


# ── Tool registry ─────────────────────────────────────────────────────────────

def get_all_tools(user_role: str = "developer") -> list:
    """Return tools available to the given user role.

    Developers receive read-only tools plus lower-risk development/staging
    remediation. Admins get
    elevated tools, with high/critical operations still gated by HITL.
    """
    normalized_role = (user_role or "").lower()

    read_only_tools = [
        # Docker — read-only
        StructuredTool.from_function(
            func=list_containers,
            name="docker_list_containers",
            description="List running Docker containers with status, ports, and names. Read-only.",
        ),
        StructuredTool.from_function(
            func=get_container_logs,
            name="docker_get_logs",
            description=(
                "Retrieve logs from a Docker container. Provide container_name and optional tail_lines. Read-only."
            ),
        ),
        # GitHub — read-only
        StructuredTool.from_function(
            func=list_workflows,
            name="github_list_workflows",
            description="List GitHub Actions workflows in a repository. Read-only.",
        ),
        StructuredTool.from_function(
            func=get_workflow_run_status,
            name="github_workflow_status",
            description="Get the status of a specific GitHub Actions workflow run by run_id. Read-only.",
        ),
        StructuredTool.from_function(
            func=list_recent_runs,
            name="github_recent_runs",
            description="Get the most recent workflow runs with their status and conclusions. Read-only.",
        ),
        StructuredTool.from_function(
            func=get_repo_info,
            name="github_repo_info",
            description="Get metadata about a GitHub repository. Read-only.",
        ),
        # Monitoring — read-only
        StructuredTool.from_function(
            func=get_system_metrics,
            name="get_system_metrics",
            description="Get current system metrics: CPU, memory, disk, load average, and network I/O. Read-only.",
        ),
        StructuredTool.from_function(
            func=get_service_health,
            name="get_service_health",
            description="Check the health status of a service by HTTP URL. Read-only.",
        ),
        StructuredTool.from_function(
            func=get_process_list,
            name="get_process_list",
            description="List top processes sorted by cpu or memory usage. Read-only.",
        ),
        StructuredTool.from_function(
            func=check_multiple_services,
            name="check_multiple_services",
            description="Health-check multiple service URLs in parallel. Read-only.",
        ),
    ]

    developer_tools = [
        StructuredTool.from_function(
            func=_restart_container_hitl,
            name="docker_restart_container",
            description=(
                "Restart a Docker container by name for development/staging self-healing. "
                "MEDIUM RISK: requires HITL approval before execution."
            ),
        ),
    ]

    # Admin-only tools — high/critical risk, wrapped with HITL gate
    elevated_tools = [
        StructuredTool.from_function(
            func=_trigger_workflow_hitl,
            name="github_trigger_workflow",
            description=(
                "Trigger a GitHub Actions workflow_dispatch event. "
                "CRITICAL RISK: requires HITL approval before execution."
            ),
        ),
        StructuredTool.from_function(
            func=_start_container_hitl,
            name="docker_start_container",
            description="Start a stopped Docker container. MEDIUM RISK: requires HITL approval.",
        ),
        StructuredTool.from_function(
            func=_stop_container_hitl,
            name="docker_stop_container",
            description=(
                "Stop a running Docker container. "
                "HIGH RISK in production — requires HITL approval."
            ),
        ),
        StructuredTool.from_function(
            func=_run_container_hitl,
            name="docker_run_container",
            description=(
                "Run a new Docker container from an image. "
                "HIGH RISK — requires HITL approval."
            ),
        ),
        StructuredTool.from_function(
            func=_shell_command_hitl,
            name="execute_shell_command",
            description=(
                "Execute a safe, allowlisted shell command on the server. "
                "HIGH RISK: requires HITL approval and only pre-approved commands are permitted."
            ),
        ),
    ]

    if normalized_role == "developer":
        return read_only_tools + developer_tools
    if normalized_role == "admin":
        return read_only_tools + developer_tools + elevated_tools
    return []
