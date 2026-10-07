import copy
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from global_stock_data.adapters import fetch
from global_stock_data.cli import main as cli_main
from global_stock_data.errors import DataError
from global_stock_data.http import Client, Response
from global_stock_data.mcp_server import bounded_fetch, main
from global_stock_data.options import chain_summary, filter_expiry
from global_stock_data.policy import authorize
from global_stock_data.sec import Sec, require_backtest_safe
from global_stock_data.sec_queries import frame_period, frame_rows, frame_selection

FIXTURES = Path(__file__).parent / "fixtures"
FRAME_ARGS = {
    "taxonomy": "us-gaap",
    "tag": "EarningsPerShareDiluted",
    "unit": "USD-per-shares",
    "period": "CY2025Q1",
    "kind": "duration",
}
SEARCH_ARGS = {
    "query": '"synthetic research"',
    "date_from": "2025-01-01",
    "date_to": "2025-12-31",
    "page_size": 2,
    "max_pages": 2,
    "forms": "10-Q",
}


class Extensions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.calls = []
        self.responses = []
        self.time = 1735689600.0
        self.client = Client(
            Path(self.temp.name),
            online=True,
            sec_contact="offline-test@synthetic-fixture.org",
            sender=self.send,
            clock=lambda: self.time,
            sleep=self.sleep,
        )

    def sleep(self, seconds):
        self.time += seconds

    def send(self, url, headers, timeout):
        self.calls.append((url, headers))
        return self.responses.pop(0)

    def fixture(self, name):
        return Response(200, {}, (FIXTURES / name).read_bytes())

    def fails(self, code, fn, *args, **kwargs):
        with self.assertRaises(DataError) as error:
            fn(*args, **kwargs)
        self.assertEqual(error.exception.code, code)

    def test_frames_raw_context_null_eps_and_no_pit(self):
        self.responses = [self.fixture("frame-duration-synthetic.json")]
        result = fetch(self.client, "sec_frames", FRAME_ARGS)
        self.assertEqual(result["data_status"], "partial")
        row = result["records"][0]
        self.assertEqual(row["unit"], "USD/shares")
        self.assertEqual(row["actual_data_date"], "2025-03-31")
        self.assertEqual(row["data"]["accession"], "synthetic-a")
        self.assertEqual(row["data"]["start"], "2025-01-01")
        self.assertEqual(row["data"]["filed"], "2025-04-20")
        self.assertEqual(row["data"]["val"], 1.234567)
        self.assertIsNone(result["records"][1]["data"]["val"])
        self.assertIn("USD-per-shares", self.calls[0][0])
        self.assertIn("offline-test@", self.calls[0][1]["User-Agent"])
        self.fails("point_in_time_blocked", require_backtest_safe, result)
        self.assertEqual(frame_period(2025, quarter=1, kind="instant"), "CY2025Q1I")
        self.fails("input", frame_period, 2025, kind="instant")
        self.fails("input", Sec(self.client).frames, **{**FRAME_ARGS, "unit": "USD"})
        self.assertEqual(len(self.calls), 1)

    def test_frame_instant_duration_conflict_and_no_fallback(self):
        raw = json.loads((FIXTURES / "frame-instant-synthetic.json").read_text())
        args = {
            **FRAME_ARGS,
            "tag": "Assets",
            "unit": "USD",
            "period": "CY2025Q1I",
            "kind": "instant",
        }
        rows = frame_rows(raw, **args)
        self.assertIsNone(rows[0]["start"])
        raw["data"][0]["start"] = "2025-01-01"
        self.fails("schema", frame_rows, raw, **args)
        self.fails("input", frame_rows, raw, **{**args, "kind": "duration"})
        self.responses = [Response(404, {}, b"")]
        self.fails("missing", Sec(self.client).frames, **args)
        self.assertEqual(len(self.calls), 1)
        raw = json.loads((FIXTURES / "frame-duration-synthetic.json").read_text())
        raw["pts"] = 3
        raw["data"].append(copy.deepcopy(raw["data"][0]))
        self.fails("conflict", frame_rows, raw, **FRAME_ARGS)

    def test_frame_rank_screen_context_and_unknowns(self):
        raw = json.loads((FIXTURES / "frame-duration-synthetic.json").read_text())
        rows = frame_rows(raw, **FRAME_ARGS)
        self.assertEqual(frame_selection(rows, top=1)["excluded_unknown_values"], 1)
        self.assertEqual(frame_selection(rows, min_value=2)["rows"], [])
        rows[1]["start"] = "2024-12-30"
        self.fails("incomparable", frame_selection, rows, top=1)
        self.assertEqual(
            frame_selection(rows, top=1, allow_calendar_approximation=True)["comparison_basis"],
            "calendar_approximation",
        )
        rows[1]["unit"] = "shares"
        self.fails("incomparable", frame_selection, rows, allow_calendar_approximation=True)

    def test_search_two_pages_exact_coverage_date_and_evidence(self):
        self.responses = [
            self.fixture("fts-page0-synthetic.json"),
            self.fixture("fts-page1-synthetic.json"),
        ]
        result = fetch(self.client, "sec_fulltext_search", SEARCH_ARGS)
        self.assertEqual(result["data_status"], "ok")
        self.assertEqual(result["coverage"], "end_of_query_reached")
        self.assertEqual(len(result["records"]), 3)
        self.assertEqual(result["records"][2]["actual_data_date"], "2025-06-20")
        self.assertEqual(result["source_metadata"]["pages_retrieved"], 2)
        self.assertFalse(result["source_metadata"]["earliest_mention_established"])
        self.assertNotEqual(
            result["records"][0]["evidence_ref"], result["records"][2]["evidence_ref"]
        )
        self.assertIn("from=2", self.calls[1][0])
        self.assertTrue(all("@" in headers["User-Agent"] for _, headers in self.calls))
        self.assertTrue((Path(self.temp.name) / "sec-budget.sqlite").exists())

    def test_search_lower_bounds_empty_and_limits(self):
        page = json.loads((FIXTURES / "fts-page0-synthetic.json").read_text())
        page["hits"]["total"]["relation"] = "gte"
        page["hits"]["hits"] = []
        self.responses = [Response(200, {}, json.dumps(page).encode())]
        result = Sec(self.client).fulltext_search(**SEARCH_ARGS)
        self.assertEqual(result["completeness"], "bounded_partial")
        self.responses = [self.fixture("fts-page0-synthetic.json")]
        self.assertEqual(
            Sec(self.client).fulltext_search(**{**SEARCH_ARGS, "query": "other", "max_pages": 1})[
                "completeness"
            ],
            "bounded_partial",
        )
        for changes in ({"max_pages": 11}, {"page_size": 101}, {"date_from": "2026-01-01"}):
            self.fails("input", Sec(self.client).fulltext_search, **{**SEARCH_ARGS, **changes})
        self.fails(
            "url_denied",
            authorize,
            "sec",
            self.calls[0][0] + "&url=https://evil.invalid",
            online=True,
        )

    def test_search_duplicates_conflicts_schema_and_permission(self):
        page0 = json.loads((FIXTURES / "fts-page0-synthetic.json").read_text())
        page1 = copy.deepcopy(page0)
        self.responses = [Response(200, {}, json.dumps(p).encode()) for p in (page0, page1)]
        result = Sec(self.client).fulltext_search(**SEARCH_ARGS)
        self.assertEqual(result["duplicate_hits"], 2)
        self.assertEqual(result["completeness"], "bounded_partial")
        self.assertEqual(len(result["rows"]), 2)
        page1["hits"]["hits"][0]["_source"]["root_form"] = "8-K"
        self.responses = [Response(200, {}, json.dumps(p).encode()) for p in (page0, page1)]
        self.fails(
            "conflict", Sec(self.client).fulltext_search, **{**SEARCH_ARGS, "query": "conflict"}
        )
        self.responses = [Response(403, {}, b"AccessDenied")]
        count = len(self.calls)
        self.fails(
            "forbidden", Sec(self.client).fulltext_search, **{**SEARCH_ARGS, "query": "forbidden"}
        )
        self.assertEqual(len(self.calls), count + 1)
        self.responses = [Response(200, {}, b'{"hits":{}}')]
        self.fails("schema", Sec(self.client).fulltext_search, **{**SEARCH_ARGS, "query": "bad"})

    def test_options_expiry_and_dte_from_et_snapshot(self):
        rows = [{"expiry": "2025-01-01"}, {"expiry": "2025-01-02"}, {"expiry": "2025-01-05"}]
        snapshot = "2025-01-02T02:00:00Z"  # Still Jan 1 in ET.
        self.assertEqual(
            filter_expiry(rows, snapshot_at=snapshot, expiry="0DTE")["contracts"][0]["expiry"],
            "2025-01-01",
        )
        selected = filter_expiry(rows, snapshot_at=snapshot, dte_min=1, dte_max=3)
        self.assertEqual([r["dte_calendar_days"] for r in selected["contracts"]], [1])
        self.assertEqual(
            len(filter_expiry(rows, snapshot_at=snapshot, expiry="2025-01-05")["contracts"]), 1
        )
        self.fails("input", filter_expiry, rows, snapshot_at=snapshot, dte_min=4, dte_max=1)
        self.fails("schema", filter_expiry, [{}], snapshot_at=snapshot)

    def test_options_counts_ratios_missing_and_adjusted_multipliers(self):
        rows = [
            {
                "contract_id": "SYNTH:C",
                "side": "C",
                "volume": 10,
                "open_interest": 20,
                "multiplier": 10,
                "iv": 0.2,
                "iv_unit": "fraction",
            },
            {
                "contract_id": "SYNTH:P",
                "side": "P",
                "volume": 5,
                "open_interest": 30,
                "multiplier": 100,
                "iv": 0.4,
                "iv_unit": "fraction",
            },
        ]
        result = chain_summary(rows)
        self.assertEqual(result["put_call_volume_ratio"], 0.5)
        self.assertEqual(result["put_call_open_interest_ratio"], 1.5)
        self.assertEqual(result["actual_multipliers"], [10, 100])
        self.assertAlmostEqual(result["volume_weighted_iv"], (10 * 0.2 + 5 * 0.4) / 15)
        self.assertNotIn("net_delta_exposure", result)
        rows[0]["volume"] = None
        rows[0]["multiplier"] = None
        missing = chain_summary(rows)
        self.assertIsNone(missing["put_call_volume_ratio"])
        self.assertIsNone(missing["call_volume"]["value"])
        self.assertIsNone(missing["volume_weighted_iv"])
        self.assertEqual(missing["unknown_multiplier_contracts"], 1)
        rows[0]["volume"] = 0
        self.assertIsNone(chain_summary(rows)["put_call_volume_ratio"])
        self.fails("conflict", chain_summary, [rows[0], rows[0]])
        self.fails("schema", chain_summary, [{**rows[0], "volume": -1}])
        self.fails("schema", chain_summary, [{**rows[0], "iv_unit": "percent"}])

    def test_local_option_cli_complete_workflow(self):
        path = Path(__file__).parents[1] / "examples/options-synthetic.json"
        with redirect_stdout(io.StringIO()) as output:
            result = cli_main(
                [
                    "options",
                    str(path),
                    "--snapshot-at",
                    "2026-01-02T16:00:00Z",
                    "--dte-min",
                    "0",
                    "--dte-max",
                    "7",
                ]
            )
        self.assertEqual(result, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["summary"]["put_call_volume_ratio"], 0.5)
        self.assertEqual(report["summary"]["actual_multipliers"], [10, 100])
        self.assertEqual(report["snapshot_date_et"], "2026-01-02")

    def test_mcp_operator_policy_and_truncated_read(self):
        blocked = bounded_fetch("sec_frames", FRAME_ARGS)
        self.assertEqual(blocked["data_status"], "permission_blocked")
        self.assertEqual(self.calls, [])
        self.responses = [self.fixture("treasury-synthetic.xml")]
        result = bounded_fetch(
            "treasury_daily_nominal_par",
            {"year": 2026},
            limit=1,
            client=self.client,
            allowed_providers=("treasury",),
        )
        self.assertEqual(result["data_status"], "partial")
        self.assertTrue(result["output_truncated"])
        self.assertNotIn("rows", result["source_metadata"])
        self.assertEqual(result["returned_count"], 1)
        denied = bounded_fetch(
            "sec_frames", FRAME_ARGS, client=self.client, allowed_providers=("treasury",)
        )
        self.assertEqual(denied["data_status"], "permission_blocked")
        injection = bounded_fetch(
            "treasury_daily_nominal_par",
            {"year": 2026, "online": True, "url": "https://evil.invalid"},
            client=self.client,
            allowed_providers=("treasury",),
        )
        self.assertEqual(injection["data_status"], "error")
        self.assertEqual(len(self.calls), 1)
        self.fails("input", bounded_fetch, "sec_frames", FRAME_ARGS, limit=101)

    def test_mcp_startup_rejects_missing_contact_and_incomplete_optin(self):
        with (
            patch(
                "sys.argv",
                ["gsd-mcp", "--online", "--provider", "sec", "--state-dir", self.temp.name],
            ),
            patch.dict(os.environ, {"SEC_CONTACT": ""}),
        ):
            self.fails("config", main)
        with (
            patch("sys.argv", ["gsd-mcp", "--provider", "treasury"]),
            redirect_stderr(io.StringIO()),
        ):
            self.fails("config", main)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])
