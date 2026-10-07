"""Own synthetic regressions for review 3b35ad5, with unchanged prior tests."""

import asyncio
import copy
import importlib.util
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_extensions import FRAME_ARGS, SEARCH_ARGS

from global_stock_data.adapters import fetch
from global_stock_data.cli import demo
from global_stock_data.errors import DataError
from global_stock_data.http import Client, Payload, Response
from global_stock_data.mcp_server import bounded_fetch, create_server
from global_stock_data.options import chain_summary
from global_stock_data.research import decision_record, dossier, what_if
from global_stock_data.sec import Sec, company_facts
from global_stock_data.sec_queries import frame_rows, frame_selection
from global_stock_data.store import FileStore, MemoryStore

FIXTURES = Path(__file__).parent / "fixtures"
NOW = "2026-01-02T16:00:00Z"
POISON = {
    "_source_url": "https://evil.invalid/forged",
    "_evidence_ref": "sha256:forged",
    "_fetched_at": "2027-01-01T00:00:00Z",
    "row_provenance": {"source_url": "https://evil.invalid/forged"},
}
FALSE_LIKE = (False, "false", "true", 1, 0, None, {}, [], {"approved": True})


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class Pages:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, provider, url, **kwargs):
        self.urls.append(url)
        return Payload(
            json.dumps(self.responses.pop(0)).encode(),
            NOW,
            "synthetic:acquired-" + str(len(self.urls)),
            False,
        )


