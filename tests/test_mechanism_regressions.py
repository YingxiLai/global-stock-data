"""Own focused synthetic regressions for the two 26dcc23 mechanism findings."""

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

from jsonschema import Draft202012Validator
from test_extensions import FRAME_ARGS

from global_stock_data.cli import demo
from global_stock_data.contracts import decision_schema, validate_decision_record
from global_stock_data.errors import DataError
from global_stock_data.http import Client, Response
from global_stock_data.mcp_server import bounded_fetch, create_server
from global_stock_data.store import FileStore, MemoryStore

NOW = "2026-01-02T16:00:00Z"
FIXTURES = Path(__file__).parent / "fixtures"


class DecisionMechanismRegressions(unittest.TestCase):
    def args(self):
        return {
            "identifier": "synthetic:d1",
            "dossier_ref": "synthetic:dossier",
            "dossier_version": 1,
            "decision": "defer",
            "user_statement": "Synthetic defer",
            "now": NOW,
        }

    def record(self, confirmed=False):
        return MemoryStore().record_decision(
            **self.args(),
            confirmed=confirmed,
            confirmation_ref="synthetic:human" if confirmed else None,
        )

    def rejects(self, function, *args, **kwargs):
        with self.assertRaises(DataError):
            function(*args, **kwargs)

    def test_R2_canonical_contract_and_nullable_required_keys(self):
        schema = json.loads((Path.cwd() / "schemas/contracts-v1.json").read_text())
        self.assertEqual(decision_schema(), schema["$defs"]["DecisionRecord"])
        returned = decision_schema()
        returned["required"].clear()
        self.assertTrue(decision_schema()["required"])
        for confirmed in (False, True):
            good = self.record(confirmed)
            validate_decision_record(good)
            Draft202012Validator(decision_schema()).validate(good)
            for key in decision_schema()["required"]:
                bad = {field: value for field, value in good.items() if field != key}
                self.rejects(validate_decision_record, bad)
                self.assertTrue(list(Draft202012Validator(decision_schema()).iter_errors(bad)))
        self.assertIn("confirmation_ref", decision_schema()["required"])
        self.assertIsNone(self.record()["confirmation_ref"])

    def test_R2_creation_validates_identity_and_exact_integer_version(self):
        for version in (True, False, 1.0, 0, -1, "1", None, {}, []):
            self.rejects(
                MemoryStore().record_decision, **{**self.args(), "dossier_version": version}
            )
        for key in ("identifier", "dossier_ref", "user_statement"):
            for value in (None, True, 1, {}, [], "", "   "):
                self.rejects(MemoryStore().record_decision, **{**self.args(), key: value})
        for key in ("decision", "supersedes"):
            for value in (True, 1, [], {}, ""):
                self.rejects(MemoryStore().record_decision, **{**self.args(), key: value})
        self.assertEqual(MemoryStore().record_decision(**self.args())["dossier_version"], 1)

    def test_R2_runtime_and_schema_agree_on_known_fields_and_semantics(self):
        validator = Draft202012Validator(decision_schema())
        good = self.record(True)
        cases = [
            {**good, key: value}
            for key, values in {
                "schema_version": (None, 1, "2.0"),
                "decision_id": (True, 1, None, "", " "),
                "dossier_ref": (True, [], None, ""),
                "dossier_version": (True, "1", 0, -1),
                "actor": (None, "proposal", "bot"),
                "state": (None, "proposed", "done"),
                "decision": (None, True, "buy"),
                "user_statement": (False, [], None, ""),
                "execution_status": (None, True, "user_reported"),
                "user_approved": (1, "true", False),
                "confirmation_ref": (None, True, "", " "),
                "supersedes": (1, ""),
            }.items()
            for value in values
        ]
        for bad in cases:
            self.assertTrue(list(validator.iter_errors(bad)), bad)
            self.rejects(validate_decision_record, bad)
        reported = {**good, "decision": "user_reported_action", "execution_status": "user_reported"}
        validator.validate(reported)
        validate_decision_record(reported)

    def test_R2_invalid_snapshots_fail_save_load_without_replacing_good_file(self):
        minimal = {
            "user_approved": True,
            "state": "confirmed",
            "actor": "user",
            "confirmation_ref": "synthetic:human",
            "execution_status": "not_applicable",
        }
        missing_ref = self.record()
        del missing_ref["confirmation_ref"]
        bad_version = {**self.record(True), "dossier_version": True}
        with tempfile.TemporaryDirectory() as directory:
            private = FileStore(Path(directory), repository_root=Path.cwd(), user_enabled=True)
            good = self.record(True)
            private.state["decisions"] = [good]
            private.save(user_requested=True)
            saved = private.path.read_bytes()
            for bad in (minimal, missing_ref, bad_version):
                private.state["decisions"] = [bad]
                self.rejects(private.snapshot)
                self.rejects(private.save, user_requested=True)
                self.assertEqual(private.path.read_bytes(), saved)
                private.path.write_text(json.dumps(private.state))
                self.rejects(
                    FileStore, Path(directory), repository_root=Path.cwd(), user_enabled=True
                )
                private.path.write_bytes(saved)
            loaded = FileStore(Path(directory), repository_root=Path.cwd(), user_enabled=True)
            self.assertEqual(loaded.snapshot()["decisions"], [good])

    def test_R2_complete_proposed_and_confirmed_roundtrip_preserves_types(self):
        with tempfile.TemporaryDirectory() as directory:
            private = FileStore(Path(directory), repository_root=Path.cwd(), user_enabled=True)
            records = [private.record_decision(**self.args())]
            records.append(
                private.record_decision(
                    **{**self.args(), "identifier": "synthetic:d2", "dossier_version": 2},
                    confirmed=True,
                    confirmation_ref="synthetic:human",
                    supersedes="synthetic:d1",
                )
            )
            private.save(user_requested=True)
            loaded = FileStore(Path(directory), repository_root=Path.cwd(), user_enabled=True)
            self.assertEqual(loaded.snapshot()["decisions"], records)
            self.assertTrue(all(type(item["dossier_version"]) is int for item in records))


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Optional mcp extra absent")
class CompleteMcpResultRegressions(unittest.IsolatedAsyncioTestCase):
    def bounded(self, result):
        complete = result.model_dump(mode="json", by_alias=True)
        self.assertLessEqual(len(json.dumps(complete, allow_nan=False).encode()), 200_000)
        return complete

    async def test_R1_actual_sdk_wraps_large_acquisition_as_small_typed_error(self):
        from mcp import Client as McpClient

        raw = json.loads((FIXTURES / "frame-duration-synthetic.json").read_text())
        raw["data"][0]["padding"] = "x" * 110_000

        def sender(*args):
            return Response(200, {}, json.dumps(raw).encode())

        with tempfile.TemporaryDirectory() as directory:
            reader = Client(
                Path(directory),
                online=True,
                sec_contact="offline-test@synthetic-fixture.org",
                sender=sender,
            )
            payload = bounded_fetch(
                "sec_frames", FRAME_ARGS, limit=1, client=reader, allowed_providers=("sec",)
            )
            self.assertLess(len(json.dumps(payload).encode()), 200_000)
            self.assertGreater(len(json.dumps(payload).encode()), 100_000)
            async with McpClient(
                create_server(read_client=reader, allowed_providers=("sec",))
            ) as client:
                result = await client.call_tool(
                    "research_fetch",
                    {"capability": "sec_frames", "arguments": FRAME_ARGS, "limit": 1},
                )
                self.assertTrue(result.is_error)
                self.assertEqual(result.structured_content["error"]["code"], "output_too_large")
                self.bounded(result)
                self.assertNotIn("padding", json.dumps(result.model_dump(mode="json")))

    async def test_R1_actual_stdio_large_result_and_small_positive(self):
        from mcp import Client as McpClient
        from mcp.client.stdio import StdioServerParameters

        for mode in ([], ["large-frame"]):
            with tempfile.TemporaryDirectory() as directory:
                trace = Path(directory) / "trace.json"
                params = StdioServerParameters(
                    command=sys.executable,
                    args=[
                        str(Path(__file__).parent / "mcp_stdio_fixture.py"),
                        directory,
                        str(trace),
                        *mode,
                    ],
                    env={
                        "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
                        "OTEL_SDK_DISABLED": "true",
                    },
                )
                async with asyncio.timeout(20), McpClient(params) as client:
                    result = await client.call_tool(
                        "research_fetch",
                        {"capability": "sec_frames", "arguments": FRAME_ARGS, "limit": 1},
                    )
                    self.assertEqual(result.is_error, bool(mode))
                    self.bounded(result)
                    if mode:
                        self.assertEqual(
                            result.structured_content["error"]["code"], "output_too_large"
                        )
                    else:
                        self.assertEqual(result.structured_content["data_status"], "partial")
                calls = json.loads(trace.read_text())
                self.assertEqual(len(calls), 1)
                self.assertTrue(calls[0]["sec_agent_present"])

    async def test_R1_actual_sdk_bounds_pure_denial_and_error_results(self):
        from mcp import Client as McpClient

        with patch.object(Client, "get", side_effect=AssertionError("implicit fetch")) as reader:
            async with McpClient(create_server()) as client:
                base = demo()
                request = copy.deepcopy(base["request"])
                request["question"] = "x" * 65_000
                pure = await client.call_tool(
                    "research_dossier",
                    {
                        "request": request,
                        "evidence": base["evidence"],
                        "claims": base["claims"],
                        "now": NOW,
                    },
                )
                self.assertTrue(pure.is_error)
                self.assertEqual(pure.structured_content["error"]["code"], "output_too_large")
                self.bounded(pure)
                for name, args in (
                    ("what_if", {"weights": {"SYNTH:A": 1}, "shocks": {"SYNTH:A": 0}}),
                    ("research_fetch", {"capability": "sec_frames", "arguments": FRAME_ARGS}),
                    ("unknown_tool", {}),
                    ("what_if", {"weights": {"SYNTH:A": True}, "shocks": {"SYNTH:A": 0}}),
                ):
                    self.bounded(await client.call_tool(name, args))
            self.assertEqual(reader.call_count, 0)
