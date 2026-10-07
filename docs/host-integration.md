# Native Claude and Codex setup

The package must be installed in a project-scoped virtual environment; review README first. Hosts invoke the absolute `.venv/bin/gsd` path in this checkout. No host credentials are inspected or copied. Do not install upstream's archived snippets or auto-enable network access.

## Codex

This fork includes a native project skill at `.agents/skills/global-stock-data/SKILL.md`. Codex discovers project skills from `.agents/skills`; use the global-stock-data skill for research after installing the package. The root SKILL is the canonical distributable; copies must remain equivalent except relative links. No user-level files were changed by this task.

## Claude Code

For a user-requested project-only integration, copy this reviewed root SKILL.md to `.claude/skills/global-stock-data/SKILL.md` and adjust links to this repository's README/docs. Avoid changing an existing different skill without review. Do not claim the Skill is an installed data tool until `.venv/bin/gsd demo` succeeds. This repository does not globally install or edit Claude settings and does not resume other agents/runners.

## Optional stdio MCP

After installing the pinned optional extra, the host may explicitly launch the absolute `.venv/bin/gsd-mcp` command. No arguments, credentials or sockets are needed. The only tools are `research_dossier` and `what_if`. No host configuration was written automatically. SDK metadata marks both read-only; handlers enforce this by using pure local functions. There is no external MCP discovery or trading passthrough.

The host still controls tool authorization and untrusted evidence. Returned facts are not instructions to contact users, connect accounts, increase autonomy or bypass a source policy.

Official references reviewed 2026-10-07: [Claude skills](https://code.claude.com/docs/en/skills), [Codex skills](https://learn.chatgpt.com/docs/build-skills), [MCP SDK v2 API](https://py.sdk.modelcontextprotocol.io/).
