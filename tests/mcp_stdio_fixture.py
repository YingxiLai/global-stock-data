"""Test-only synthetic sender wired to the real stdio server; never a product mode."""

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from global_stock_data.http import Client, Response
from global_stock_data.mcp_server import create_server

FIXTURES = Path(__file__).parent / "fixtures"
calls = []


def sender(url, headers, timeout):
    query = parse_qs(urlsplit(url).query)
    if "/frames/" in url:
        fixture = "frame-duration-synthetic.json"
    elif "search-index" in url:
        fixture = (
            "fts-page0-synthetic.json" if query["from"] == ["0"] else "fts-page1-synthetic.json"
        )
    elif "treasury.gov" in url:
        fixture = "treasury-synthetic.xml"
    elif "companyfacts" in url:
        fixture = "xbrl-synthetic.json"
    else:
        raise AssertionError("Unexpected synthetic endpoint")
    calls.append({"url": url, "sec_agent_present": "@" in headers["User-Agent"]})
    Path(sys.argv[2]).write_text(json.dumps(calls))
    body = (FIXTURES / fixture).read_bytes()
    if "/frames/" in url and len(sys.argv) > 3 and sys.argv[3] == "large-frame":
        raw = json.loads(body)
        raw["data"][0]["padding"] = "x" * 110_000
        body = json.dumps(raw).encode()
    return Response(200, {}, body)


if __name__ == "__main__":
    # Fictional identity is used ONLY by this injected sender, under socket guard.
    client = Client(
        Path(sys.argv[1]),
        online=True,
        sec_contact="offline-test@synthetic-fixture.org",
        sender=sender,
    )
    create_server(read_client=client, allowed_providers=("sec", "treasury")).run(transport="stdio")
