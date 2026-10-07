# Investment research assistant contract

Version 0.1, implementation schema 1.0, 2026-10-07.

## Product decision

A conversation-first research assistant produces inspectable evidence and helps a person clarify a question, compare like-for-like facts, explore explicit assumptions and record their own decisions. The runnable MVP is the Python package, CLI, pure workflow APIs and optional local stdio interface. It does not deploy a bot, GUI or trading terminal.

The minimum loop is intent → request → approved source capability → evidence → claims/dossier → short answer and optional record → manual review. Always distinguish whether data meets the requested contract, whether a question is answerable, whether user constraints are known, and whether the user actually chose an action.

## Four responsibilities

| Layer | Implementation | Boundary |
|---|---|---|
| Data | policy.py, http.py, sec.py, sec_queries.py, macro.py, local.py, adapters.py | Approved capability only; raw dates, units and scope retained; no unlicensed collectors |
| Research | records.py, research.py, render.py | Deterministic quality/readiness; facts/calculations have evidence; assumptions are explicit |
| User context and risk | request context fields, what_if, MemoryStore | Use only volunteered context; declined remains declined; synthetic long-only stress is not advice |
| Human records | MemoryStore, FileStore, review | Explicit mutation/save; append decisions and review versions; execution remains human |

`constraint_checks` currently states unknown. The deterministic what-if concentration check compares an explicitly supplied bound; no suitability or personal portfolio assessment exists.

## Intent routing

`lookup` needs company/filing/metric/period, normally no personal question. `research` proceeds with general evidence. `decision`/`decision_support` preserves the buy question, performs independent research and asks at most two relevant horizon/risk questions. The current-price portion stays unresolved without qualified price evidence. `compare` checks period/unit/definition. `scenario` uses explicit formulas and hypothetical inputs. `review` reads supplied prior/new dossiers and produces a diff without mutating the earlier one.

Watchlist and decision updates are explicit store API operations. The CLI returns outputs rather than pretending to have saved them. User-requested private FileStore save is optional and outside the public repository. There is no scheduler, notification delivery or hidden host configuration.

## User context

Each context field has `value`, `status` (`provided`, `unknown`, `declined`, `hypothetical`) and `scope` (`this_request`, `session`, `persistent`). Clients may include `source_ref` and `confirmed_at`; these rich provenance fields are reserved but not automatically inferred. Persistence needs a real store and explicit authorization; MemoryStore rejects persistent scope.

Minimum fields: goal, horizon, liquidity_constraint, risk_constraints, optional anonymized portfolio_context. No income, assets, jurisdiction, account or risk profile is inferred from a ticker, language or device. A declined horizon/risk field is not asked again. Unknown personal context does not block ordinary company facts. There is no fixed investor questionnaire.

## Versioned structures

[contracts-v1.json](schemas/contracts-v1.json) defines ResearchRequest, EvidenceItem, Claim, ResearchDossier, WatchlistItem and DecisionRecord, matching the current compact implementation. Runtime validators also enforce semantic references and invariants that structural JSON Schema cannot prove. Unknown metadata is null, not zero.

Record is the acquisition envelope. EvidenceItem is a research reference to a concrete source/evidence hash plus source time, status and optional metric. Rich locator/value/unit fields can accompany it and are retained. Acquisition records are not automatically promoted to fresh research evidence: date-only observations and unknown publication instants require explicit source-aware freshness and scope selection by the host. This is a deliberate quality boundary, not a promise of autonomous financial interpretation.

Claims use `fact`, `calculation`, `inference`, `scenario`, `assumption` and `user_statement`. Facts/calculations require resolvable evidence IDs. Calculations require formula/inputs/method_version. Inferences/scenarios require assumptions. The host supplies claim text; no LLM inference service or numerical-consistency theorem prover is included. The validator checks provenance/support status, not whether every natural-language assertion is true.

