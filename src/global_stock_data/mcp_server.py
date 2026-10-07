"""Optional SDK-v2 local stdio facade; pure tools, no URLs/paths/accounts."""

import json
from typing import Any

from . import __version__
from .errors import DataError, require
from .research import dispatch

TOOL_ALLOWLIST = ("what_if", "research_dossier")


def bounded_dispatch(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    require(tool in TOOL_ALLOWLIST, "Tool is not allowlisted", "tool_denied")
    require(
        len(json.dumps(arguments, allow_nan=False).encode()) <= 100_000,
        "Tool input too large",
        "input",
    )
    result = dispatch(tool, arguments)
    require(
        len(json.dumps(result, allow_nan=False).encode()) <= 200_000,
        "Tool output too large",
        "input",
    )
    return result


def create_server() -> Any:
    try:
        from mcp.server import MCPServer
        from mcp_types import ToolAnnotations
    except ImportError as exc:
        raise DataError(
            "capability_unavailable", "Optional pinned mcp extra is not installed"
        ) from exc
    server: Any = MCPServer("global-stock-data-research", version=__version__, subscriptions=False)
    annotations = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, open_world_hint=False
    )

    def what_if(
        weights: dict[str, float], shocks: dict[str, float], max_weight: float = 1
    ) -> dict[str, Any]:
        """Compute a synthetic static-weight scenario; no prediction or execution."""
        return bounded_dispatch(
            "what_if", {"weights": weights, "shocks": shocks, "max_weight": max_weight}
        )

    def research_dossier(
        request: dict[str, Any],
        evidence: list[dict[str, Any]],
        claims: list[dict[str, Any]],
        now: str,
        max_age_seconds: float = 86400,
    ) -> dict[str, Any]:
        """Validate supplied evidence and render readiness; no data fetch or storage."""
        return bounded_dispatch(
            "research_dossier",
            {
                "request": request,
                "evidence": evidence,
                "claims": claims,
                "now": now,
                "max_age_seconds": max_age_seconds,
            },
        )

    server.add_tool(what_if, annotations=annotations)
    server.add_tool(research_dossier, annotations=annotations)
    return server


def main() -> None:
    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
