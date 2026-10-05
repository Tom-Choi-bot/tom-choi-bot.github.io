"""Collect dated, linked public feed entries as candidates (never publish raw feed text)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from scripts.site import valid_url

ATOM = "{http://www.w3.org/2005/Atom}"


class TextOnly(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(raw: str) -> str:
    parser = TextOnly()
    parser.feed(raw or "")
    return re.sub(r"\s+", " ", unescape(" ".join(parser.parts))).strip()


def date_string(raw: str) -> str | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def parse_feed(xml: bytes, *, source: str, category: str) -> list[dict]:
    root = ET.fromstring(xml)
    rss = root.findall("./channel/item")
    atom = root.findall(f"./{ATOM}entry")
    if not rss and not atom:
        raise ValueError("no RSS/Atom entries")
    entries = []
    for node in rss:
        title = plain(node.findtext("title") or "")
        url = (node.findtext("link") or "").strip()
        published = date_string(node.findtext("pubDate") or node.findtext("{http://purl.org/dc/elements/1.1/}date") or "")
        description = plain(node.findtext("description") or "")
        if title and valid_url(url) and published:
            entries.append({"title": title, "url": url, "published_at": published,
                            "source": source, "category": category, "description": description[:750]})
    for node in atom:
        title = plain(node.findtext(f"{ATOM}title") or "")
        links = node.findall(f"{ATOM}link")
        url = next((link.attrib.get("href", "") for link in links if link.attrib.get("rel", "alternate") == "alternate"), "")
        published = date_string(node.findtext(f"{ATOM}published") or node.findtext(f"{ATOM}updated") or "")
        description = plain(node.findtext(f"{ATOM}summary") or "")
        if title and valid_url(url) and published:
            entries.append({"title": title, "url": url, "published_at": published,
                            "source": source, "category": category, "description": description[:750]})
    return entries


def collect(sources: list[dict], *, now: datetime | None = None, hours: int = 48) -> dict:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    items, failures, seen = [], [], set()
    for feed in sources:
        try:
            request = Request(feed["url"], headers={"User-Agent": "MarketNote/1.0 (+https://tom-choi-bot.github.io/method/)", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
            with urlopen(request, timeout=15) as response:
                raw = response.read(2_000_000)
            entries = parse_feed(raw, source=feed["name"], category=feed["category"])
            for entry in entries:
                published = datetime.fromisoformat(entry["published_at"])
                if not cutoff <= published <= now + timedelta(minutes=10):
                    continue
                key = entry["url"].split("?")[0].rstrip("/").lower()
                if key not in seen:
                    seen.add(key)
                    items.append(entry)
        except Exception as exc:
            failures.append({"source": feed.get("name", "unknown"), "error": str(exc)[:200]})
    if len(failures) == len(sources):
        raise RuntimeError("all sources failed: " + json.dumps(failures, ensure_ascii=False))
    return {"collected_at": now.isoformat(), "window_hours": hours,
            "entries": sorted(items, key=lambda item: item["published_at"], reverse=True),
            "source_failures": failures}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, default=Path("sources.json"))
    parser.add_argument("--output", type=Path, default=Path("data/inbox.json"))
    parser.add_argument("--hours", type=int, default=48)
    args = parser.parse_args()
    sources = json.loads(args.sources.read_text(encoding="utf-8"))
    result = collect(sources, hours=args.hours)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"collected {len(result['entries'])} entries; {len(result['source_failures'])} sources failed; output {args.output}")
    for failed in result["source_failures"]:
        print(f"source failure: {failed['source']}: {failed['error']}", file=sys.stderr)


if __name__ == "__main__":
    main()
