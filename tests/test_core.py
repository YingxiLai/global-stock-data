import io
import json
import multiprocessing
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path

from global_stock_data.cli import demo, main
from global_stock_data.errors import DataError
from global_stock_data.http import Client, Payload, Response, SharedBudget
from global_stock_data.indicators import bollinger, ema, kdj, macd, rsi, sma, validate_bars
from global_stock_data.local import finra_volume, scaled_quote, yahoo_bars
from global_stock_data.macro import cot, cot_rows, spread_basis_points, treasury, treasury_xml
from global_stock_data.options import activity, parse_osi, signed_delta_exposure, zero_dte
from global_stock_data.policy import authorize
from global_stock_data.records import Record, compare, evidence_hash, instant, number
from global_stock_data.research import (
    alert,
    decision_record,
    dispatch,
    dossier,
    validate_request,
    what_if,
)
from global_stock_data.sec import (
    Sec,
    cik,
    company_facts,
    parse_index,
    require_backtest_safe,
    submissions,
)

FIXTURES = Path(__file__).parent / "fixtures"
SEC_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json"
# Fictional value exists only in an injected transport. Never used for an online request.
TEST_CONTACT = "offline-test@synthetic-fixture.org"


def reserve_worker(path, queue):
    queue.put(SharedBudget(Path(path)).reserve(100.0))


class Base(unittest.TestCase):
    def raises_code(self, code, fn, *args, **kwargs):
        with self.assertRaises(DataError) as error:
            fn(*args, **kwargs)
        self.assertEqual(error.exception.code, code)


