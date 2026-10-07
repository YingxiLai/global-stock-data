"""Local stdio tools; data access is fixed by operator startup, never model input."""

import argparse
import json
import os
from pathlib import Path
from typing import Any, cast

from . import __version__
from .adapters import CAPABILITIES, fetch
from .errors import DataError, require
from .http import Client
from .records import number
from .research import dispatch

PURE_TOOLS = ("what_if", "research_dossier")
TOOL_ALLOWLIST = (*PURE_TOOLS, "research_fetch")
READ_PROVIDERS = ("sec", "treasury", "cftc")


def json_bound(value: Any, maximum: int, message: str) -> None:
    try:
        size = len(json.dumps(value, allow_nan=False).encode())
    except (TypeError, ValueError, RecursionError) as exc:
        raise DataError("input", "Finite JSON input/output required") from exc
    require(size <= maximum, message, "input")


def read_input(capability: Any, arguments: Any, limit: Any) -> None:
    require(
        isinstance(capability, str) and 0 < len(capability) <= 80 and isinstance(arguments, dict),
        "Read capability and argument object must be bounded",
        "input",
    )
    require(type(limit) is int and 1 <= limit <= 100, "Read output bounded to 100 records", "input")
    json_bound(
        {"capability": capability, "arguments": arguments, "limit": limit},
        10_000,
        "Read input too large",
    )


def bounded_dispatch(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    require(tool in PURE_TOOLS, "Tool is not a pure allowlisted tool", "tool_denied")
    json_bound(arguments, 100_000, "Tool input too large")
    result = dispatch(tool, arguments)
    json_bound(result, 200_000, "Tool output too large")
    return result


def bounded_fetch(
    capability: str,
    arguments: dict[str, Any],
    *,
    limit: int = 20,
    client: Client | None = None,
    allowed_providers: tuple[str, ...] = (),
) -> dict[str, Any]:
    read_input(capability, arguments, limit)
    provider = CAPABILITIES.get(capability)
    if client is None or provider not in allowed_providers:
        denied = {
            "schema_version": "1.0",
            "capability": capability,
            "data_status": "permission_blocked",
            "records": [],
            "issues": [
                {
                    "code": "operator_policy",
                    "retryable": False,
                    "message": "Provider was not enabled by the operator at startup",
                }
            ],
        }
        json_bound(denied, 200_000, "Read result exceeds safe response bound")
        return denied
    result = fetch(client, capability, arguments)
    records = result["records"]
    truncated = len(records) > limit
    # Keep scope/provenance metadata without duplicating all retrieved rows or
    # allowing the model to read a cache path. No arbitrary continuation URL.
    output = {
        **result,
        "records": records[:limit],
        "source_metadata": {
            key: value
            for key, value in result.get("source_metadata", {}).items()
            if key not in ("rows", "row_provenance", "historical_files")
        },
        "available_in_bounded_fetch": len(records),
        "returned_count": min(limit, len(records)),
        "output_truncated": truncated,
        "data_status": "partial"
        if truncated and result["data_status"] == "ok"
        else result["data_status"],
    }
    json_bound(output, 200_000, "Read result exceeds safe response bound")
    return output


def create_server(
    *, read_client: Client | None = None, allowed_providers: tuple[str, ...] = ()
) -> Any:
    require(
        set(allowed_providers) <= set(READ_PROVIDERS)
        and (not allowed_providers or read_client is not None),
        "Invalid operator provider configuration",
        "config",
    )
    allowed_providers = tuple(allowed_providers)
    try:
        from mcp.server import MCPServer
        from mcp.server.mcpserver.exceptions import ToolError
        from mcp_types import ToolAnnotations
    except ImportError as exc:
        raise DataError(
            "capability_unavailable", "Optional pinned mcp extra is not installed"
        ) from exc
    fields = {
        "what_if": {"weights", "shocks", "max_weight"},
        "research_dossier": {"request", "evidence", "claims", "now", "max_age_seconds"},
        "research_fetch": {"capability", "arguments", "limit"},
    }

    server: Any = MCPServer("global-stock-data-research", version=__version__, subscriptions=False)
    original_call = server.call_tool

    async def strict_call(name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        if name not in fields or not isinstance(arguments, dict) or set(arguments) - fields[name]:
            raise ToolError("Unknown tool or undeclared arguments rejected")
        try:
            json_bound(arguments, 100_000, "Tool input too large")
            if name == "research_fetch":
                read_input(
                    arguments.get("capability"),
                    arguments.get("arguments"),
                    arguments.get("limit", 20),
                )
            elif name == "what_if":
                for key in ("weights", "shocks"):
                    values = arguments.get(key)
                    require(isinstance(values, dict), "Scenario numeric maps required", "input")
                    for value in cast(dict[str, Any], values).values():
                        require(number(value) is not None, "Scenario numbers required", "input")
                require(
                    number(arguments.get("max_weight", 1)) is not None,
                    "Concentration number required",
                    "input",
                )
            else:
                require(
                    number(arguments.get("max_age_seconds", 86400)) is not None,
                    "Freshness number required",
                    "input",
                )
        except DataError as exc:
            raise ToolError(str(exc)) from exc
        return await original_call(name, arguments, context)

    # Validate the pinned SDK public call boundary before argument coercion.
    server.call_tool = strict_call
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

    def research_fetch(
        capability: str, arguments: dict[str, Any], limit: int = 20
    ) -> dict[str, Any]:
        """Read one fixed research capability within operator policy; no model online/URL/path/credentials."""
        return bounded_fetch(
            capability,
            arguments,
            limit=limit,
            client=read_client,
            allowed_providers=allowed_providers,
        )

    server.add_tool(
        research_fetch,
        annotations=ToolAnnotations(
            read_only_hint=True,
            destructive_hint=False,
            open_world_hint=bool(read_client is not None and read_client.online),
        ),
    )
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Operator-scoped research MCP (stdio only)")
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--provider", choices=READ_PROVIDERS, action="append", default=[])
    parser.add_argument("--state-dir", type=Path)
    args = parser.parse_args()
    require(
        (args.online and bool(args.provider) and args.state_dir is not None)
        or (not args.online and not args.provider and args.state_dir is None),
        "Online startup needs explicit provider(s) and private state-dir; default is offline",
        "config",
    )
    client = None
    if args.online:
        from .http import validate_sec_contact

        contact = os.environ.get("SEC_CONTACT", "") if "sec" in args.provider else None
        if "sec" in args.provider:
            validate_sec_contact(contact or "")
        state_dir = args.state_dir.expanduser().resolve()
        repository = Path(__file__).resolve().parents[2]
        require(
            not state_dir.is_relative_to(repository),
            "Operator cache must be outside this repository",
            "config",
        )
        client = Client(state_dir, online=True, sec_contact=contact)
    create_server(read_client=client, allowed_providers=tuple(args.provider)).run(transport="stdio")


if __name__ == "__main__":
    main()
