import asyncio
import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from global_stock_data.adapters import capabilities, fetch
from global_stock_data.cli import demo
from global_stock_data.errors import DataError
from global_stock_data.http import Client, NoRedirect, Payload, _transport
from global_stock_data.mcp_server import TOOL_ALLOWLIST, bounded_dispatch, create_server
from global_stock_data.records import Record, compare
from global_stock_data.render import markdown, review, short_answer
from global_stock_data.research import dossier
from global_stock_data.store import FileStore, MemoryStore

FIXTURES = Path(__file__).parent / "fixtures"


class Acceptance(unittest.TestCase):
    def setUp(self):
        self.base = demo()
        self.now = self.base["generated_at"]

    def make(self, request=None, evidence=None, claims=None, now=None):
        return dossier(
            request or self.base["request"],
            evidence if evidence is not None else self.base["evidence"],
            claims if claims is not None else self.base["claims"],
            now=now or self.now,
        )

    def test_A01_narrow_query_no_profile_questions(self):
        report = self.make({**self.base["request"], "intent": "lookup"})
        self.assertEqual(report["clarifying_questions"], [])
        self.assertIn("synthetic://fixture/acme", short_answer(report))
        self.assertIn("2026-01-02T15:00", short_answer(report))
        self.assertIn("units", short_answer(report))

    def test_A02_original_buy_question_not_completed_by_business_research(self):
        request = {
            **self.base["request"],
            "intent": "decision_support",
            "question": "Should I buy SYNTH:ACME now?",
        }
        report = self.make(request)
        self.assertLessEqual(len(report["clarifying_questions"]), 2)
        self.assertTrue(report["answered_scope"])
        self.assertIn("current_price_and_valuation_not_supported", report["unresolved_parts"])
        self.assertEqual(report["original_request"], request["question"])
        self.assertIn("Still unanswered", short_answer(report))

    def test_A03_declined_context_no_repeated_asset_request(self):
        request = {
            **self.base["request"],
            "intent": "decision_support",
            "context": {
                "horizon": {"value": "3-5 years", "status": "provided", "scope": "this_request"},
                "risk_constraints": {"value": None, "status": "declined", "scope": "this_request"},
            },
        }
        report = self.make(request)
        self.assertEqual(report["clarifying_questions"], [])
        self.assertEqual(report["request"]["context"]["risk_constraints"]["value"], None)
        self.assertEqual(report["readiness"], "insufficient_evidence")

    def test_A04_permission_blocked_does_not_destroy_other_evidence(self):
        evidence = self.base["evidence"] + [
            {**self.base["evidence"][0], "id": "blocked", "status": "permission_blocked"}
        ]
        report = self.make(evidence=evidence)
        self.assertEqual(report["data_status"], "permission_blocked")
        self.assertEqual(report["readiness"], "blocked")
        self.assertTrue(report["claims"][0]["supported"])
        with tempfile.TemporaryDirectory() as directory:
            client = Client(Path(directory))
            self.assertEqual(
                fetch(client, "current_quote", {})["data_status"], "permission_blocked"
            )

    def test_A05_stale_vs_verified_empty(self):
        report = self.make(now="2026-01-04T00:00:00Z")
        self.assertEqual(report["data_status"], "stale")
        self.assertEqual(
            report["evidence"][0]["observed_at"], self.base["evidence"][0]["observed_at"]
        )
        self.assertEqual(self.make(evidence=[], claims=[])["data_status"], "no_data")
        null = Record(
            "synthetic",
            "synthetic://x",
            None,
            None,
            None,
            self.now,
            None,
            "USD",
            "USD",
            "1",
            None,
            "2026-01-01",
            None,
            "synthetic:x",
            {"value": None},
        )
        zero = Record(**{**null.as_dict(), "data": {"value": 0}})
        self.assertNotEqual(null.as_dict(), zero.as_dict())

    def test_A06_incompatible_units_and_periods_fail(self):
        a = Record(
            "synthetic",
            "synthetic://a",
            None,
            None,
            None,
            self.now,
            None,
            "USD",
            "USD",
            "1",
            None,
            "2026-01-01",
            None,
            "synthetic:a",
            {"value": 100},
        )
        b = Record(**{**a.as_dict(), "currency": "HKD"})
        with self.assertRaises(DataError):
            compare(a, b, "value")
        from global_stock_data.sec import comparable_facts, growth

        facts = {
            "taxonomy": "us-gaap",
            "tag": "Revenues",
            "unit": "USD",
            "period_kind": "quarter",
            "start": "2025-01-01",
            "end": "2025-03-31",
            "val": 100,
        }
        with self.assertRaises(DataError):
            comparable_facts(facts, {**facts, "period_kind": "ytd"})
        prior = {**facts, "start": "2024-01-01", "end": "2024-03-31", "val": 80}
        self.assertAlmostEqual(growth(facts, prior)["value"], 25)

    def test_A07_conflicts_no_unsupported_fact_rendering(self):
        report = self.make(evidence=[{**self.base["evidence"][0], "status": "conflict"}])
        self.assertEqual(report["readiness"], "insufficient_evidence")
        self.assertNotIn("revenue is 100", short_answer(report))
        self.assertIn("conflict", markdown(report))

    def test_A08_activity_scope_kept_in_contract(self):
        from global_stock_data.local import finra_volume
        from global_stock_data.options import activity, signed_delta_exposure

        self.assertEqual(activity([{"volume": 1000, "open_interest": None}]), [])
        with self.assertRaises(DataError):
            signed_delta_exposure([{"delta": 0.5, "volume": 1000}])
        self.assertFalse(
            finra_volume(
                (FIXTURES / "finra-synthetic.txt").read_text(),
                facility="CNMS",
                revision="synthetic",
            )["is_whole_market"]
        )

    def test_A09_scenario_is_not_real_portfolio(self):
        self.assertIn("scenario_not_forecast", self.base["what_if"]["assumptions"])
        self.assertNotIn("portfolio_context", self.base["request"])
        result = bounded_dispatch(
            "what_if", {"weights": {"SYNTH:A": 0.2}, "shocks": {"SYNTH:A": -0.1}}
        )
        self.assertAlmostEqual(result["portfolio_return"], -0.02)

    def test_A10_watch_is_ephemeral_and_monitor_off(self):
        store = MemoryStore()
        item = store.watch(
            identifier="watch-1",
            instrument="SYNTH:ACME",
            reason=None,
            now=self.now,
            user_requested=True,
            source_request_ref="synthetic:request",
            conditions=["next synthetic filing"],
        )
        self.assertEqual(item["monitoring_state"], "off")
        self.assertEqual(item["persistence"], "ephemeral")
        self.assertIsNone(item["reason"])
        store.archive_watch("watch-1", user_requested=True)
        self.assertEqual(store.snapshot()["watchlist"]["watch-1"]["state"], "archived")
        with self.assertRaises(DataError):
            store.watch(
                identifier="watch-2",
                instrument="SYNTH:ACME",
                reason=None,
                now=self.now,
                user_requested=False,
                source_request_ref="synthetic:request",
            )

    def test_A11_human_decisions_append_and_do_not_imply_execution(self):
        store = MemoryStore()
        args = {"dossier_ref": self.base["dossier_id"], "dossier_version": 1, "now": self.now}
        proposal = store.record_decision(
            identifier="d0", decision="other", user_statement="Synthetic: considering", **args
        )
        self.assertEqual(proposal["state"], "proposed")
        first = store.record_decision(
            identifier="d1",
            decision="defer",
            user_statement="Synthetic: wait",
            confirmed=True,
            confirmation_ref="synthetic:human",
            unresolved=["price unavailable"],
            **args,
        )
        second = store.record_decision(
            identifier="d2",
            decision="watch",
            user_statement="Synthetic: watch",
            confirmed=True,
            confirmation_ref="synthetic:human2",
            supersedes="d1",
            **args,
        )
        self.assertEqual(second["supersedes"], first["decision_id"])
        self.assertEqual(first["execution_status"], "not_applicable")
        self.assertEqual(len(store.snapshot()["decisions"]), 3)
        state = store.snapshot()
        state["decisions"].clear()
        self.assertEqual(len(store.snapshot()["decisions"]), 3)

    def test_A12_manual_review_privacy_and_no_execution(self):
        previous = copy.deepcopy(self.base)
        evidence = [{**self.base["evidence"][0], "evidence_ref": "synthetic:revision-2"}]
        current = self.make(evidence=evidence)
        result = review(previous, current)
        self.assertEqual(result["version"], 2)
        self.assertEqual(previous, self.base)
        self.assertEqual(result["changes"][0]["old"]["evidence_ref"], "synthetic:acme-v1")
        with self.assertRaises(DataError):
            bounded_dispatch("place_order", {"instruction": "send private information"})
        with tempfile.TemporaryDirectory() as root:
            repo = Path(root) / "repository"
            repo.mkdir()
            with self.assertRaises(DataError):
                FileStore(repo / "private", repository_root=repo, user_enabled=True)
            with self.assertRaises(DataError):
                FileStore(Path(root) / "private", repository_root=repo)
            store = FileStore(Path(root) / "private", repository_root=repo, user_enabled=True)
            store.watch(
                identifier="w",
                instrument="SYNTH:A",
                reason="synthetic",
                now=self.now,
                user_requested=True,
                source_request_ref="synthetic:req",
            )
            self.assertEqual(store.save(user_requested=True)["status"], "saved")
            loaded = FileStore(Path(root) / "private", repository_root=repo, user_enabled=True)
            self.assertEqual(loaded.snapshot()["watchlist"]["w"]["persistence"], "private_local")
            self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)