Dossiers preserve `original_request`, `answered_scope`, `unresolved_parts`, original request/context, evidence, supported flags, gaps, counterevidence, risks, change conditions, freshness policy, deterministic ID, version and generated time. A supported business claim never silently completes an unanswered current-price question. A complete report may include valid facts alongside blocked claims; the short renderer emits supported claims only and explicitly names remaining blockers.

## Quality and readiness

| Data state | Meaning |
|---|---|
| ok | Qualified evidence for this request |
| partial | Unknown time/field/coverage or supplemental gap |
| no_data | A validated successful result truly has no observations |
| stale | Data time exceeds the explicit evidence rule or is future |
| conflict | Unresolved comparable evidence conflicts |
| permission_blocked | Adapter is disabled, offline or explicitly denied access |
| error | Configuration, network, parse or schema failure; never empty success |

Readiness: `answerable` (requested scope supported), `needs_clarification` (material unanswered context), `insufficient_evidence` (critical evidence gap), `blocked` (critical permission or operational barrier). It is not investment suitability, a buy signal or execution permission. Supplemental items marked `critical=false` can leave report data partial while valid claims remain answerable; critical gaps keep overall readiness limited.

Freshness selects observed_at or published_at and an explicit threshold per EvidenceItem. fetched_at cannot establish freshness. The simple default is a visible observed-age rule, not a universal 24-hour financial validity claim. Source schedules/holidays, exchange session calendars and exact filing acceptance times are deferred. Source-only dates remain dates, so unknown availability is not fabricated.

## State, review and reminders

MemoryStore maintains explicit watchlists/context and append-only decisions. A watch item can be watching or archived, always monitoring_state=off. Null reason remains null. Decisions are proposed unless a human confirmation reference exists; confirmed records bind a specific dossier version and can append a supersedes relationship. A user can record defer/watch/no_action even with unresolved research; this does not assert adequate buy evidence. `user_reported_action` means user self-report, never a verified broker fill.

FileStore requires explicit enablement, an external private directory and explicit save. It uses atomic replacement and 0600 files; this is local persistence, not encryption or a multi-user database. Save exceptions return save_failed, never “saved.” Users control data retention and deletion. No personal state is included in source or CI.

Manual review compares prior/new evidence, retains both versions and flags added/revised/removed evidence plus changed readiness. Later disclosures belong only to the new version. Full historical knowability is not inferred. Rich assumption/constraint change interpretation is left to the host; the deterministic diff does not claim causal investment performance attribution.

`alert` is a pure local threshold evaluator with >=1-hour cooldown, crossing deduplication and stale/error suppression. It returns no delivery and creates no schedule. It requires caller-supplied previous state; durable state/scheduling is deferred. A watchlist or “review next filing” is not notification authorization.

## External components

Optional official MCP SDK 2.3.0 supports two pure read-only tools over stdio. No remote server/client registration or HTTP service is exposed. External documents cannot expand permissions. No trading/account/payment tool is registered. See [reuse assessment](docs/reuse.md) for nonintegrated candidates and [source policies](docs/source-policies.md) for access scope.

## Acceptance and scope

[A01–A12](docs/acceptance.md) map to deterministic offline tests and interaction fixtures: zero-question lookup, progressive decision support, declined context, policy refusal, stale/empty distinction, comparable units/periods, conflict suppression, option/short-sale semantics, synthetic scenarios, watch without monitoring, human decision versions, manual review/privacy/execution boundary.

This iteration does not claim live schema validation, real-time quotes, a historical universe, full XBRL fiscal harmonization, a securities account, a deployed assistant, calibrated investment predictions or automatic notifications. These remain explicit extensions requiring their own source policy, implementation and tests.

Completion is explicitly bound to original requirements, claim coverage and same-instrument metric evidence. No requirement assessment means no whole-question answerable. Evaluation identities include actual freshness rules, and nested records are isolated snapshots. The optional MCP research_fetch makes reviewed adapters available under operator startup scope; tool parameters never grant access. New SEC calendar samples/search results remain partial or bounded evidence, not historical universes, first-mention proofs or broker data.
