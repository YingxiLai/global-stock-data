"""JSON CLI; default offline; no session or credential discovery."""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .adapters import CAPABILITIES, capabilities, fetch
from .errors import DataError, require
from .http import Client
from .options import chain_summary, filter_expiry
from .policy import source_manifest
from .render import markdown, short_answer
from .research import dossier, validate_request, what_if
from .sec import Sec, company_facts


def demo() -> dict[str, Any]:
    request = {
        "schema_version": "1.0",
        "intent": "research",
        "question": "What does synthetic ACME evidence support?",
        "autonomy": "research",
        "watchlist": ["SYNTH:ACME"],
        "requirements": [
            {
                "id": "revenue",
                "description": "Inspect synthetic revenue",
                "instrument": "SYNTH:ACME",
                "evidence_metrics": ["revenue"],
            }
        ],
    }
    evidence = [
        {
            "id": "demo-1",
            "status": "ok",
            "source_url": "synthetic://fixture/acme",
            "evidence_ref": "synthetic:acme-v1",
            "observed_at": "2026-01-02T15:00:00+00:00",
            "instrument": "SYNTH:ACME",
            "metric": "revenue",
        }
    ]
    claims = [
        {
            "kind": "fact",
            "text": "Synthetic revenue is 100 units.",
            "evidence_ids": ["demo-1"],
            "requirement_ids": ["revenue"],
        },
        {
            "kind": "scenario",
            "text": "A 10% price shock with 20% weight changes portfolio value by 2%.",
            "evidence_ids": ["demo-1"],
            "assumptions": ["static weights", "synthetic prices"],
        },
    ]
    report = dossier(request, evidence, claims, now="2026-01-02T16:00:00+00:00")
    report["what_if"] = what_if({"SYNTH:ACME": 0.2}, {"SYNTH:ACME": -0.1}, max_weight=0.25)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evidence-first research; offline unless --online")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    demo_parser = sub.add_parser("demo")
    demo_parser.add_argument("--format", choices=("json", "markdown", "short"), default="json")
    sub.add_parser("sources")
    sub.add_parser("capabilities")
    fetch_parser = sub.add_parser("fetch")
    fetch_parser.add_argument("capability", choices=list(CAPABILITIES))
    fetch_parser.add_argument(
        "--arguments", default="{}", help="JSON object with bounded capability arguments"
    )
    fetch_parser.add_argument("--online", action="store_true")
    fetch_parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path(
            os.environ.get("GSD_STATE_DIR", str(Path.home() / ".cache/global-stock-data"))
        ),
    )
    workflow = sub.add_parser("research")
    workflow.add_argument("file", type=Path)
    workflow.add_argument("--format", choices=("json", "markdown", "short"), default="json")
    workflow.add_argument("--now", required=True, help="Explicit ISO timestamp including offset")
    option_parser = sub.add_parser("options")
    option_parser.add_argument("file", type=Path)
    option_parser.add_argument("--snapshot-at", required=True)
    option_parser.add_argument("--expiry")
    option_parser.add_argument("--dte-min", type=int)
    option_parser.add_argument("--dte-max", type=int)
    for name in ("sec-facts", "sec-filings", "sec-tickers", "sec-index"):
        command = sub.add_parser(name)
        command.add_argument("--online", action="store_true")
        command.add_argument(
            "--state-dir",
            type=Path,
            default=Path(
                os.environ.get("GSD_STATE_DIR", str(Path.home() / ".cache/global-stock-data"))
            ),
        )
        if name in ("sec-facts", "sec-filings"):
            command.add_argument("cik")
        if name == "sec-facts":
            command.add_argument("--as-of")
        if name == "sec-filings":
            command.add_argument("--max-history-files", type=int, default=0)
        if name == "sec-index":
            command.add_argument("date")
            command.add_argument("--max-fallback-days", type=int, default=0)
            command.add_argument("--max-data-age-days", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        result: Any
        if args.command == "demo":
            result = demo()
        elif args.command == "sources":
            result = source_manifest()
        elif args.command == "capabilities":
            result = capabilities()
        elif args.command == "fetch":
            require(
                len(args.arguments.encode()) <= 10000, "Capability arguments too large", "input"
            )
            arguments = json.loads(args.arguments)
            require(isinstance(arguments, dict), "Capability arguments must be an object", "input")
            require(args.online, "Online access requires explicit --online", "offline")
            result = fetch(Client(args.state_dir, online=True), args.capability, arguments)
        elif args.command == "options":
            require(args.file.stat().st_size <= 1_000_000, "Option input too large", "input")
            contracts = json.loads(args.file.read_text())
            require(
                isinstance(contracts, list) and all(isinstance(row, dict) for row in contracts),
                "Local option input must be contract objects",
                "input",
            )
            result = filter_expiry(
                contracts,
                snapshot_at=args.snapshot_at,
                expiry=args.expiry,
                dte_min=args.dte_min,
                dte_max=args.dte_max,
            )
            result["summary"] = chain_summary(result["contracts"])
        elif args.command == "research":
            require(args.file.stat().st_size <= 1_000_000, "Research input too large", "input")
            content = json.loads(args.file.read_text())
            validate_request(content["request"])
            result = dossier(
                content["request"], content["evidence"], content["claims"], now=args.now
            )
        else:
            require(args.online, "Online access requires explicit --online", "offline")
            sec = Sec(Client(args.state_dir, online=args.online))
            if args.command == "sec-facts":
                payload = sec.facts(args.cik)
                result = {
                    "facts": company_facts(payload.json(), as_of=args.as_of),
                    "fetched_at": payload.fetched_at,
                    "evidence_ref": payload.evidence_ref,
                    "point_in_time_safe": False,
                }
            elif args.command == "sec-filings":
                result = sec.filings(args.cik, max_history_files=args.max_history_files)
            elif args.command == "sec-tickers":
                payload = sec.tickers()
                result = {
                    "mapping": payload.json(),
                    "fetched_at": payload.fetched_at,
                    "evidence_ref": payload.evidence_ref,
                    "accuracy_and_scope": "not_guaranteed",
                }
            else:
                result = sec.daily_index(
                    args.date,
                    max_fallback_days=args.max_fallback_days,
                    max_data_age_days=args.max_data_age_days,
                )
        if getattr(args, "format", "json") == "markdown":
            print(markdown(result), end="")
        elif getattr(args, "format", "json") == "short":
            print(short_answer(result), end="")
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return (
            2
            if isinstance(result, dict)
            and result.get("data_status") in ("error", "permission_blocked")
            else 0
        )
    except DataError as exc:
        print(json.dumps(exc.as_dict()), file=sys.stderr)
        return 2
    except (ValueError, KeyError, TypeError, OSError):
        print(
            json.dumps(
                DataError("input", "Invalid input or local file; details redacted").as_dict()
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