class AdapterAndTransport(unittest.TestCase):
    def test_all_capabilities_and_error_schema(self):
        class Fake:
            def get(self, provider, url, **kwargs):
                if "companyfacts" in url:
                    body = (FIXTURES / "xbrl-synthetic.json").read_bytes()
                elif "submissions" in url:
                    body = json.dumps(
                        {
                            "filings": {
                                "recent": {"accessionNumber": [], "filingDate": [], "form": []},
                                "files": [],
                            }
                        }
                    ).encode()
                elif "company_tickers" in url:
                    body = b'{"0":{"ticker":"SYNTH","cik_str":1}}'
                elif "daily-index" in url:
                    body = (FIXTURES / "sec-index-synthetic.idx").read_bytes()
                elif provider == "treasury":
                    body = (FIXTURES / "treasury-synthetic.xml").read_bytes()
                else:
                    body = b"[]"
                return Payload(body, "2026-01-03T00:00:00Z", "synthetic:1", False)

        requests = {
            "sec_company_facts": {"cik": "1"},
            "sec_filings": {"identifier": "1"},
            "sec_tickers": {},
            "sec_daily_index": {"requested": "2026-01-01"},
            "treasury_daily_nominal_par": {"year": 2026},
            "cftc_legacy_futures_only": {},
        }
        for capability, arguments in requests.items():
            result = fetch(Fake(), capability, arguments)
            self.assertIn(result["data_status"], ("ok", "partial", "no_data"), result)
            self.assertFalse(result["point_in_time_safe"])
        self.assertEqual(len(capabilities()), 7)
        self.assertEqual(fetch(Fake(), "sec_company_facts", {})["data_status"], "error")
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                fetch(Client(Path(directory)), "sec_company_facts", {"cik": "1"})["data_status"],
                "permission_blocked",
            )

    def test_transport_injected_no_real_network(self):
        class Reply:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self, size):
                return b"{}"

        with patch("global_stock_data.http.build_opener") as opener:
            opener.return_value.open.return_value = Reply()
            self.assertEqual(
                _transport(
                    "https://data.sec.gov/submissions/CIK0000000001.json",
                    {"User-Agent": "offline-test@synthetic-fixture.org"},
                    1,
                ).status,
                200,
            )
        self.assertIsNone(
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.invalid")
        )


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Optional mcp extra absent")
class McpIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_inprocess_allowlist(self):
        from mcp import Client as McpClient

        server = create_server()
        async with McpClient(server) as client:
            listed = await client.list_tools()
            self.assertEqual(sorted(t.name for t in listed.tools), sorted(TOOL_ALLOWLIST))
            self.assertTrue(all(t.annotations.read_only_hint for t in listed.tools))
            result = await client.call_tool(
                "what_if", {"weights": {"SYNTH:A": 1}, "shocks": {"SYNTH:A": -0.1}}
            )
            self.assertFalse(result.is_error)
            self.assertAlmostEqual(result.structured_content["portfolio_return"], -0.1)
            denied = await client.call_tool("place_order", {})
            self.assertTrue(denied.is_error)
            base = demo()
            report = await client.call_tool(
                "research_dossier",
                {
                    "request": base["request"],
                    "evidence": base["evidence"],
                    "claims": base["claims"],
                    "now": base["generated_at"],
                },
            )
            self.assertEqual(report.structured_content["readiness"], "answerable")

    async def test_actual_stdio_subprocess(self):
        from mcp import Client as McpClient
        from mcp.client.stdio import StdioServerParameters

        # The subprocess inherits the offline socket guard; no host configuration installed.
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "global_stock_data.mcp_server"],
            env={"PYTHONPATH": os.environ.get("PYTHONPATH", ""), "OTEL_SDK_DISABLED": "true"},
        )
        async with asyncio.timeout(20), McpClient(params) as client:
            result = await client.call_tool(
                "what_if", {"weights": {"SYNTH:A": 0.5}, "shocks": {"SYNTH:A": -0.2}}
            )
            self.assertFalse(result.is_error)
            self.assertAlmostEqual(result.structured_content["portfolio_return"], -0.1)