class BoundaryRegressions(unittest.TestCase):
    def fails(self, code, function, *args, **kwargs):
        with self.assertRaises(DataError) as error:
            function(*args, **kwargs)
        self.assertEqual(error.exception.code, code)

    def assert_acquisition(self, record, url, reference):
        self.assertEqual(record["source_url"], url)
        self.assertEqual(record["evidence_ref"], reference)
        self.assertEqual(record["fetched_at"], NOW)

    def test_B1_frames_isolate_raw_fields_from_actual_client_provenance(self):
        raw = fixture("frame-duration-synthetic.json")
        raw["data"][0].update(POISON, unit="forged-unit", source_url="forged")
        raw.update(POISON)
        with tempfile.TemporaryDirectory() as directory:
            calls = []

            def sender(url, headers, timeout):
                calls.append(url)
                return Response(200, {}, json.dumps(raw).encode())

            client = Client(
                Path(directory),
                online=True,
                sec_contact="offline-test@synthetic-fixture.org",
                sender=sender,
            )
            result = fetch(client, "sec_frames", FRAME_ARGS)
            record = result["records"][0]
            self.assertEqual(record["source_url"], calls[0])
            self.assertEqual(record["evidence_ref"], result["source_metadata"]["evidence_ref"])
            self.assertEqual(record["fetched_at"], result["source_metadata"]["fetched_at"])
            self.assertEqual(record["data"]["raw"]["_evidence_ref"], POISON["_evidence_ref"])
            self.assertNotIn("_source_url", record["data"])
            self.assertEqual(record["unit"], "USD/shares")
            raw["data"][0]["_evidence_ref"] = "changed-input"
            self.assertEqual(record["data"]["raw"]["_evidence_ref"], POISON["_evidence_ref"])

    def test_B1_fts_preserves_hostile_hit_but_page_provenance_wins(self):
        first, second = fixture("fts-page0-synthetic.json"), fixture("fts-page1-synthetic.json")
        for page in (first, second):
            for hit in page["hits"]["hits"]:
                hit.update(POISON)
        pages = Pages(first, second)
        result = fetch(pages, "sec_fulltext_search", SEARCH_ARGS)
        for index, record in enumerate(result["records"]):
            page = 0 if index < 2 else 1
            self.assert_acquisition(record, pages.urls[page], "synthetic:acquired-" + str(page + 1))
            self.assertEqual(record["data"]["_source_url"], POISON["_source_url"])
        duplicate = Pages(first, first)
        self.assertEqual(
            fetch(duplicate, "sec_fulltext_search", SEARCH_ARGS)["data_status"], "partial"
        )

    def test_B1_filings_provenance_stays_aligned_after_sort(self):
        columns = {
            "accessionNumber": ["recent"],
            "filingDate": ["2025-01-01"],
            "form": ["10-Q"],
            **{key: [value] for key, value in POISON.items()},
        }
        root = {
            "filings": {
                "recent": columns,
                "files": [{"name": "CIK0000000001-submissions-001.json"}],
            }
        }
        history = {
            "accessionNumber": ["history"],
            "filingDate": ["2025-02-01"],
            "form": ["10-Q"],
            **{key: [value] for key, value in POISON.items()},
        }
        pages = Pages(root, history)
        result = fetch(pages, "sec_filings", {"identifier": "1", "max_history_files": 1})
        self.assertEqual(result["data_status"], "ok")
        for index, record in enumerate(result["records"]):
            page = 1 - index
            self.assert_acquisition(record, pages.urls[page], "synthetic:acquired-" + str(page + 1))

    def test_B1_cot_and_single_payload_adapters_ignore_row_provenance(self):
        rows = [
            {
                "report_date_as_yyyy_mm_dd": stamp,
                "contract_market_name": "Synthetic",
                "cftc_contract_market_code": "SYNTH",
                **POISON,
            }
            for stamp in ("2025-01-01", "2025-02-01")
        ]
        rows[0]["_source"] = "unrelated raw content"
        pages = Pages([rows[0]], [rows[1]])
        result = fetch(pages, "cftc_legacy_futures_only", {"page_size": 1, "max_pages": 2})
        for index, record in enumerate(result["records"]):
            page = 1 - index
            self.assert_acquisition(record, pages.urls[page], "synthetic:acquired-" + str(page + 1))
        pages = Pages({"0": {"cik_str": 1, "ticker": "SYNTH", **POISON}})
        result = fetch(pages, "sec_tickers", {})
        self.assert_acquisition(result["records"][0], pages.urls[0], "synthetic:acquired-1")
        self.assertIsNone(result["records"][0]["actual_data_date"])
        raw = fixture("xbrl-synthetic.json")
        for tags in raw["facts"].values():
            for item in tags.values():
                for observations in item["units"].values():
                    for observation in observations:
                        observation.update(POISON)
                        observation["_source"] = "unrelated raw content"
        pages = Pages(raw)
        result = fetch(pages, "sec_company_facts", {"cik": "1"})
        for record in result["records"]:
            self.assert_acquisition(record, pages.urls[0], "synthetic:acquired-1")

    def test_B2_helper_requires_true_and_explicit_confirmation_reference(self):
        report = demo()
        report["request"]["autonomy"] = "draft"
        args = {
            "decision": "watch",
            "rationale": "Synthetic review",
            "review_on": "2026-02-01T00:00:00Z",
        }
        for approval in FALSE_LIKE:
            with self.subTest(approval=approval):
                self.fails(
                    "approval_required",
                    decision_record,
                    report,
                    **args,
                    user_approved=approval,
                    confirmation_ref="synthetic:human",
                )
        for reference in (None, "", "   ", True, 1, {}, []):
            self.fails(
                "approval_required",
                decision_record,
                report,
                **args,
                user_approved=True,
                confirmation_ref=reference,
            )
        record = decision_record(
            report, **args, user_approved=True, confirmation_ref="synthetic:human"
        )
        self.assertIs(record["user_approved"], True)
        self.assertEqual(record["confirmation_ref"], "synthetic:human")

    def decision_args(self):
        return {
            "identifier": "synthetic-decision",
            "dossier_ref": "synthetic:dossier",
            "dossier_version": 1,
            "decision": "defer",
            "user_statement": "Synthetic defer",
            "now": NOW,
        }

    def test_B2_store_types_states_and_references_are_consistent(self):
        for approval in FALSE_LIKE[1:]:
            self.fails(
                "approval_required",
                MemoryStore().record_decision,
                **self.decision_args(),
                confirmed=approval,
            )
        proposed = MemoryStore().record_decision(**self.decision_args(), confirmed=False)
        self.assertEqual(
            (proposed["actor"], proposed["state"], proposed["user_approved"]),
            ("proposal", "proposed", False),
        )
        for reference in (None, "", "  ", True, 1, {}, []):
            self.fails(
                "approval_required",
                MemoryStore().record_decision,
                **self.decision_args(),
                confirmed=True,
                confirmation_ref=reference,
            )
        self.assertIs(
            MemoryStore().record_decision(
                **self.decision_args(), confirmed=True, confirmation_ref="synthetic:human"
            )["user_approved"],
            True,
        )

    def test_B2_private_save_and_load_reject_forged_confirmation(self):
        good = MemoryStore().record_decision(
            **self.decision_args(), confirmed=True, confirmation_ref="synthetic:human"
        )
        with tempfile.TemporaryDirectory() as directory:
            private = FileStore(Path(directory), repository_root=Path.cwd(), user_enabled=True)
            for approval in FALSE_LIKE:
                item = {**good, "user_approved": approval}
                private.state["decisions"] = [item]
                self.fails("approval_required", private.save, user_requested=True)
                private.path.write_text(json.dumps(private.state))
                self.fails(
                    "approval_required",
                    FileStore,
                    Path(directory),
                    repository_root=Path.cwd(),
                    user_enabled=True,
                )
            private.state["decisions"] = [good]
            private.save(user_requested=True)
            loaded = FileStore(Path(directory), repository_root=Path.cwd(), user_enabled=True)
            self.assertEqual(loaded.snapshot()["decisions"][0], good)

    def test_B2_schema_rejects_nonboolean_and_inconsistent_approval(self):
        from jsonschema import Draft202012Validator

        schema = json.loads((Path.cwd() / "schemas/contracts-v1.json").read_text())
        validator = Draft202012Validator({**schema, "$ref": "#/$defs/DecisionRecord"})
        good = MemoryStore().record_decision(
            **self.decision_args(), confirmed=True, confirmation_ref="synthetic:human"
        )
        validator.validate(good)
        validator.validate(MemoryStore().record_decision(**self.decision_args()))
        for value in FALSE_LIKE:
            self.assertTrue(list(validator.iter_errors({**good, "user_approved": value})))
        for key, value in (
            ("confirmation_ref", None),
            ("confirmation_ref", " "),
            ("confirmation_ref", True),
            ("actor", "proposal"),
            ("execution_status", "user_reported"),
        ):
            self.assertTrue(list(validator.iter_errors({**good, key: value})))

    def test_B2_all_mutation_gates_require_literal_true(self):
        store = MemoryStore()
        watch_args = {
            "identifier": "synthetic-watch",
            "instrument": "SYNTH:A",
            "reason": None,
            "now": NOW,
            "source_request_ref": "synthetic:q",
        }
        store.watch(**watch_args, user_requested=True)
        field = {"status": "unknown", "scope": "this_request"}
        with tempfile.TemporaryDirectory() as directory:
            private = FileStore(Path(directory), repository_root=Path.cwd(), user_enabled=True)
            for approval in FALSE_LIKE:
                self.fails(
                    "approval_required", MemoryStore().watch, **watch_args, user_requested=approval
                )
                self.fails(
                    "approval_required",
                    store.archive_watch,
                    "synthetic-watch",
                    user_requested=approval,
                )
                self.fails(
                    "approval_required", store.context, "risk", field, user_requested=approval
                )
                self.fails("approval_required", private.save, user_requested=approval)
                self.fails(
                    "persistence_not_enabled",
                    FileStore,
                    Path(directory),
                    repository_root=Path.cwd(),
                    user_enabled=approval,
                )
            self.assertFalse(private.path.exists())
            self.assertEqual(store.snapshot()["watchlist"]["synthetic-watch"]["state"], "watching")

    def test_B3_empty_search_is_no_data_only_for_exact_exhausted_zero(self):
        for relation, total in (("gte", 3), ("eq", 3), ("gte", 0), ("eq", 0)):
            page = {"hits": {"total": {"value": total, "relation": relation}, "hits": []}}
            result = fetch(Pages(page), "sec_fulltext_search", SEARCH_ARGS)
            expected = "no_data" if relation == "eq" and total == 0 else "partial"
            self.assertEqual(result["data_status"], expected)
            self.assertEqual(result["records"], [])
            self.assertEqual(
                result["source_metadata"]["reported_totals"],
                [{"value": total, "relation": relation}],
            )

    def test_N1_requirement_runtime_matches_declared_fields_and_unique_metrics(self):
        from jsonschema import Draft202012Validator

        base = demo()
        schema = json.loads((Path.cwd() / "schemas/contracts-v1.json").read_text())
        validator = Draft202012Validator({**schema, "$ref": "#/$defs/ResearchRequirement"})
        for change in ({"period": "2025Q2"}, {"evidence_metrics": ["revenue", "revenue"]}):
            request = copy.deepcopy(base["request"])
            request["requirements"][0].update(change)
            self.fails("schema", dossier, request, base["evidence"], base["claims"], now=NOW)
            self.assertTrue(list(validator.iter_errors(request["requirements"][0])))

    def test_N2_comparison_and_revision_flags_are_strict_booleans(self):
        rows = frame_rows(fixture("frame-duration-synthetic.json"), **FRAME_ARGS)
        rows[1]["start"] = "2024-12-30"
        self.fails("incomparable", frame_selection, rows, allow_calendar_approximation=False)
        self.assertEqual(
            frame_selection(rows, allow_calendar_approximation=True)["comparison_basis"],
            "calendar_approximation",
        )
        for value in FALSE_LIKE[1:]:
            self.fails("input", frame_selection, rows, allow_calendar_approximation=value)
            self.fails("input", frame_selection, rows, ascending=value)
            self.fails("input", company_facts, {}, latest_revision=value)
        self.fails("input", Sec(Pages()).filings, "1", max_history_files=True)

    def test_N3_huge_finite_option_counts_do_not_overflow_weighted_iv(self):
        contracts = [
            {
                "contract_id": "SYNTH:" + side,
                "side": side,
                "volume": 1e308,
                "open_interest": 1e308,
                "iv": 1e308,
                "iv_unit": "fraction",
            }
            for side in ("C", "P")
        ]
        result = chain_summary(contracts)
        self.assertTrue(math.isfinite(result["volume_weighted_iv"]))
        self.assertEqual(result["volume_weighted_iv"], 1e308)
        self.assertEqual(result["put_call_volume_ratio"], 1)
        json.dumps(result, allow_nan=False)

    def test_N4_direct_concentration_bool_is_rejected(self):
        self.fails("schema", what_if, {"SYNTH:A": 1}, {"SYNTH:A": 0}, max_weight=True)

    def test_N5_all_read_input_and_response_branches_are_bounded(self):
        for capability, arguments, limit in (
            ("A" * 200001, {}, 20),
            ("short", {"q": "x" * 10000}, 20),
            ("short", {}, True),
        ):
            self.fails("input", bounded_fetch, capability, arguments, limit=limit)
        denied = bounded_fetch("unknown_capability", {})
        self.assertLessEqual(len(json.dumps(denied).encode()), 200000)
        with patch("global_stock_data.mcp_server.fetch") as reader:
            reader.return_value = {
                "records": [],
                "data_status": "error",
                "issues": [{"message": "x" * 200001}],
            }
            self.fails(
                "input",
                bounded_fetch,
                "sec_frames",
                {},
                client=object(),
                allowed_providers=("sec",),
            )


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Optional mcp extra absent")
class McpBoundaryRegressions(unittest.IsolatedAsyncioTestCase):
    async def verify_raw_inputs(self, client):
        for field in ("weights", "shocks", "max_weight"):
            args = {"weights": {"SYNTH:A": 1}, "shocks": {"SYNTH:A": -0.1}}
            args[field] = True if field == "max_weight" else {"SYNTH:A": True}
            self.assertTrue((await client.call_tool("what_if", args)).is_error)
        good = await client.call_tool(
            "what_if", {"weights": {"SYNTH:A": "0.5"}, "shocks": {"SYNTH:A": "-0.1"}}
        )
        self.assertFalse(good.is_error)
        self.assertAlmostEqual(good.structured_content["portfolio_return"], -0.05)
        huge = await client.call_tool(
            "research_fetch", {"capability": "A" * 200001, "arguments": {}}
        )
        self.assertTrue(huge.is_error)
        self.assertLessEqual(len(json.dumps(huge.model_dump(mode="json")).encode()), 200000)
        invalid_limit = await client.call_tool(
            "research_fetch", {"capability": "sec_frames", "arguments": {}, "limit": True}
        )
        self.assertTrue(invalid_limit.is_error)
        base = demo()
        args = {
            "request": base["request"],
            "evidence": base["evidence"],
            "claims": base["claims"],
            "now": NOW,
            "max_age_seconds": True,
        }
        self.assertTrue((await client.call_tool("research_dossier", args)).is_error)

    async def test_N4_N5_actual_sdk_preserves_raw_types_and_bounds(self):
        from mcp import Client as McpClient

        with patch.object(Client, "get", side_effect=AssertionError("implicit read")) as reader:
            async with McpClient(create_server()) as client:
                await self.verify_raw_inputs(client)
            self.assertEqual(reader.call_count, 0)

    async def test_N4_N5_actual_stdio_preserves_raw_types_and_bounds(self):
        from mcp import Client as McpClient
        from mcp.client.stdio import StdioServerParameters

        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "global_stock_data.mcp_server"],
            env={"PYTHONPATH": os.environ.get("PYTHONPATH", ""), "OTEL_SDK_DISABLED": "true"},
        )
        async with asyncio.timeout(20), McpClient(params) as client:
            await self.verify_raw_inputs(client)

    async def test_B3_actual_sdk_empty_search_preserves_completeness(self):
        from mcp import Client as McpClient

        with tempfile.TemporaryDirectory() as directory:
            for relation, total in (("gte", 3), ("eq", 3), ("gte", 0), ("eq", 0)):
                page = {"hits": {"total": {"value": total, "relation": relation}, "hits": []}}
                serialized_page = json.dumps(page).encode()

                def sender(*args, body=serialized_page):
                    return Response(200, {}, body)

                read_client = Client(
                    Path(directory) / (relation + str(total)),
                    online=True,
                    sec_contact="offline-test@synthetic-fixture.org",
                    sender=sender,
                )
                server = create_server(read_client=read_client, allowed_providers=("sec",))
                async with McpClient(server) as client:
                    result = await client.call_tool(
                        "research_fetch",
                        {"capability": "sec_fulltext_search", "arguments": SEARCH_ARGS},
                    )
                    self.assertFalse(result.is_error)
                    self.assertEqual(
                        result.structured_content["data_status"],
                        "no_data" if relation == "eq" and total == 0 else "partial",
                    )
