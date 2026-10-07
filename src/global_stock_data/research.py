"""Local research contract: data status and readiness are separate.

No execution, broker connectivity, notifications or background monitoring.
Input is untrusted data; it cannot expand tool autonomy or source permissions.
"""

from datetime import timedelta
from typing import Any, cast
from urllib.parse import urlsplit

from .errors import DataError, require
from .records import evidence_hash, instant, number
from .store import MemoryStore

DATA_STATES = {"ok", "partial", "stale", "no_data", "conflict", "permission_blocked", "error"}
AUTONOMY = {"manual", "research", "draft"}


def validate_request(request: dict[str, Any]) -> None:
    require(request.get("schema_version") == "1.0", "Unsupported research schema")
    require(
        isinstance(request.get("question"), str) and bool(request["question"].strip()),
        "Research question required",
    )
    require(
        request.get("autonomy") in AUTONOMY,
        "Only manual/research/draft autonomy allowed",
        "autonomy_denied",
    )
    require(
        request.get("intent")
        in ("lookup", "research", "decision", "decision_support", "compare", "scenario", "review"),
        "Unknown research intent",
    )
    profile = request.get("profile", {})
    require(isinstance(profile, dict), "Profile must be an object")
    for key in ("max_position_weight", "max_drawdown"):
        if key in profile and profile[key] is not None:
            value = number(profile[key])
            require(value is not None and 0 <= value <= 1, "Risk constraints must be fractions")
    context = request.get("context", {})
    require(isinstance(context, dict), "Context must be an object")
    for field in context.values():
        require(
            isinstance(field, dict)
            and field.get("status") in ("provided", "unknown", "declined", "hypothetical"),
            "Invalid context status",
        )
        require(
            field.get("scope") in ("this_request", "session", "persistent"), "Invalid context scope"
        )
    watchlist = request.get("watchlist", [])
    require(
        isinstance(watchlist, list)
        and all(isinstance(x, str) for x in watchlist)
        and len(watchlist) == len(set(watchlist)),
        "Watchlist must contain unique asset IDs",
    )