class SchemaAndSafety(unittest.TestCase):
    def test_local_schema_definitions_and_examples(self):
        from jsonschema import Draft202012Validator

        schema = json.loads((Path(__file__).parents[1] / "schemas/contracts-v1.json").read_text())
        Draft202012Validator.check_schema(schema)

        def validate(name, value):
            Draft202012Validator({**schema, "$ref": "#/$defs/" + name}).validate(value)

        report = demo()
        validate("ResearchRequest", report["request"])
        validate("ResearchDossier", report)
        for item in report["evidence"]:
            validate("EvidenceItem", item)
        for item in report["claims"]:
            validate("Claim", item)
        store = MemoryStore()
        validate(
            "WatchlistItem",
            store.watch(
                identifier="synthetic-w",
                instrument="SYNTH:A",
                reason=None,
                now=report["generated_at"],
                user_requested=True,
                source_request_ref="synthetic:req",
            ),
        )
        validate(
            "DecisionRecord",
            store.record_decision(
                identifier="synthetic-d",
                dossier_ref=report["dossier_id"],
                dossier_version=1,
                decision="defer",
                user_statement="Synthetic: defer",
                now=report["generated_at"],
            ),
        )

    def test_denial_and_config_fail_before_disk_or_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "not-created"
            client = Client(target, online=True, sec_contact="contact@example.com")
            with self.assertRaises(DataError):
                client.get("yahoo", "https://invalid.invalid")
            with self.assertRaises(DataError):
                client.get("sec", "https://data.sec.gov/submissions/CIK0000000001.json")
            self.assertFalse(target.exists())
            with self.assertRaises(DataError):
                client.get("sec", "https://data.sec.gov/submissions/CIK0000000001.json?arbitrary=1")
            self.assertFalse(target.exists())

    def test_missing_optional_package_no_install_or_io(self):
        import builtins

        actual = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name == "mcp.server":
                raise ImportError("synthetic missing optional package")
            return actual(name, *args, **kwargs)

        with (
            patch("builtins.__import__", side_effect=guarded),
            self.assertRaises(DataError) as error,
        ):
            create_server()
        self.assertEqual(error.exception.code, "capability_unavailable")

    def test_context_persistence_and_save_failure_are_real(self):
        store = MemoryStore()
        field = {"value": None, "status": "declined", "scope": "session"}
        store.context("portfolio_context", field, user_requested=True)
        self.assertEqual(store.snapshot()["context"]["portfolio_context"], field)
        with self.assertRaises(DataError):
            store.context("x", {**field, "scope": "persistent"}, user_requested=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private = FileStore(root / "private", repository_root=root / "repo", user_enabled=True)
            with (
                patch("global_stock_data.store.os.replace", side_effect=OSError("synthetic")),
                self.assertRaises(DataError) as error,
            ):
                private.save(user_requested=True)
            self.assertEqual(error.exception.code, "save_failed")
            self.assertFalse(private.path.exists())

    def test_supplemental_gap_and_explicit_publication_freshness(self):
        base = demo()
        extra = {**base["evidence"][0], "id": "supplement", "status": "partial", "critical": False}
        report = dossier(
            base["request"], base["evidence"] + [extra], base["claims"], now=base["generated_at"]
        )
        self.assertEqual(report["data_status"], "partial")
        self.assertEqual(report["readiness"], "answerable")
        evidence = [
            {
                **base["evidence"][0],
                "observed_at": None,
                "freshness_basis": "published_at",
                "published_at": "2026-01-02T15:00:00Z",
                "max_age_seconds": 7200,
            }
        ]
        report = dossier(base["request"], evidence, base["claims"], now=base["generated_at"])
        self.assertEqual(report["data_status"], "ok")
        with self.assertRaises(DataError):
            dossier(
                base["request"],
                [{**evidence[0], "freshness_basis": "fetched_at"}],
                base["claims"],
                now=base["generated_at"],
            )
