"""SEC parsing with explicit completeness and conservative period semantics."""

import re
from datetime import date, timedelta
from typing import Any, cast

from .errors import DataError, require
from .http import Client, Payload
from .records import number
from .sec_queries import frames, fulltext_search


def cik(value: str) -> str:
    require(bool(re.fullmatch(r"\d{1,10}", value)), "CIK must contain 1-10 digits", "input")
    return value.zfill(10)


def company_facts(
    raw: dict[str, Any], *, as_of: str | None = None, latest_revision: bool = False
) -> list[dict[str, Any]]:
    """Retain all original fields, units and revisions; never infer missing tags.

    as_of filters by filed DATE (not intraday availability); unsuitable for PIT
    backtests. Duration labels are conservative heuristics, not fiscal calendars.
    IFRS/foreign filings are explicitly unsupported by this normalizer.
    """
    require(isinstance(raw, dict), "Company facts must be an object")
    if as_of:
        date.fromisoformat(as_of)
    facts = raw.get("facts", {})
    require(isinstance(facts, dict), "Missing facts object")
    if "ifrs-full" in facts:
        raise DataError("unsupported", "IFRS normalization is not supported")
    output: list[dict[str, Any]] = []
    for taxonomy, tags in facts.items():
        require(isinstance(tags, dict), "Invalid taxonomy")
        for tag, item in tags.items():
            require(isinstance(item, dict) and isinstance(item.get("units"), dict), "Missing units")
            for unit, observations in item["units"].items():
                require(isinstance(observations, list), "Invalid unit series")
                for observation in observations:
                    require(isinstance(observation, dict), "Invalid fact")
                    require(
                        all(k in observation for k in ("end", "val", "accn", "filed", "form")),
                        "Incomplete XBRL observation",
                    )
                    number(observation["val"])
                    date.fromisoformat(observation["end"])
                    filed = date.fromisoformat(observation["filed"])
                    if observation["form"] not in (
                        "10-K",
                        "10-K/A",
                        "10-Q",
                        "10-Q/A",
                        "8-K",
                        "8-K/A",
                    ):
                        raise DataError(
                            "unsupported",
                            "Only domestic 10-K/10-Q/8-K fact normalization is supported",
                        )
                    if as_of and filed > date.fromisoformat(as_of):
                        continue
                    period = "instant"
                    if observation.get("start"):
                        duration = (
                            date.fromisoformat(observation["end"])
                            - date.fromisoformat(observation["start"])
                        ).days + 1
                        require(duration > 0, "Fact period ends before start")
                        period = (
                            "annual"
                            if 330 <= duration <= 400
                            else "quarter"
                            if 60 <= duration <= 120
                            else "ytd"
                            if 121 <= duration <= 329
                            else "other_duration"
                        )
                    output.append(
                        {
                            **observation,
                            "taxonomy": taxonomy,
                            "tag": tag,
                            "unit": unit,
                            "accession": observation["accn"],
                            "start": observation.get("start"),
                            "frame": observation.get("frame"),
                            "period_kind": period,
                            "period_classification": "duration_heuristic",
                            "as_of": as_of,
                            "point_in_time_safe": False,
                        }
                    )
    output.sort(key=lambda r: (r["end"], r["filed"], r["accession"], r["unit"]))
    if not latest_revision:
        return output
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in output:
        key = (row["taxonomy"], row["tag"], row["unit"], row["start"], row["end"])
        previous = grouped.get(key)
        if previous and previous["filed"] == row["filed"] and previous["val"] != row["val"]:
            raise DataError(
                "conflict", "Same-day fact revisions disagree; selection requires review"
            )
        grouped[key] = row
    return list(grouped.values())


def require_backtest_safe(_: Any) -> None:
    raise DataError(
        "point_in_time_blocked",
        "Historical availability, universe and delistings are not modeled; backtests blocked",
    )