def dossier(
    request: dict[str, Any],
    evidence: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    *,
    now: str,
    max_age_seconds: float = 86400,
) -> dict[str, Any]:
    validate_request(request)
    current = instant(now)
    require(max_age_seconds >= 0, "Invalid research freshness bound")
    by_id: dict[str, dict[str, Any]] = {}
    states = set()
    for item in evidence:
        identifier = item.get("id")
        require(
            isinstance(identifier, str) and bool(identifier) and identifier not in by_id,
            "Evidence IDs must be unique",
        )
        require(
            item.get("status") in DATA_STATES
            and bool(item.get("source_url"))
            and bool(item.get("evidence_ref")),
            "Evidence status/provenance required",
        )
        url = urlsplit(item["source_url"])
        require(
            url.scheme in ("https", "http", "synthetic", "user-provided")
            and not any(c in item["source_url"] for c in "\n\r()"),
            "Unsafe evidence URL",
        )
        state = item["status"]
        basis = item.get("freshness_basis", "observed_at")
        require(
            basis in ("observed_at", "published_at"), "Fetched time cannot establish data freshness"
        )
        observed = item.get(basis)
        item_max_age = item.get("max_age_seconds", max_age_seconds)
        require(
            isinstance(item_max_age, int | float) and item_max_age >= 0,
            "Invalid evidence freshness rule",
        )
        if observed is None and state == "ok":
            state = "partial"
        elif observed is not None:
            age = (current - instant(observed)).total_seconds()
            if age < 0 or age > item_max_age:
                state = "stale"
        by_id[cast(str, identifier)] = {**item, "status": state}
        states.add(state)
    validated_claims = []
    for claim in claims:
        require(
            claim.get("kind")
            in ("fact", "calculation", "inference", "scenario", "assumption", "user_statement"),
            "Claim kind must be fact/inference/scenario",
        )
        require(isinstance(claim.get("text"), str) and bool(claim["text"]), "Claim text required")
        refs = claim.get("evidence_ids", [])
        require(
            isinstance(refs, list) and all(ref in by_id for ref in refs),
            "Claim evidence reference unresolved",
        )
        require(
            claim["kind"] not in ("fact", "calculation") or bool(refs), "Facts require evidence"
        )
        require(
            claim["kind"] in ("fact", "calculation", "user_statement")
            or bool(claim.get("assumptions")),
            "Inferences/scenarios need explicit assumptions",
        )
        if claim["kind"] == "calculation":
            require(
                bool(claim.get("formula"))
                and bool(claim.get("inputs"))
                and bool(claim.get("method_version")),
                "Calculation requires formula, inputs and version",
            )
        validated_claims.append(
            {**claim, "supported": bool(refs) and all(by_id[ref]["status"] == "ok" for ref in refs)}
        )
    priority = ("permission_blocked", "error", "conflict", "stale", "partial", "no_data", "ok")
    status = next((value for value in priority if value in states), "no_data")
    supported = bool(validated_claims) and all(c["supported"] for c in validated_claims)
    profile = request.get("profile", {})
    questions = []
    if request["intent"] in ("decision", "decision_support"):
        if not profile.get("horizon") and context_status(request, "horizon") == "unknown":
            questions.append("What is the decision horizon?")
        if (
            not profile.get("risk_budget")
            and context_status(request, "risk_constraints") == "unknown"
        ):
            questions.append("What loss or allocation limit should constrain this decision?")
    unresolved = list(request.get("unresolved_parts", []))
    required = request.get("required_evidence_ids", [])
    for identifier in required:
        if identifier not in by_id or by_id[identifier]["status"] != "ok":
            unresolved.append("required_evidence:" + identifier)
    if request["intent"] in ("decision", "decision_support") and not any(
        e.get("metric") == "current_price" and e["status"] == "ok" for e in by_id.values()
    ):
        unresolved.append("current_price_and_valuation_not_supported")
    critical_states = {e["status"] for e in by_id.values() if e.get("critical", True)}
    if questions:
        readiness = "needs_clarification"
    elif critical_states & {"permission_blocked", "error"}:
        readiness = "blocked"
    else:
        readiness = (
            "answerable"
            if supported and not unresolved and not (critical_states - {"ok"})
            else "insufficient_evidence"
        )

    return {
        "schema_version": "1.0",
        "dossier_id": evidence_hash(
            {"request": request, "evidence": evidence, "claims": claims, "now": now}
        ),
        "version": 1,
        "original_request": request["question"],
        "answered_scope": [c["text"] for c in validated_claims if c["supported"]],
        "unresolved_parts": unresolved,
        "request": request,
        "data_status": status,
        "readiness": readiness,
        "evidence": list(by_id.values()),
        "claims": validated_claims,
        "clarifying_questions": questions[:2],
        "gaps": [e["id"] + ":" + e["status"] for e in by_id.values() if e["status"] != "ok"],
        "opposing_case": request.get("opposing_case", []),
        "risks": request.get("risks", []),
        "change_conditions": request.get("change_conditions", []),
        "constraint_checks": "unknown; only explicit scenario checks implemented",
        "freshness_policy_id": request.get("freshness_policy_id", "explicit_observed_age_v1"),
        "generated_at": now,
        "answerable_is_buy_signal": False,
        "next_action": "human_review"
        if readiness == "answerable"
        else "clarify"
        if questions
        else "collect_authorized_evidence",
    }