class HttpTests(Base):
    def test_treasury_documented_endpoint_and_query_scope(self):
        url = (
            "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
            "?data=daily_treasury_yield_curve&field_tdr_date_value=2026"
        )
        self.responses = [Response(200, {}, (FIXTURES / "treasury-synthetic.xml").read_bytes())]
        result = treasury(self.client, 2026)
        self.assertEqual(result["source_url"], url)
        self.assertEqual(self.calls[0][0], url)
        self.assertEqual(result["rows"][0]["unit"], "percent")
        self.raises_code(
            "url_denied",
            authorize,
            "treasury",
            url.replace("resource-center/data-chart-center", "resource-center-data-chart-center"),
            online=True,
        )
        self.raises_code("url_denied", authorize, "treasury", url + "&all=1", online=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.time = 100.0
        self.calls = []
        self.responses = [Response(200, {}, b'{"value": null}')]
        self.client = Client(
            Path(self.temp.name),
            online=True,
            sec_contact=TEST_CONTACT,
            sender=self.send,
            clock=lambda: self.time,
            sleep=self.sleep,
        )

    def sleep(self, seconds):
        self.time += seconds

    def send(self, url, headers, timeout):
        self.calls.append((url, headers, timeout))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def test_cache_provenance_and_expiry(self):
        a = self.client.get("sec", SEC_URL)
        b = self.client.get("sec", SEC_URL)
        self.assertFalse(a.cached)
        self.assertTrue(b.cached)
        self.assertEqual(a.fetched_at, b.fetched_at)
        self.assertEqual(a.json(), {"value": None})
        self.time += 301
        self.responses = [Response(200, {}, b"{}")]
        c = self.client.get("sec", SEC_URL)
        self.assertNotEqual(a.fetched_at, c.fetched_at)
        self.assertEqual(len(self.calls), 2)

    def test_failure_paths_no_permission_retry_or_fallback(self):
        for status, code in [
            (403, "forbidden"),
            (401, "unauthorized"),
            (404, "missing"),
            (302, "http"),
            (418, "http"),
        ]:
            self.responses = [Response(status, {}, b"<Error><Code>AccessDenied</Code></Error>")]
            count = len(self.calls)
            self.raises_code(code, self.client.get, "sec", SEC_URL, ttl=0)
            self.assertEqual(len(self.calls), count + 1)

    def test_retry_after_and_bounded_errors(self):
        self.responses = [Response(429, {"retry-after": "2"}, b""), Response(200, {}, b"{}")]
        self.client.get("sec", SEC_URL)
        self.assertEqual(self.time, 102)
        self.responses = [Response(503, {"retry-after": "61"}, b"")]
        self.raises_code("rate_limited", self.client.get, "sec", SEC_URL, ttl=0)
        self.responses = [Response(500, {}, b"")] * 3
        self.raises_code("server", self.client.get, "sec", SEC_URL, ttl=0)
        self.responses = [Response(429, {}, b"")] * 3
        self.raises_code("rate_limited", self.client.get, "sec", SEC_URL, ttl=0)

    def test_network_timeout_and_schema(self):
        self.responses = [DataError("timeout", "synthetic")] * 3
        self.raises_code("timeout", self.client.get, "sec", SEC_URL)
        self.responses = [DataError("network", "synthetic"), Response(200, {}, b"invalid")]
        self.raises_code("schema", self.client.get("sec", SEC_URL).json)
        self.raises_code("schema", Payload(b'{"x":NaN}', "", "", False).json)
        self.assertEqual(
            self.client.retry_delay("Thu, 01 Jan 1970 00:02:00 GMT", 0), 120 - self.time
        )
        self.assertEqual(self.client.retry_delay("invalid", 1), 2)

    def test_policy_and_contact_before_any_request(self):
        for provider in (
            "cboe",
            "yahoo",
            "finra",
            "eastmoney",
            "sina",
            "tencent",
            "nasdaq",
            "hkex",
            "unknown",
        ):
            self.raises_code("license_denied", self.client.get, provider, "https://invalid.invalid")
        self.client.online = False
        self.raises_code("offline", self.client.get, "sec", SEC_URL)
        self.client.online = True
        for url in [
            "http://data.sec.gov/submissions/CIK0000000001.json",
            "https://data.sec.gov.evil.invalid/submissions/CIK0000000001.json",
            "https://data.sec.gov/private",
            SEC_URL + "#x",
            "https://user:password@data.sec.gov/submissions/CIK0000000001.json",
        ]:
            self.raises_code("url_denied", self.client.get, "sec", url)
        self.client.sec_contact = "contact@example.com"
        self.raises_code("config", self.client.get, "sec", SEC_URL)
        self.assertEqual(self.calls, [])

    def test_shared_window_and_cooldown(self):
        budget = SharedBudget(Path(self.temp.name) / "shared.sqlite")
        for _ in range(8):
            self.assertEqual(budget.reserve(100), 0)
        self.assertEqual(budget.reserve(100), 1)
        self.assertEqual(budget.reserve(101), 0)
        budget.defer(104)
        self.assertEqual(budget.reserve(101), 3)
        self.raises_code("schema", SharedBudget, Path(self.temp.name) / "bad.sqlite", 10)

    def test_multiprocess_aggregate_limit(self):
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        path = str(Path(self.temp.name) / "processes.sqlite")
        SharedBudget(Path(path))
        processes = [ctx.Process(target=reserve_worker, args=(path, queue)) for _ in range(12)]
        for process in processes:
            process.start()
        results = [queue.get(timeout=30) for _ in processes]
        for process in processes:
            process.join(30)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(results.count(0), 8)
        self.assertEqual(results.count(1), 4)
        queue.close()

    def test_logs_redacted(self):
        with self.assertLogs("global_stock_data.http", level="INFO") as logs:
            self.client.get("sec", SEC_URL)
        text = " ".join(logs.output)
        self.assertNotIn(TEST_CONTACT, text)
        self.assertNotIn(SEC_URL, text)


class RecordTests(Base):
    def record(self):
        return Record(
            "synthetic",
            "synthetic://quote",
            "2026-01-01T00:00:00+00:00",
            None,
            None,
            "2026-01-01T01:00:00+00:00",
            "America/New_York",
            "currency",
            "USD",
            "1",
            "raw",
            "2025-12-31",
            None,
            "synthetic:1",
            {"value": None},
        )

    def test_numbers_and_units(self):
        for value in [None, "N/A", "", "-"]:
            self.assertIsNone(number(value))
        for value in [True, "bad", "NaN", "Infinity"]:
            self.raises_code("schema", number, value)
        self.assertEqual(number("0.123456789"), 0.123456789)
        a = self.record()
        self.assertEqual(compare(a, a, "value"), "unknown")
        self.assertEqual(
            compare(replace(a, data={"value": 1}), replace(a, data={"value": 2}), "value"),
            "conflict",
        )
        self.raises_code("incomparable", compare, a, replace(a, currency="HKD"), "value")
        self.raises_code(
            "incomparable", compare, replace(a, unit=None), replace(a, unit=None), "value"
        )
        self.assertEqual(a.as_dict()["schema_version"], "1.0")
        self.assertEqual(a.freshness("2026-01-01T01:00:00Z", 3600), "fresh")
        self.assertEqual(a.freshness("2026-01-02T00:00:00Z", 3600), "stale")
        self.assertEqual(a.freshness("2025-12-31T00:00:00Z", 3600), "future")
        self.assertEqual(
            replace(a, observed_at=None).freshness("2026-01-02T00:00:00Z", 3600), "unknown"
        )
        self.raises_code("schema", instant, "2026-01-01")
        self.assertEqual(evidence_hash({"a": 1}), evidence_hash({"a": 1}))


class FinancialTests(Base):
    def test_indicators_seed_flat_gaps(self):
        self.assertEqual(sma([], 2), [])
        self.assertEqual(ema([1, 2, 3], 2), [None, 1.5, 2.5])
        self.assertEqual(rsi([10] * 5, 2), [None, None, 50, 50, 50])
        self.assertEqual(rsi([1, 2, 3, 4], 2)[-1], 100)
        self.assertEqual(rsi([4, 3, 2, 1], 2)[-1], 0)
        self.assertEqual(rsi([1, 2, None, 3, 4, 5], 2)[-1], 100)
        self.assertIsNone(ema([1, 2, None, 3], 2)[-1])
        self.assertNotEqual(
            rsi([1, 2, 4, 3, 1, 4], 2), rsi([1, 2, 4, 3, 1, 4], 2, variant="simple")
        )
        for fn in (sma, ema, rsi, bollinger):
            self.raises_code("input", fn, [1, 2], 0)
        self.raises_code("input", rsi, [1], variant="unknown")
        values = list(range(20))
        a, b = macd(values, 2, 3, 2), macd(values, 2, 3, 2, histogram_scale=2)
        self.assertEqual(b["histogram"][-1], a["histogram"][-1] * 2)
        self.assertEqual(bollinger([1, 1, 1], 2)[-1], {"middle": 1, "upper": 1, "lower": 1})
        self.assertEqual(bollinger([None], 2)[0]["middle"], None)
        bars = [
            {"date": "2026-01-01", "close": 1, "low": 1, "high": 1},
            {"date": "2026-01-02", "close": 1, "low": 1, "high": 1},
        ]
        self.assertEqual(kdj(bars, 2)[-1], {"k": 50, "d": 50, "j": 50})
        self.assertEqual(validate_bars([]), [])
        self.raises_code("input", validate_bars, bars[::-1])
        self.raises_code("input", validate_bars, bars + bars)
        self.raises_code(
            "schema", validate_bars, [{"date": "2026-01-01", "close": 3, "low": 1, "high": 2}]
        )

    def test_options_no_opening_flow_assumption(self):
        parsed = parse_osi("ACME1 260102C00100000")
        self.assertEqual(parsed["strike"], 100)
        self.assertIsNone(parsed["multiplier"])
        self.raises_code("input", parse_osi, "bad")
        self.assertEqual(
            activity(
                [{"volume": 1000, "open_interest": None}, {"volume": 1000, "open_interest": 0}]
            ),
            [],
        )
        self.assertIn(
            "opening_direction_unknown",
            activity([{"volume": 1000, "open_interest": 100}])[0]["interpretation"],
        )
        self.raises_code("schema", signed_delta_exposure, [{"volume": 1000, "delta": 0.5}])
        positions = [
            {
                "signed_quantity": 2,
                "delta": 0.5,
                "multiplier": 10,
                "underlying": "SYNTH:A",
                "deliverable": {"kind": "equity", "underlying": "SYNTH:A", "unit": "shares"},
                "delta_basis": "per_deliverable_unit",
            },
            {
                "signed_quantity": -1,
                "delta": 0.5,
                "multiplier": 10,
                "underlying": "SYNTH:A",
                "deliverable": {"kind": "equity", "underlying": "SYNTH:A", "unit": "shares"},
                "delta_basis": "per_deliverable_unit",
            },
        ]
        self.assertEqual(signed_delta_exposure(positions)["groups"][0]["signed_delta"], 5)
        result = zero_dte(
            [{"expiry": "2026-01-01"}],
            snapshot_at="2026-01-02T00:00:00Z",
            now="2026-01-02T00:01:00Z",
        )
        self.assertEqual(result["expiry"], "2026-01-01")
        self.raises_code(
            "stale", zero_dte, [], snapshot_at="2026-01-01T00:00:00Z", now="2026-01-02T00:00:00Z"
        )
        self.raises_code(
            "stale", zero_dte, [], snapshot_at="2026-01-02T04:59:00Z", now="2026-01-02T05:01:00Z"
        )

    def test_local_quotes_precision_and_metadata(self):
        raw = json.loads((FIXTURES / "yahoo-synthetic.json").read_text())
        output = yahoo_bars(raw, now="2026-01-02T16:00:00Z")
        self.assertIsNone(output["bars"][0]["close"])
        self.assertEqual(output["bars"][1]["close"], 1.23456789)
        self.assertEqual(output["bars"][0]["exchange_date"], "2026-01-01")
        self.assertEqual(output["bars"][1]["adjclose"], 1.1)
        self.assertIsNone(output["bars"][1]["finished_bar"])
        self.raises_code(
            "schema",
            scaled_quote,
            100,
            provider="eastmoney",
            decimal_places=None,
            currency="USD",
            scale=1,
            unit="currency",
        )
        self.assertEqual(
            scaled_quote(
                12345,
                provider="eastmoney",
                decimal_places=3,
                currency="USD",
                scale=1,
                unit="currency",
            )["value"],
            12.345,
        )
        self.assertEqual(
            scaled_quote(
                2,
                provider="tencent",
                decimal_places=0,
                currency="HKD",
                scale=100_000_000,
                unit="currency",
            )["value"],
            200_000_000,
        )

    def test_finra_scope_and_no_duplicates(self):
        text = (FIXTURES / "finra-synthetic.txt").read_text()
        parsed = finra_volume(text, facility="CNMS", revision="synthetic-v1")
        self.assertFalse(parsed["is_whole_market"])
        self.assertFalse(parsed["is_short_interest"])
        self.assertEqual(parsed["rows"][0]["short_volume_ratio"], 0.4)
        self.raises_code(
            "conflict",
            finra_volume,
            text + text.splitlines()[1] + "\n",
            facility="CNMS",
            revision="synthetic-v1",
        )

    def test_macro_dates_na_basis_points(self):
        rows = treasury_xml((FIXTURES / "treasury-synthetic.xml").read_text())
        self.assertEqual(rows[0]["actual_data_date"], "2026-01-02")
        self.assertIsNone(rows[0]["rates"]["1MONTH"])
        self.assertAlmostEqual(spread_basis_points("4.1", "3.9"), 20)
        self.assertIsNone(spread_basis_points("N/A", "3.9"))
        self.raises_code("schema", treasury_xml, "<!DOCTYPE x><x/>")
        self.raises_code("schema", treasury_xml, "invalid")
        row = {
            "report_date_as_yyyy_mm_dd": "2026-01-06T00:00:00",
            "contract_market_name": "SYNTHETIC",
            "cftc_contract_market_code": "SYNTH",
        }
        self.assertEqual(cot_rows([row])[0]["report_type"], "LegacyFuturesOnly")

        class Fake:
            def get(self, provider, url, **kwargs):
                raw = (
                    (FIXTURES / "treasury-synthetic.xml").read_bytes()
                    if provider == "treasury"
                    else json.dumps([row] if "%24offset=0" in url else []).encode()
                )
                return Payload(raw, "2026-01-09T00:00:00Z", "synthetic:1", False)

        self.assertEqual(treasury(Fake(), 2026)["completeness"], "requested_year_only")
        self.assertEqual(
            cot(Fake(), page_size=1, max_pages=2)["completeness"], "end_of_query_reached"
        )
        self.assertEqual(cot(Fake(), page_size=1, max_pages=1)["completeness"], "bounded_partial")


class SecTests(Base):
    def test_full_xbrl_context_asof_revisions(self):
        raw = json.loads((FIXTURES / "xbrl-synthetic.json").read_text())
        rows = company_facts(raw)
        self.assertEqual(len(rows), 4)
        self.assertEqual([r["period_kind"] for r in rows], ["quarter", "quarter", "ytd", "annual"])
        self.assertEqual(rows[0]["unit"], "USD/shares")
        self.assertEqual(rows[0]["frame"], "CY2025Q1")
        self.assertEqual(len(company_facts(raw, as_of="2025-05-01")), 1)
        self.assertEqual(len(company_facts(raw, latest_revision=True)), 3)
        self.raises_code("point_in_time_blocked", require_backtest_safe, rows)
        self.raises_code("unsupported", company_facts, {"facts": {"ifrs-full": {}}})
        self.assertEqual(company_facts({"facts": {}}), [])
        self.assertEqual(cik("1"), "0000000001")
        self.raises_code("input", cik, "../x")

    def test_submissions_not_last50(self):
        columns = {
            "accessionNumber": [f"synth-{i}" for i in range(70)],
            "filingDate": ["2026-01-01"] * 70,
            "form": ["13F-HR"] * 70,
        }
        raw = {
            "filings": {
                "recent": columns,
                "files": [{"name": "CIK0000000001-submissions-001.json"}],
            }
        }
        self.assertEqual(len(submissions(raw)["rows"]), 70)
        self.assertFalse(submissions(raw)["holdings_are_realtime"])

        class Fake:
            def get(self, provider, url, **kwargs):
                data = (
                    {"accessionNumber": ["old"], "filingDate": ["2025-01-01"], "form": ["10-K"]}
                    if "submissions-001" in url
                    else raw
                )
                return Payload(
                    json.dumps(data).encode(), "2026-01-02T00:00:00Z", "synthetic:1", False
                )

        sec = Sec(Fake())
        self.assertEqual(sec.filings("1")["completeness"], "bounded_partial")
        self.assertEqual(len(sec.filings("1", max_history_files=1)["rows"]), 71)
        self.assertEqual(sec.filings("1", max_history_files=1)["remaining_history_files"], 0)
        self.assertEqual(sec.facts("1").evidence_ref, "synthetic:1")
        self.assertEqual(sec.tickers().evidence_ref, "synthetic:1")

    def test_index_fallback_only404_and_actual_date(self):
        text = (FIXTURES / "sec-index-synthetic.idx").read_text()
        self.assertEqual(parse_index(text)[0]["event_date"], "unknown")

        class Fake:
            def __init__(self, code):
                self.code = code

            def get(self, provider, url, **kwargs):
                if "20260102" in url:
                    raise DataError(self.code, "synthetic")
                return Payload(text.encode(), "2026-01-03T00:00:00Z", "synthetic:1", False)

        sec = Sec(Fake("missing"))
        result = sec.daily_index("2026-01-02", max_fallback_days=1, max_data_age_days=1)
        self.assertEqual(result["actual_data_date"], "2026-01-01")
        self.assertEqual(result["fallback_reason"], "requested_index_missing")
        self.raises_code(
            "forbidden",
            Sec(Fake("forbidden")).daily_index,
            "2026-01-02",
            max_fallback_days=1,
            max_data_age_days=1,
        )
        self.raises_code("stale", sec.daily_index, "2026-01-02", max_fallback_days=1)


class ResearchTests(Base):
    def test_demo_and_claim_contract(self):
        report = demo()
        self.assertEqual(report["readiness"], "answerable")
        self.assertFalse(report["answerable_is_buy_signal"])
        request, evidence, claims = report["request"], report["evidence"], report["claims"]
        for state in ["partial", "stale", "no_data", "conflict", "permission_blocked"]:
            result = dossier(
                request, [{**evidence[0], "status": state}], claims, now=report["generated_at"]
            )
            self.assertEqual(
                result["readiness"],
                "blocked" if state == "permission_blocked" else "insufficient_evidence",
            )
            self.assertEqual(result["data_status"], state)
        wide = {**request, "intent": "decision"}
        result = dossier(wide, evidence, claims, now=report["generated_at"])
        self.assertEqual(result["readiness"], "needs_clarification")
        self.assertEqual(len(result["clarifying_questions"]), 2)
        self.raises_code(
            "schema",
            dossier,
            request,
            evidence,
            [{"kind": "fact", "text": "x", "evidence_ids": []}],
            now=report["generated_at"],
        )
        self.raises_code(
            "schema",
            dossier,
            request,
            evidence,
            [{"kind": "inference", "text": "x", "evidence_ids": ["demo-1"]}],
            now=report["generated_at"],
        )
        self.raises_code("autonomy_denied", validate_request, {**request, "autonomy": "trade"})
        self.assertEqual(
            dossier(request, evidence, claims, now="2026-01-04T00:00:00Z")["data_status"], "stale"
        )

    def test_human_decision_record(self):
        report = demo()
        self.raises_code(
            "approval_required",
            decision_record,
            report,
            decision="watch",
            rationale="review",
            user_approved=True,
            review_on="2026-02-01T00:00:00Z",
        )
        report["request"]["autonomy"] = "draft"
        record = decision_record(
            report,
            decision="watch",
            rationale="review evidence",
            user_approved=True,
            confirmation_ref="synthetic:human-confirmation",
            review_on="2026-02-01T00:00:00Z",
        )
        self.assertEqual(record["execution"], "human_only")
        self.raises_code(
            "autonomy_denied",
            decision_record,
            report,
            decision="buy",
            rationale="x",
            user_approved=True,
            confirmation_ref="synthetic:human-confirmation",
            review_on="2026-02-01T00:00:00Z",
        )
        report["readiness"] = "insufficient_evidence"
        self.raises_code(
            "evidence_blocked",
            decision_record,
            report,
            decision="watch",
            rationale="x",
            user_approved=True,
            review_on="2026-02-01T00:00:00Z",
        )

    def test_whatif_and_alert_cooldown(self):
        self.assertAlmostEqual(
            what_if({"SYNTH:A": 0.5}, {"SYNTH:A": -0.2})["portfolio_return"], -0.1
        )
        self.assertEqual(
            what_if({"SYNTH:A": 0.5}, {"SYNTH:A": 0}, max_weight=0.2)["concentration_breaches"],
            ["SYNTH:A"],
        )
        self.raises_code("schema", what_if, {"SYNTH:A": 1.1}, {"SYNTH:A": 0})
        rule = {"threshold": 10, "direction": "above", "cooldown_seconds": 3600}
        first = alert(rule, value=11, data_status="ok", now="2026-01-01T00:00:00Z")
        self.assertTrue(first["emit"])
        self.assertFalse(
            alert(rule, value=12, data_status="ok", now="2026-01-01T02:00:00Z", previous=first)[
                "emit"
            ]
        )
        reset = alert(rule, value=8, data_status="ok", now="2026-01-01T00:01:00Z", previous=first)
        self.assertFalse(
            alert(rule, value=11, data_status="ok", now="2026-01-01T00:02:00Z", previous=reset)[
                "emit"
            ]
        )
        self.assertTrue(
            alert(rule, value=11, data_status="ok", now="2026-01-01T02:00:00Z", previous=reset)[
                "emit"
            ]
        )
        self.assertFalse(
            alert(rule, value=11, data_status="stale", now="2026-01-01T02:00:00Z")["emit"]
        )
        self.raises_code("tool_denied", dispatch, "place_order", {})
        self.assertEqual(
            dispatch("what_if", {"weights": {"SYNTH:A": 1}, "shocks": {"SYNTH:A": 0}})[
                "portfolio_return"
            ],
            0,
        )

    def test_cli_json_and_offline_default(self):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(["demo"]), 0)
        self.assertEqual(json.loads(out.getvalue())["data_status"], "ok")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["sources"]), 0)
        with redirect_stdout(io.StringIO()) as research_out:
            self.assertEqual(
                main(
                    [
                        "research",
                        str(FIXTURES / "research-synthetic.json"),
                        "--now",
                        "2026-01-02T16:00:00Z",
                    ]
                ),
                0,
            )
        report = json.loads(research_out.getvalue())
        self.assertEqual(report["original_request"], "Inspect synthetic revenue")
        self.assertEqual(report["data_status"], "ok")
        self.assertEqual(report["readiness"], "answerable")
        self.assertTrue(report["claims"][0]["supported"])
        self.assertEqual(report["evidence"][0]["evidence_ref"], "synthetic:acme-v1")
        with redirect_stderr(io.StringIO()) as err:
            self.assertEqual(main(["sec-facts", "1"]), 2)
        self.assertEqual(json.loads(err.getvalue())["error"]["code"], "offline")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(
                main(["research", "/definitely/missing", "--now", "2026-01-02T16:00:00Z"]), 2
            )


if __name__ == "__main__":
    unittest.main()
