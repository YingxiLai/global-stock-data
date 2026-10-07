# Product acceptance

The executable A01–A12 methods are in tests/test_product.py; financial/error/concurrency invariants are in tests/test_core.py. All cases use synthetic fixtures and run under the outbound socket guard. These are deterministic component/conversation-contract checks, not claims of an LLM's investment reasoning quality or live market availability.

| ID | Expected behavior | Executable evidence |
|---|---|---|
| A01 | Narrow lookup has no personal questions; value/unit/date/source visible | test_A01_narrow_query_no_profile_questions |
| A02 | At most two questions, business facts proceed, original buy/price part unresolved | test_A02_original_buy_question_not_completed_by_business_research |
| A03 | Declined context remains null/declined, no repeated asset request | test_A03_declined_context_no_repeated_asset_request |
| A04 | Permission status preserved; other valid facts remain; no quote fallback | test_A04_permission_blocked_does_not_destroy_other_evidence + HTTP denial tests |
| A05 | Old time remains stale; validated empty differs from null and zero | test_A05_stale_vs_verified_empty + cache provenance |
| A06 | Currency/scale/quarter/YTD mismatch blocks computation; comparable growth formula retained | test_A06_incompatible_units_and_periods_fail |
| A07 | Critical conflict limits readiness; renderer suppresses unsupported facts | test_A07_conflicts_no_unsupported_fact_rendering |
| A08 | Missing OI/delta not fabricated; CNMS is limited facility volume | test_A08_activity_scope_kept_in_contract |
| A09 | Synthetic static-weight stress is not actual portfolio or forecast | test_A09_scenario_is_not_real_portfolio |
| A10 | Explicit watch is ephemeral, monitor off, null reason not invented | test_A10_watch_is_ephemeral_and_monitor_off |
| A11 | Human confirmation references, specific dossier version, append/supersedes; no execution | test_A11_human_decisions_append_and_do_not_imply_execution |
| A12 | Old dossier unchanged; new evidence diff; private path required; order tools denied | test_A12_manual_review_privacy_and_no_execution |

examples/conversations.json is a synthetic case inventory; examples/research-synthetic.json and demo outputs are runnable workflow fixtures. No real user dialogue is published. The host remains responsible for forming valid claim text, source-aware thresholds and prompt-injection handling. We do not claim semantic truth merely because a cited string passes a schema.

JSON Schema contracts are structural; runtime validators establish evidence references, critical status/readiness, temporal freshness, explicit human actions and comparison invariants. Optional MCP tests check actual tool listing and calls in-process and through a real stdio subprocess, with no port/account/provider service.

Follow-up acceptance is covered in test_extensions.py and test_review_regressions.py: bounded Frames/FTS and source errors, expiry/DTE/count summaries, operator-scoped/default-offline MCP reads, real stdio read-to-dossier loop, requirement coverage, evaluation identity, isolated snapshots and per-underlying delta. Failing scope or unknown source freshness must stay visibly unresolved.
