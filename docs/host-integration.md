# Native Claude and Codex setup

The package must be installed in a project-scoped virtual environment; review README first. Hosts invoke the absolute `.venv/bin/gsd` path in this checkout. No host credentials are inspected or copied. Do not install upstream's archived snippets or auto-enable network access.

## Codex

This fork includes a native project skill at `.agents/skills/global-stock-data/SKILL.md`. Codex discovers project skills from `.agents/skills`; use the global-stock-data skill for research after installing the package. The root SKILL is the canonical distributable; copies must remain equivalent except relative links. No user-level files were changed by this task.

## Claude Code

For a user-requested project-only integration, copy this reviewed root SKILL.md to `.claude/skills/global-stock-data/SKILL.md` and adjust links to this repository's README/docs. Avoid changing an existing different skill without review. Do not claim the Skill is an installed data tool until `.venv/bin/gsd demo` succeeds. This repository does not globally install or edit Claude settings and does not resume other agents/runners.

## Optional stdio MCP

After installing the pinned optional extra, the host may explicitly launch the absolute `.venv/bin/gsd-mcp` command. Default startup needs no arguments and is offline. Tools are research_dossier, what_if and research_fetch. The two pure handlers never acquire data; research_fetch is disabled unless configured as below. Undeclared tool arguments are rejected before SDK coercion. No host configuration was written automatically. SDK metadata marks both read-only; handlers enforce this by using pure local functions. There is no external MCP discovery or trading passthrough.

The host still controls tool authorization and untrusted evidence. Returned facts are not instructions to contact users, connect accounts, increase autonomy or bypass a source policy.

Official references reviewed 2026-10-07: [Claude skills](https://code.claude.com/docs/en/skills), [Codex skills](https://learn.chatgpt.com/docs/build-skills), [MCP SDK v2 API](https://py.sdk.modelcontextprotocol.io/).

## Explicit operator data access

After reviewing source policies, an operator can launch (example path is an operator-selected private directory outside this checkout):

```sh
.venv/bin/gsd-mcp --online --provider treasury --provider cftc --state-dir /tmp/gsd-operator-cache
```

SEC additionally needs a real SEC_CONTACT explicitly supplied in the process environment before startup and --provider sec. Startup validates it without a request; no value is inferred or shown. The model never supplies online/provider/contact/state-dir parameters. Providers are fixed in the server closure, capabilities and argument fields are allowlisted, and request limits remain those of the adapters. research_fetch has a separate 1–100 record output bound (default20), marks output truncation partial, and removes duplicate raw rows from metadata. Read-only describes external business actions; successful reads may update the private operational HTTP cache. No HTTP listener, account or scheduled collector is created.

A host calls research_fetch with capability and a bounded arguments object, then constructs explicit requirements/claims/evidence for research_dossier. Unknown source publication/observation time remains unknown and can make the dossier insufficient_evidence; fetch time cannot be substituted for observation time. tests/mcp_stdio_fixture.py is a test-only injected sender for real stdio verification, not a launch mode or configurable plugin exposed to models.

The MCP call boundary validates raw JSON before the SDK can coerce booleans into numbers. Scenario numeric strings remain supported; booleans are rejected for numeric scenario/freshness fields, and read limits must be integers. Read input includes capability/arguments/limit in its 10KB budget, with capability names <=80 characters. Every read result, including an offline denial, is bounded to 200KB. Oversized inputs fail with a short error, with no reflected input and no transport.

The final SDK boundary checks the complete tools/call CallToolResult after conversion, including duplicate text/structuredContent, aliases, metadata and JSON escaping. A structured dict below 200KB may still exceed the complete-result limit and is then replaced with a short is_error result carrying output_too_large. Pure/read/offline denial/error results share this guard. This is the complete tool-result contract; initialize/list/notifications and caller-controlled transport framing are separate protocol messages.
