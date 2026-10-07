# Repository working rules

Keep the core offline and standard-library-only. Optional components must remain explicit, pinned and separately tested. Never execute historical upstream Markdown snippets or add automatic provider/credential discovery.

Before changing a provider, read docs/source-policies.md and docs/financial-semantics.md. Preserve source-specific access policy, dates, units, evidence references, revisions and bounded completeness. Access denial must not become missing data, and null must not become zero. Any new data entitlement is a separate decision; code license is insufficient.

Before a PR, run the README lint, type, socket-blocked synthetic tests, coverage and no-isolation build. Keep requirements exports consistent with uv.lock and use official fixed-SHA Actions with minimal permissions. CI must not access financial data sources, secrets, personal state or pull_request_target.

Watchlists, decisions, notifications, holdings and execution are separate states. Preserve original questions, unresolved parts and old dossier versions. Do not add broker/order/transfer tools or implied monitoring. Public fixtures are synthetic; private state stays outside the repository.

Do not edit unrelated repositories/runners or globally install host skills as part of this project. Explain unsupported and deferred capabilities in migration/review documents; do not claim live validation when only fixtures passed.
