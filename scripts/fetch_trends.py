"""Retrieve dated observations from public U.S. Treasury and EIA data APIs.

A date-only observation is not a release timestamp. The default end is two
calendar days before the 06:00 KST brief, deliberately excluding the most
recent U.S. trading day when publication time cannot be established.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

TREASURY_BASE = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
EIA_BASE = "https://api.eia.gov/v2/petroleum/pri/spt/data/"
NS = {"a": "http://www.w3.org/2005/Atom", "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata", "d": "http://schemas.microsoft.com/ado/2007/08/dataservices"}


def parse_treasury(payload: bytes, start: date, end: date) -> list[dict]:
    """Extract 10-year par yields with actual observation dates from Atom XML."""
    points = {}
    for entry in ET.fromstring(payload).findall("a:entry", NS):
        day_node = entry.find("a:content/m:properties/d:NEW_DATE", NS)
        value_node = entry.find("a:content/m:properties/d:BC_10YEAR", NS)
        if day_node is None or value_node is None or not value_node.text:
            continue
        day = date.fromisoformat(day_node.text[:10])
        value = float(value_node.text)
        if start <= day <= end and math.isfinite(value) and value >= 0:
            if day in points and points[day] != value:
                raise ValueError("conflicting Treasury observation")
            points[day] = value
    return [{"date": day.isoformat(), "value": points[day]} for day in sorted(points)]


def parse_eia(payload: dict, start: date, end: date) -> list[dict]:
    """Extract Brent *spot* observations only, never mix them with futures."""
    response = payload["response"]
    if int(response["total"]) > len(response["data"]):
        raise ValueError("EIA response is paginated; observations incomplete")
    points = {}
    for row in response["data"]:
        if row.get("series") != "RBRTE" or row.get("units") != "$/BBL" or row.get("value") is None:
            continue
        day = date.fromisoformat(row["period"])
        value = float(row["value"])
        if start <= day <= end and math.isfinite(value) and value >= 0:
            if day in points and points[day] != value:
                raise ValueError("conflicting EIA observation")
            points[day] = value
    return [{"date": day.isoformat(), "value": points[day]} for day in sorted(points)]


def get(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "MarketNote/1.0 (public data research)", "Accept": "application/json, application/xml, text/xml"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def collect(start: date, end: date) -> list[dict]:
    treasury_points = []
    for year in range(start.year, end.year + 1):
        url = TREASURY_BASE + "?" + urlencode({"data": "daily_treasury_yield_curve", "field_tdr_date_value": year})
        treasury_points.extend(parse_treasury(get(url), start, end))
    treasury_points = sorted(treasury_points, key=lambda point: point["date"])
    eia_url = EIA_BASE + "?" + urlencode({"api_key": "DEMO_KEY", "frequency": "daily", "data[0]": "value", "facets[series][]": "RBRTE", "start": start.isoformat(), "end": end.isoformat(), "sort[0][column]": "period", "sort[0][direction]": "asc", "length": "100"})
    eia_points = parse_eia(json.loads(get(eia_url)), start, end)
    if len(treasury_points) < 6 or len(eia_points) < 6:
        raise ValueError("not enough source observations for trend charts")
    return [
        {"title": "미 국채 10년물 수익률", "unit": "%", "as_of": treasury_points[-1]["date"], "source": "미 재무부 Daily Treasury Par Yield Curve Rates", "url": TREASURY_BASE + "?" + urlencode({"data": "daily_treasury_yield_curve", "field_tdr_date_value": treasury_points[-1]["date"][:4]}), "points": treasury_points},
        {"title": "브렌트유 현물가격", "unit": "달러/배럴", "as_of": eia_points[-1]["date"], "source": "미 에너지정보청(EIA) Brent Spot RBRTE", "url": eia_url, "points": eia_points},
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brief-date", required=True, type=date.fromisoformat, help="KST brief date, YYYY-MM-DD")
    parser.add_argument("--end", type=date.fromisoformat, help="last allowable observation date; defaults to brief date minus two days")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    end = args.end or args.brief_date - timedelta(days=2)
    if end > args.brief_date - timedelta(days=2):
        raise ValueError("end is too recent for a conservative 06:00 KST cutoff")
    start = end - timedelta(days=31)
    result = collect(start, end)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")
    args.output.write_text(json.dumps({"brief_date": args.brief_date.isoformat(), "end_limit": end.isoformat(), "retrieved_at": retrieved_at, "trends": result}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"collected {[(r['title'], len(r['points']), r['as_of']) for r in result]} into {args.output}")


if __name__ == "__main__":
    main()