def submissions(raw: dict[str, Any], *, historical: bool = False) -> dict[str, Any]:
    require(isinstance(raw, dict), "Submissions must be an object")
    require(historical or isinstance(raw.get("filings"), dict), "Missing filings object")
    columns = raw if historical else raw.get("filings", {}).get("recent")
    require(isinstance(columns, dict), "Missing submissions columns")
    required = ("accessionNumber", "filingDate", "form")
    require(
        all(isinstance(columns.get(k), list) for k in required), "Incomplete submissions columns"
    )
    size = len(columns["accessionNumber"])
    require(
        all(isinstance(v, list) and len(v) == size for v in columns.values()),
        "Mismatched submissions columns",
    )
    rows = [{key: value[i] for key, value in columns.items()} for i in range(size)]
    return {
        "rows": rows,
        "historical_files": [] if historical else raw.get("filings", {}).get("files", []),
        "completeness": "bounded_history_file" if historical else "recent_window_only",
        "filing_date_is_event_date": False,
        "holdings_are_realtime": False,
    }


class Sec:
    def __init__(self, client: Client) -> None:
        self.client = client

    def facts(self, identifier: str) -> Payload:
        return self.client.get(
            "sec", f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik(identifier)}.json"
        )

    def tickers(self) -> Payload:
        return self.client.get(
            "sec", "https://www.sec.gov/files/company_tickers.json", ttl=86400, max_age=86400
        )

    def frames(
        self, *, taxonomy: str, tag: str, unit: str, period: str, kind: str
    ) -> dict[str, Any]:
        return frames(self.client, taxonomy=taxonomy, tag=tag, unit=unit, period=period, kind=kind)

    def fulltext_search(
        self,
        *,
        query: str,
        date_from: str,
        date_to: str,
        page_size: int = 100,
        max_pages: int = 1,
        forms: str | None = None,
    ) -> dict[str, Any]:
        return fulltext_search(
            self.client,
            query=query,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            max_pages=max_pages,
            forms=forms,
        )

    def filings(self, identifier: str, *, max_history_files: int = 0) -> dict[str, Any]:
        require(0 <= max_history_files <= 10, "History retrieval is bounded to 10 files", "input")
        root = self.client.get("sec", f"https://data.sec.gov/submissions/CIK{cik(identifier)}.json")
        parsed = submissions(root.json())
        root_url = f"https://data.sec.gov/submissions/CIK{cik(identifier)}.json"
        parsed["rows"] = [
            {
                **row,
                "_evidence_ref": root.evidence_ref,
                "_source_url": root_url,
                "_fetched_at": root.fetched_at,
            }
            for row in parsed["rows"]
        ]
        refs = [root.evidence_ref]
        files = parsed["historical_files"]
        require(
            isinstance(files, list) and all(isinstance(f, dict) for f in files),
            "Invalid history files",
        )
        for item in files[:max_history_files]:
            name = item.get("name", "")
            require(
                bool(re.fullmatch(r"CIK" + cik(identifier) + r"-submissions-\d{3}\.json", name)),
                "Invalid history file path",
            )
            payload = self.client.get("sec", "https://data.sec.gov/submissions/" + name)
            parsed["rows"].extend(
                {
                    **row,
                    "_evidence_ref": payload.evidence_ref,
                    "_source_url": "https://data.sec.gov/submissions/" + name,
                    "_fetched_at": payload.fetched_at,
                }
                for row in submissions(payload.json(), historical=True)["rows"]
            )
            refs.append(payload.evidence_ref)
        parsed.update(
            {
                "fetched_at": root.fetched_at,
                "evidence_refs": refs,
                "remaining_history_files": max(0, len(files) - max_history_files),
                "completeness": "all_listed_files_retrieved"
                if max_history_files >= len(files)
                else "bounded_partial",
            }
        )
        # Source corrections may change repeated accessions; do not silently overwrite.
        seen: dict[str, dict[str, Any]] = {}
        for row in parsed["rows"]:
            accession = row["accessionNumber"]
            require(
                accession not in seen
                or {k: v for k, v in seen[accession].items() if not k.startswith("_")}
                == {k: v for k, v in row.items() if not k.startswith("_")},
                "Conflicting submissions accession",
                "conflict",
            )
            seen[accession] = row
        parsed["rows"] = sorted(
            seen.values(), key=lambda r: (r["filingDate"], r["accessionNumber"]), reverse=True
        )
        return parsed

    def daily_index(
        self, requested: str, *, max_fallback_days: int = 0, max_data_age_days: int = 0
    ) -> dict[str, Any]:
        day = date.fromisoformat(requested)
        require(
            0 <= max_fallback_days <= 7 and 0 <= max_data_age_days <= 7,
            "Invalid fallback freshness bound",
            "input",
        )
        for offset in range(max_fallback_days + 1):
            actual = day - timedelta(days=offset)
            require(
                offset <= max_data_age_days,
                "Candidate index exceeds requested data-age bound",
                "stale",
            )
            url = f"https://www.sec.gov/Archives/edgar/daily-index/{actual.year}/QTR{(actual.month - 1) // 3 + 1}/master.{actual:%Y%m%d}.idx"
            try:
                payload = self.client.get("sec", url, ttl=300, max_age=300)
            except DataError as exc:
                if exc.code == "missing":
                    continue
                raise
            rows = parse_index(payload.body.decode("utf-8"))
            return {
                "source_url": url,
                "requested_date": requested,
                "actual_data_date": actual.isoformat(),
                "fallback_reason": "requested_index_missing" if offset else None,
                "rows": rows,
                "fetched_at": payload.fetched_at,
                "evidence_ref": payload.evidence_ref,
                "completeness": "one_daily_index; subsequent_corrections_not_guaranteed",
                "intraday_stream": False,
            }
        raise DataError("missing", "No index found inside explicit fallback bound")


