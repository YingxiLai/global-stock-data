"""Own synthetic reproductions of the independent fa8cc99 review, no imported scripts."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from global_stock_data.adapters import fetch
from global_stock_data.cli import demo
from global_stock_data.errors import DataError
from global_stock_data.http import Client, Payload
from global_stock_data.indicators import ema, sma, validate_bars
from global_stock_data.local import scaled_quote, yahoo_bars
from global_stock_data.options import signed_delta_exposure
from global_stock_data.policy import authorize
from global_stock_data.records import Record
from global_stock_data.research import dossier
from global_stock_data.store import FileStore, MemoryStore


class ReviewRegressions(unittest.TestCase):
    def fails(self, code, function, *args, **kwargs):
        with self.assertRaises(DataError) as error:
            function(*args, **kwargs)
        self.assertEqual(error.exception.code, code)

    def test_original_scope_requires_explicit_coverage_not_claim_text(self):
        base = demo()
        request = {
            **base["request"],
            "intent": "compare",
            "question": "Compare synthetic cash and debt.",
        }
        request.pop("requirements")
        cash = {**base["evidence"][0], "metric": "cash"}
        claim = {"kind": "fact", "text": "Cash is 100 USD.", "evidence_ids": ["demo-1"]}
        report = dossier(request, [cash], [claim], now=base["generated_at"])
        self.assertEqual(report["readiness"], "insufficient_evidence")
        request["requirements"] = [
            {
                "id": key,
                "description": "Compare " + key,
                "instrument": "SYNTH:ACME",
                "evidence_metrics": [key],
            }
            for key in ("cash", "debt")
        ]
        claim["requirement_ids"] = ["cash"]
        report = dossier(request, [cash], [claim], now=base["generated_at"])
        self.assertIn("requirement:debt", report["unresolved_parts"])
        self.assertEqual(report["readiness"], "insufficient_evidence")
        debt = {**cash, "id": "debt-1", "metric": "debt"}
        debt_claim = {
            "kind": "fact",
            "text": "Debt is 50 USD.",
            "evidence_ids": ["debt-1"],
            "requirement_ids": ["debt"],
        }
        complete = dossier(request, [cash, debt], [claim, debt_claim], now=base["generated_at"])
        self.assertEqual(complete["readiness"], "answerable")
        debt["instrument"] = "SYNTH:OTHER"
        self.assertEqual(
            dossier(request, [cash, debt], [claim, debt_claim], now=base["generated_at"])[
                "readiness"
            ],
            "insufficient_evidence",
        )

    def test_price_alone_does_not_complete_valuation_decision(self):
        base = demo()
        request = {
            **base["request"],
            "intent": "decision_support",
            "instrument": "SYNTH:ACME",
            "profile": {"horizon": "synthetic year", "risk_budget": "synthetic bound"},
            "requirements": [
                {
                    "id": key,
                    "description": key,
                    "instrument": "SYNTH:ACME",
                    "evidence_metrics": [key],
                }
                for key in ("current_price", "valuation")
            ],
        }
        price = {**base["evidence"][0], "metric": "current_price"}
        claim = {
            "kind": "fact",
            "text": "Synthetic price 100 USD.",
            "evidence_ids": ["demo-1"],
            "requirement_ids": ["current_price"],
        }
        report = dossier(request, [price], [claim], now=base["generated_at"])
        self.assertEqual(report["readiness"], "insufficient_evidence")
        self.assertIn("requirement:valuation", report["unresolved_parts"])
        self.assertIn("current_price_and_valuation_not_supported", report["unresolved_parts"])

    def test_identity_binds_effective_evaluation_rules(self):
        base = demo()
        args = (base["request"], base["evidence"], base["claims"])
        strict = dossier(*args, now=base["generated_at"], max_age_seconds=60)
        loose = dossier(*args, now=base["generated_at"], max_age_seconds=86400)
        self.assertNotEqual(strict["readiness"], loose["readiness"])
        self.assertNotEqual(strict["dossier_id"], loose["dossier_id"])
        self.assertEqual(strict["evaluation_context"]["max_age_seconds"], 60)
        self.assertEqual(strict["evidence"][0]["effective_freshness_rule"]["max_age_seconds"], 60)

    def test_dossier_and_records_are_isolated_from_caller_inputs(self):
        base = demo()
        request, evidence, claims = copy.deepcopy(
            (base["request"], base["evidence"], base["claims"])
        )
        report = dossier(request, evidence, claims, now=base["generated_at"])
        saved = copy.deepcopy(report)
        claims[0]["evidence_ids"].clear()
        request["question"] = "Mutated question"
        request["requirements"][0]["description"] = "Mutated scope"
        evidence[0]["status"] = "error"
        self.assertEqual(report, saved)
        raw = {"nested": {"value": 1}}
        record = Record(
            "synthetic",
            "synthetic://local",
            None,
            None,
            None,
            base["generated_at"],
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "synthetic:record",
            raw,
        )
        raw["nested"]["value"] = 2
        output = record.as_dict()
        output["data"]["nested"]["value"] = 3
        self.assertEqual(record.as_dict()["data"]["nested"]["value"], 1)

    def test_decisions_watch_and_private_snapshots_do_not_alias(self):
        store = MemoryStore()
        gaps, conditions = ["valuation_missing"], ["synthetic filing"]
        store.watch(
            identifier="watch",
            instrument="SYNTH:A",
            reason=None,
            now="2026-01-01T00:00:00Z",
            user_requested=True,
            source_request_ref="synthetic:q",
            conditions=conditions,
        )
        result = store.record_decision(
            identifier="d1",
            dossier_ref="synthetic:dossier",
            dossier_version=1,
            decision="defer",
            user_statement="synthetic defer",
            now="2026-01-01T00:00:00Z",
            unresolved=gaps,
        )
        gaps.clear()
        conditions.clear()
        result["unresolved_at_decision"].clear()
        snapshot = store.snapshot()
        self.assertEqual(snapshot["decisions"][0]["unresolved_at_decision"], ["valuation_missing"])
        self.assertEqual(snapshot["watchlist"]["watch"]["review_conditions"], ["synthetic filing"])
        snapshot["decisions"].clear()
        self.assertEqual(len(store.snapshot()["decisions"]), 1)
        with tempfile.TemporaryDirectory() as directory:
            private = FileStore(Path(directory), repository_root=Path.cwd(), user_enabled=True)
            private.state = store.snapshot()
            private.save(user_requested=True)
            reopened = FileStore(Path(directory), repository_root=Path.cwd(), user_enabled=True)
            returned = reopened.snapshot()
            returned["decisions"][0]["unresolved_at_decision"].clear()
            self.assertEqual(
                reopened.snapshot()["decisions"][0]["unresolved_at_decision"], ["valuation_missing"]
            )

    def test_delta_groups_assets_and_refuses_cash_or_unstructured_delivery(self):
        def position(asset, quantity):
            return {
                "underlying": asset,
                "signed_quantity": quantity,
                "delta": 1,
                "multiplier": 100,
                "deliverable": {"kind": "equity", "underlying": asset, "unit": "shares"},
                "delta_basis": "per_deliverable_unit",
            }

        result = signed_delta_exposure([position("SYNTH:A", 1), position("SYNTH:B", -1)])
        self.assertEqual([g["signed_delta"] for g in result["groups"]], [100, -100])
        self.assertIsNone(result["cross_underlying_total"])
        bad = position("SYNTH:A", 1)
        for deliverable in (
            "100 A shares + 20 USD cash",
            {"kind": "mixed", "assets": ["A", "B"]},
            {"kind": "equity", "underlying": "SYNTH:B", "unit": "shares"},
        ):
            self.fails("schema", signed_delta_exposure, [{**bad, "deliverable": deliverable}])
        self.fails("schema", signed_delta_exposure, [{**bad, "multiplier": None}])

    def test_truthy_strings_never_authorize_network_or_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            self.fails("config", Client, Path(directory), online="false")
            self.fails(
                "persistence_not_enabled",
                FileStore,
                Path(directory),
                repository_root=Path.cwd(),
                user_enabled="false",
            )
        self.fails(
            "offline",
            authorize,
            "sec",
            "https://www.sec.gov/files/company_tickers.json",
            online="false",
        )
        self.fails(
            "approval_required",
            MemoryStore().watch,
            identifier="x",
            instrument="SYNTH:A",
            reason=None,
            now="2026-01-01T00:00:00Z",
            user_requested="false",
            source_request_ref="synthetic:x",
        )

    def test_malformed_shapes_and_conflict_retain_typed_contract(self):
        class Fake:
            def __init__(self, raw):
                self.raw = raw

            def get(self, *args, **kwargs):
                return Payload(
                    json.dumps(self.raw).encode(),
                    "2026-01-01T00:00:00Z",
                    "synthetic:payload",
                    False,
                )

        for raw in ([], None, {"facts": []}, {"facts": {"us-gaap": []}}):
            result = fetch(Fake(raw), "sec_company_facts", {"cik": "1"})
            self.assertEqual(result["data_status"], "error")
            self.assertEqual(result["issues"][0]["code"], "schema")
        raw = json.loads((Path(__file__).parent / "fixtures/xbrl-synthetic.json").read_text())
        observations = next(iter(raw["facts"]["us-gaap"].values()))["units"]
        values = next(iter(observations.values()))
        values.append({**values[-1], "val": values[-1]["val"] + 1})
        result = fetch(Fake(raw), "sec_company_facts", {"cik": "1", "latest_revision": True})
        self.assertEqual(result["data_status"], "conflict")
        self.assertEqual(result["issues"][0]["code"], "conflict")

    def test_numeric_and_ohlc_failures_remain_typed(self):
        for value, scale in ((0, float("inf")), (1.7e308, 10)):
            self.fails(
                "schema",
                scaled_quote,
                value,
                provider="synthetic",
                decimal_places=0,
                currency="USD",
                scale=scale,
                unit="USD",
            )
        self.fails(
            "schema",
            validate_bars,
            [{"date": "2026-01-01", "low": None, "high": 2, "close": 1, "open": "NaN"}],
        )
        raw = json.loads((Path(__file__).parent / "fixtures/yahoo-synthetic.json").read_text())
        raw["chart"]["result"][0]["indicators"]["quote"][0]["high"][1] = 0
        self.fails("schema", yahoo_bars, raw, now="2026-01-02T16:00:00Z")
        for function in (sma, ema):
            self.fails("schema", function, [1.7e308, 1.7e308], 2)