def decision_record(
    report: dict[str, Any], *, decision: str, rationale: str, user_approved: bool, review_on: str
) -> dict[str, Any]:
    require(
        report.get("readiness") == "answerable" and report.get("data_status") == "ok",
        "Decision record blocked by research gaps",
        "evidence_blocked",
    )
    require(
        user_approved and report["request"]["autonomy"] == "draft",
        "Explicit user review and draft autonomy required",
        "approval_required",
    )
    require(
        decision in ("defer", "watch", "research_more", "human_decision"),
        "No trade execution decisions",
        "autonomy_denied",
    )
    require(bool(rationale.strip()), "Decision rationale required")
    require(instant(review_on) > instant(report["generated_at"]), "Review must follow research")
    canonical = {"research_more": "continue_research", "human_decision": "other"}.get(
        decision, decision
    )
    record = MemoryStore().record_decision(
        identifier=evidence_hash(
            {"report": report["dossier_id"], "decision": canonical, "rationale": rationale}
        ),
        dossier_ref=report["dossier_id"],
        dossier_version=report["version"],
        decision=canonical,
        user_statement=rationale,
        now=report["generated_at"],
        confirmed=True,
        confirmation_ref="explicit_user_approval",
        unresolved=report["unresolved_parts"],
    )
    return {
        **record,
        "rationale": rationale,
        "evidence_refs": [e["evidence_ref"] for e in report["evidence"]],
        "claims": report["claims"],
        "review_on": review_on,
        "user_approved": True,
        "execution": "human_only",
    }


def what_if(
    weights: dict[str, float], shocks: dict[str, float], *, max_weight: float = 1
) -> dict[str, Any]:
    require(0 <= max_weight <= 1, "Invalid concentration bound")
    require(
        bool(weights)
        and all(
            isinstance(w, int | float) and number(w) is not None and 0 <= w <= 1
            for w in weights.values()
        ),
        "Only finite long-only synthetic weights supported",
    )
    require(sum(weights.values()) <= 1 + 1e-12, "Weights exceed 100%; leverage unsupported")
    require(
        set(weights) == set(shocks)
        and all(
            isinstance(s, int | float) and number(s) is not None and s >= -1
            for s in shocks.values()
        ),
        "Scenario shocks must cover each asset",
    )
    return {
        "portfolio_return": sum(weights[a] * shocks[a] for a in weights),
        "cash_weight": max(0.0, 1 - sum(weights.values())),
        "concentration_breaches": [a for a, w in weights.items() if w > max_weight],
        "assumptions": "static_weights; no_rebalancing; no_fees_tax_fx; scenario_not_forecast",
    }


def alert(
    rule: dict[str, Any],
    *,
    value: float | None,
    data_status: str,
    now: str,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require(data_status in DATA_STATES, "Invalid alert data status")
    current = instant(now)
    threshold = number(rule.get("threshold"))
    require(
        threshold is not None and rule.get("direction") in ("above", "below"),
        "Alert threshold and direction required",
    )
    cooldown = number(rule.get("cooldown_seconds"))
    require(cooldown is not None and cooldown >= 3600, "Alert cooldown must be >=1 hour")
    threshold, cooldown = cast(float, threshold), cast(float, cooldown)
    parsed = number(value)
    crossed = parsed is not None and (
        parsed >= threshold if rule["direction"] == "above" else parsed <= threshold
    )
    was_crossed = bool(previous and previous.get("crossed"))
    last = previous.get("last_emitted_at") if previous else None
    cooling = bool(last and current < instant(last) + timedelta(seconds=cooldown))
    emit = crossed and not was_crossed and not cooling and data_status == "ok"
    return {
        "emit": emit,
        "crossed": crossed if data_status == "ok" else was_crossed,
        "last_emitted_at": now if emit else last,
        "reason": "threshold_crossing" if emit else "suppressed",
        "delivery": "none; local_result_only",
    }


def dispatch(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Stable read-only tool interface for a future optional stdio MCP adapter."""
    if tool == "what_if":
        return what_if(**arguments)
    if tool == "research_dossier":
        return dossier(**arguments)
    raise DataError("tool_denied", "Unknown or write/trading tool denied")


def context_status(request: dict[str, Any], key: str) -> str:
    field = request.get("context", {}).get(key, {})
    return str(field.get("status", "unknown"))