def parse_index(text: str) -> list[dict[str, str]]:
    marker = "CIK|Company Name|Form Type|Date Filed|Filename"
    require(marker in text, "Invalid SEC master index")
    rows = []
    for line in text.split(marker, 1)[1].splitlines():
        if not line.strip() or line.startswith("---"):
            continue
        fields = line.split("|")
        require(len(fields) == 5, "Malformed SEC index row")
        identifier, company, form, filed, path = fields
        date.fromisoformat(filed)
        require(
            path.startswith("edgar/data/") and ".." not in path, "Invalid archive evidence path"
        )
        rows.append(
            {
                "cik": identifier,
                "company": company,
                "form": form,
                "filing_date": filed,
                "event_date": "unknown",
                "holding_date": "unknown",
                "source_url": "https://www.sec.gov/Archives/" + path,
            }
        )
    return rows


def comparable_facts(
    left: dict[str, Any], right: dict[str, Any], *, same_period: bool = True
) -> None:
    keys = ("taxonomy", "tag", "unit", "period_kind") + (("start", "end") if same_period else ())
    require(
        all(key in left and key in right for key in keys),
        "Complete fact context required",
        "incomparable",
    )
    require(
        all(left[key] == right[key] for key in keys),
        "Fact units, periods or definitions differ",
        "incomparable",
    )
    if not same_period:
        require(
            left.get("start") is not None and right.get("start") is not None,
            "Growth requires duration facts",
            "incomparable",
        )
        a = (date.fromisoformat(left["end"]) - date.fromisoformat(left["start"])).days
        b = (date.fromisoformat(right["end"]) - date.fromisoformat(right["start"])).days
        require(abs(a - b) <= 7, "Fact durations are not comparable", "incomparable")


def growth(current: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    comparable_facts(current, prior, same_period=False)
    a, b = number(current.get("val")), number(prior.get("val"))
    require(
        a is not None and b is not None and b > 0,
        "Growth requires known values and positive prior denominator",
        "incomparable",
    )
    return {
        "value": (cast(float, a) / cast(float, b) - 1) * 100,
        "unit": "percent",
        "formula": "(current/prior-1)*100",
        "inputs": [current, prior],
        "method_version": "growth-v1",
    }
