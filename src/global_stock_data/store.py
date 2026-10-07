"""Explicit local state, immutable decision snapshots, no background services."""

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .errors import DataError, require
from .records import instant


class MemoryStore:
    def __init__(self) -> None:
        self.state: dict[str, Any] = {
            "schema_version": "1.0",
            "watchlist": {},
            "decisions": [],
            "context": {},
        }

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.state)

    def watch(
        self,
        *,
        identifier: str,
        instrument: str,
        reason: str | None,
        now: str,
        user_requested: bool,
        source_request_ref: str,
        conditions: list[str] | None = None,
    ) -> dict[str, Any]:
        require(
            user_requested is True,
            "Watchlist mutation requires explicit user request",
            "approval_required",
        )
        instant(now)
        require(
            bool(identifier and instrument and source_request_ref), "Watch identifiers required"
        )
        item = {
            "schema_version": "1.0",
            "watch_id": identifier,
            "instrument": instrument,
            "reason": reason,
            "added_at": now,
            "source_request_ref": source_request_ref,
            "review_conditions": copy.deepcopy(conditions or []),
            "state": "watching",
            "monitoring_state": "off",
            "persistence": "ephemeral",
        }
        require(identifier not in self.state["watchlist"], "Watch ID already exists", "conflict")
        self.state["watchlist"][identifier] = item
        return copy.deepcopy(item)

    def archive_watch(self, identifier: str, *, user_requested: bool) -> None:
        require(user_requested is True, "Explicit archive request required", "approval_required")
        require(identifier in self.state["watchlist"], "Unknown watch ID", "input")
        self.state["watchlist"][identifier]["state"] = "archived"

    def record_decision(
        self,
        *,
        identifier: str,
        dossier_ref: str,
        dossier_version: int,
        decision: str,
        user_statement: str,
        now: str,
        confirmed: bool = False,
        confirmation_ref: str | None = None,
        supersedes: str | None = None,
        unresolved: list[str] | None = None,
    ) -> dict[str, Any]:
        instant(now)
        require(type(confirmed) is bool, "Human confirmation must be boolean", "approval_required")
        require(
            bool(identifier and dossier_ref and user_statement) and dossier_version >= 1,
            "Decision identity and statement required",
        )
        require(
            decision
            in (
                "continue_research",
                "watch",
                "defer",
                "no_action",
                "user_reported_action",
                "other",
            ),
            "Unsupported human decision",
        )
        require(
            not confirmed or bool(confirmation_ref),
            "Human confirmation evidence required",
            "approval_required",
        )
        require(
            all(d["decision_id"] != identifier for d in self.state["decisions"]),
            "Decision ID already exists",
            "conflict",
        )
        if supersedes:
            require(
                any(d["decision_id"] == supersedes for d in self.state["decisions"]),
                "Unknown superseded decision",
                "input",
            )
        item = {
            "schema_version": "1.0",
            "decision_id": identifier,
            "created_at": now,
            "dossier_ref": dossier_ref,
            "dossier_version": dossier_version,
            "actor": "user" if confirmed else "proposal",
            "state": "confirmed" if confirmed else "proposed",
            "decision": decision,
            "user_statement": user_statement,
            "confirmation_ref": confirmation_ref,
            "unresolved_at_decision": copy.deepcopy(unresolved or []),
            "supersedes": supersedes,
            "execution_status": "user_reported"
            if confirmed and decision == "user_reported_action"
            else "not_applicable",
        }
        self.state["decisions"].append(item)
        return copy.deepcopy(item)

    def context(self, key: str, field: dict[str, Any], *, user_requested: bool) -> None:
        require(user_requested is True, "Explicit context update required", "approval_required")
        require(
            field.get("status") in ("provided", "unknown", "declined", "hypothetical"),
            "Invalid context status",
        )
        require(
            field.get("scope") in ("this_request", "session", "persistent"), "Invalid context scope"
        )
        require(
            field["scope"] != "persistent",
            "Memory context is ephemeral; persistent intent requires a private store",
            "persistence_not_enabled",
        )
        self.state["context"][key] = copy.deepcopy(field)


class FileStore(MemoryStore):
    def __init__(
        self, directory: Path, *, repository_root: Path, user_enabled: bool = False
    ) -> None:
        require(
            user_enabled is True, "Private persistence is not enabled", "persistence_not_enabled"
        )
        resolved = directory.resolve()
        require(
            not resolved.is_relative_to(repository_root.resolve()),
            "Private state must be outside the public repository",
            "privacy_denied",
        )
        super().__init__()
        resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = resolved / "research-state.json"
        if self.path.exists():
            require(self.path.stat().st_size <= 1_000_000, "Private state too large")
            raw = json.loads(self.path.read_text())
            require(
                raw.get("schema_version") == "1.0"
                and all(k in raw for k in ("watchlist", "decisions", "context")),
                "Invalid stored state",
            )
            self.state = raw

    def save(self, *, user_requested: bool) -> dict[str, str]:
        require(user_requested is True, "Explicit save request required", "approval_required")
        state = self.snapshot()
        for item in state["watchlist"].values():
            item["persistence"] = "private_local"
        raw = json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False)
        require(len(raw.encode()) <= 1_000_000, "Private state too large")
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, delete=False
            ) as output:
                temporary = output.name
                os.chmod(temporary, 0o600)
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        except OSError as exc:
            if temporary and Path(temporary).exists():
                Path(temporary).unlink()
            raise DataError("save_failed", "Private save failed; details redacted") from exc
        return {"status": "saved", "persistence": "private_local"}
