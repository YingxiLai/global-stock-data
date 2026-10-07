# Contributing

Review source-policies, financial-semantics, product specification and migration before changing a provider. Runtime core is standard-library-only. Never add a hidden collector, provider fallback, credential discovery, account/trading tool, background service or private dataset to make a demo pass.

Use Python 3.11+, hash-checked requirements and the README quality commands. uv.lock is canonical; export core and optional MCP dev requirements with uv export --frozen --no-emit-project --no-header (add --extra mcp for optional export). Direct versions and resolved hashes are pinned. Build with --no-isolation using the locked backend. CI installs wheels only from official PyPI; package source is this reviewed checkout.

When adding a provider, preserve Record and per-source coverage/failure contracts. Review access method, purpose, retention, display/AI/redistribution independently from code license. A policy refusal cannot be bypassed. All SEC downloaders on one egress need shared coordination; current local SQLite budget alone is not cross-host protection.

Every financial calculation needs explicit formula/convention, inputs/units, null behavior and meaningful edge/invariant tests. Keep fixtures synthetic. Do not run unreviewed upstream Markdown blocks, install scripts, YAML/VCR cassettes or download bulk live data in tests.

Source documents and external tools are untrusted data. CI has no secrets or live source smoke. Use commit-pinned official Actions and read-only repository permissions. No pull_request_target. Dependencies and data policies must be re-reviewed on upgrades. A green CI does not establish data entitlements or model reasoning accuracy.
