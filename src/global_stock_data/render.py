"""Plain Markdown views; unsupported claims never appear as supported facts."""

import html
from typing import Any

from .errors import require


def text(value: Any) -> str:
    return html.escape(str(value)).replace("\n", " ").replace("[", "\\[").replace("]", "\\]")


def short_answer(report: dict[str, Any]) -> str:
    require(report.get("schema_version") == "1.0", "Unsupported dossier schema")
    lines = [f"Research status: {text(report['readiness'])}; data: {text(report['data_status'])}."]
    sources = {e["id"]: e for e in report["evidence"]}
    for claim in [c for c in report["claims"] if c["supported"]][:4]:
        citations = []
        for identifier in claim["evidence_ids"]:
            evidence = sources[identifier]
            citations.append(
                f"[{text(identifier)}]({evidence['source_url']}) (observed {text(evidence.get('observed_at'))})"
            )
        lines.append(f"- {text(claim['kind'])}: {text(claim['text'])} " + "; ".join(citations))
    if report.get("unresolved_parts"):
        lines.append("Still unanswered: " + "; ".join(text(p) for p in report["unresolved_parts"]))
    if report.get("gaps"):
        lines.append("Evidence gaps: " + "; ".join(text(g) for g in report["gaps"]))
    for question in report["clarifying_questions"]:
        lines.append(text(question))
    lines.append("This is research readiness; the decision and execution remain with the user.")
    return "\n".join(lines) + "\n"


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Research dossier",
        "",
        f"Question: {text(report['original_request'])}",
        "",
        short_answer(report).strip(),
        "",
        "## Evidence",
        "",
    ]
    for evidence in report["evidence"]:
        lines.append(
            f"- {text(evidence['id'])}: {text(evidence['status'])}; freshness: {text(evidence.get('freshness', 'unknown'))}; {text(evidence['evidence_ref'])}; observed {text(evidence.get('observed_at'))}; [{text(evidence['source_url'])}]({evidence['source_url']})"
        )
    for key, title in [
        ("opposing_case", "Counterevidence"),
        ("risks", "Risks"),
        ("change_conditions", "What would change this assessment"),
    ]:
        if report.get(key):
            lines.extend(["", "## " + title, ""] + ["- " + text(item) for item in report[key]])
    return "\n".join(lines) + "\n"


def review(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    require(
        previous.get("schema_version") == current.get("schema_version") == "1.0",
        "Incompatible dossier versions",
    )
    require(
        previous.get("original_request") == current.get("original_request"),
        "Review must retain the original question",
    )
    old = {e["id"]: e for e in previous["evidence"]}
    new = {e["id"]: e for e in current["evidence"]}
    changes = [
        {"id": identifier, "old": old.get(identifier), "new": value}
        for identifier, value in new.items()
        if old.get(identifier) != value
    ]
    removed = [identifier for identifier in old if identifier not in new]
    return {
        "schema_version": "1.0",
        "previous_version_ref": previous["dossier_id"],
        "version": previous["version"] + 1,
        "changes": changes,
        "removed_evidence_ids": removed,
        "old_readiness": previous["readiness"],
        "new_readiness": current["readiness"],
        "historical_knowability": "not_inferred; later_disclosures_remain_in_new_version_only",
    }
