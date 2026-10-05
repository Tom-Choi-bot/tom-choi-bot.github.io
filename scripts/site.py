"""Build a sourced, mobile-first static Korean market briefing."""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from xml.sax.saxutils import escape as xml_escape

SITE_TITLE = "시장노트"
CATEGORIES = {"경제": "economy", "주식": "stocks", "부동산": "housing"}
SECTIONS = {"미국 시장": "us-market", "한국 시장": "kr-market", "글로벌 변수": "global", "부동산": "housing"}
NAV = [("오늘", "/"), ("경제", "/economy/"), ("주식", "/stocks/"),
       ("부동산", "/housing/"), ("돈의 흐름", "/money-flow/"), ("경제 용어", "/terms/")]


def e(value: object) -> str:
    return html.escape(str(value), quote=True)


def valid_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return parsed.scheme in {"https", "http"} and bool(parsed.hostname) and not parsed.username


def validate_post(post: dict) -> None:
    """Reject unsourced, malformed or duplicate public claims before deployment."""
    if not isinstance(post, dict):
        raise ValueError("post must be an object")
    try:
        date.fromisoformat(post["date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("post.date must be ISO YYYY-MM-DD") from exc
    try:
        cutoff = datetime.fromisoformat(post["cutoff_at"])
        if cutoff.tzinfo is None or cutoff.date().isoformat() != post["date"]:
            raise ValueError("cutoff/date mismatch")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("cutoff_at needs timezone and the post date") from exc
    if "updated_at" in post:
        try:
            updated = datetime.fromisoformat(post["updated_at"])
            if updated.tzinfo is None or updated <= cutoff or updated.astimezone(cutoff.tzinfo).date() != cutoff.date():
                raise ValueError("updated_at must follow cutoff on the post date")
        except (TypeError, ValueError) as exc:
            raise ValueError("updated_at needs timezone and must follow cutoff on post date") from exc
    for key, minimum in (("headline", 5), ("lead", 30)):
        if not isinstance(post.get(key), str) or len(post[key].strip()) < minimum:
            raise ValueError(f"post.{key} too short")
    items = post.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("at least one sourced item required")
    if len(items) > 12:
        raise ValueError("too many items for one brief")
    seen = set()
    for item in items:
        if not isinstance(item, dict) or item.get("category") not in CATEGORIES:
            raise ValueError("invalid item category")
        for key in ("title", "summary", "context", "why_it_matters", "watch_next", "source"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError(f"item.{key} required")
        for key in ("summary", "context", "why_it_matters", "watch_next"):
            if len(item[key].strip()) < 20:
                raise ValueError(f"item.{key} too short")
        if ("published_at" in item) == ("published_on" in item):
            raise ValueError("exactly one of published_at or published_on required")
        if "published_at" in item:
            try:
                parsed = datetime.fromisoformat(item["published_at"])
                if parsed.tzinfo is None or parsed > cutoff:
                    raise ValueError("missing timezone or published after cutoff")
            except (TypeError, ValueError) as exc:
                raise ValueError("item.published_at needs timezone and must precede cutoff") from exc
        else:
            try:
                if date.fromisoformat(item["published_on"]) >= cutoff.date():
                    raise ValueError("date-only release could be after cutoff")
            except (TypeError, ValueError) as exc:
                raise ValueError("item.published_on must precede cutoff date") from exc
        url = item.get("url")
        if not valid_url(url):
            raise ValueError("item.url must be a public http(s) URL")
        normalized = url.rstrip("/").lower()
        if normalized in seen:
            raise ValueError("duplicate item URL")
        seen.add(normalized)
    flows = post.get("money_flow", [])
    if not isinstance(flows, list):
        raise ValueError("money_flow must be a list")
    for flow in flows:
        if not isinstance(flow, dict):
            raise ValueError("invalid money_flow entry")
        for key in ("label", "text", "source", "as_of"):
            if not isinstance(flow.get(key), str) or not flow[key].strip():
                raise ValueError(f"money_flow.{key} required")
        if not valid_url(flow.get("url")):
            raise ValueError("money_flow.url required")
        try:
            if date.fromisoformat(flow["as_of"]) > cutoff.date():
                raise ValueError("money_flow date after cutoff")
        except ValueError as exc:
            raise ValueError("money_flow.as_of needs ISO date") from exc
    if post.get("brief_type") == "sectioned":
        if len(items) < 4 or not {"미국 시장", "한국 시장", "글로벌 변수"}.issubset({i.get("section") for i in items}):
            raise ValueError("sectioned brief needs four items across US, Korea and global sections")
        if any(i.get("section") not in SECTIONS for i in items):
            raise ValueError("invalid item section")
    elif post.get("brief_type") is not None:
        raise ValueError("invalid brief_type")
    calendar = post.get("calendar", [])
    if not isinstance(calendar, list):
        raise ValueError("calendar must be a list")
    for event in calendar:
        if not isinstance(event, dict):
            raise ValueError("invalid calendar event")
        for key in ("at", "event", "watch", "source"):
            if not isinstance(event.get(key), str) or not event[key].strip():
                raise ValueError(f"calendar.{key} required")
        if len(event["watch"].strip()) < 20 or not valid_url(event.get("url")):
            raise ValueError("calendar needs sourced context and URL")
        try:
            when = datetime.fromisoformat(event["at"])
            if when.tzinfo is None or when <= cutoff:
                raise ValueError("calendar event must follow cutoff with timezone")
        except (TypeError, ValueError) as exc:
            raise ValueError("calendar.at must follow cutoff with timezone") from exc


def validate_terms(terms: list[dict]) -> None:
    """Require a substantive explanation and a direct source for each term."""
    if not isinstance(terms, list) or not terms:
        raise ValueError("glossary must have entries")
    seen = set()
    for term in terms:
        if not isinstance(term, dict):
            raise ValueError("invalid glossary entry")
        for key in ("category", "term", "definition", "example", "caution", "source"):
            if not isinstance(term.get(key), str) or not term[key].strip():
                raise ValueError(f"glossary.{key} required")
        if len(term["definition"].strip()) < 20 or len(term["example"].strip()) < 20:
            raise ValueError("glossary explanation too short")
        if not valid_url(term.get("url")):
            raise ValueError("glossary source URL required")
        if term["term"] in seen:
            raise ValueError("duplicate glossary term")
        seen.add(term["term"])


def head(title: str, description: str, canonical: str) -> str:
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f7f6f2"><meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(canonical)}"><link rel="alternate" type="application/rss+xml" title="시장노트 RSS" href="/feed.xml">
<link rel="stylesheet" href="/assets/style.css"><title>{e(title)} · 시장노트</title></head><body>
<a class="skip" href="#main">본문으로 건너뛰기</a>
<header class="site-header"><div class="wrap header-inner"><a class="brand" href="/" aria-label="시장노트 첫 화면"><span class="brand-mark">◉</span> 시장노트</a><span class="header-caption">숫자와 출처로 읽는 오늘</span></div>
<nav class="nav wrap" aria-label="주요 메뉴">{''.join(f'<a href="{path}">{e(name)}</a>' for name, path in NAV)}</nav></header>'''


def foot() -> str:
    return '''<footer class="site-footer"><div class="wrap"><strong>시장노트</strong><p>공개된 자료의 요약과 해설입니다. 투자 권유가 아닙니다. 발표 시점과 집계 기준은 다를 수 있습니다.</p><p><a href="/method/">출처·작성 방법</a> · <a href="/feed.xml">RSS 구독</a></p></div></footer></body></html>'''


def stamp(timestamp: str) -> str:
    kst = datetime.fromisoformat(timestamp).astimezone(timezone(timedelta(hours=9)))
    return e(kst.strftime("%Y-%m-%d %H:%M KST"))


def item_card(item: dict) -> str:
    published = stamp(item["published_at"]) if "published_at" in item else e(item["published_on"] + " (시각 미공개)")
    return f'''<article class="news-card"><div class="card-top"><span class="tag">{e(item['category'])}</span><span class="published">발표 {published}</span></div>
<h3>{e(item['title'])}</h3><p class="summary">{e(item['summary'])}</p>
<div class="analysis-block"><div class="analysis-label">배경과 숫자</div><p>{e(item['context'])}</p></div>
<div class="analysis-block"><div class="analysis-label">읽는 법</div><p>{e(item['why_it_matters'])}</p></div>
<div class="next-check"><strong>다음에 확인할 것</strong><p>{e(item['watch_next'])}</p></div>
<a class="source" href="{e(item['url'])}" target="_blank" rel="noopener noreferrer">원문 · {e(item['source'])} <span aria-hidden="true">↗</span></a></article>'''


def flow_card(flow: dict) -> str:
    return f'''<article class="flow-card"><div class="flow-label">{e(flow['label'])}</div><p>{e(flow['text'])}</p><div class="flow-meta">자료 기준 {e(flow['as_of'])} · <a href="{e(flow['url'])}" target="_blank" rel="noopener noreferrer">{e(flow['source'])} ↗</a></div></article>'''


def brief_body(post: dict, *, home: bool = False) -> str:
    published = e(post["date"])
    cutoff = e(post["cutoff_at"][11:16])
    items = "".join(item_card(item) for item in post["items"])
    flows = post.get("money_flow", [])
    flow_html = "".join(flow_card(flow) for flow in flows) if flows else '<p class="empty-flow">오늘 확인 가능한 자금 흐름 자료가 없습니다. 오래된 수치를 오늘 수치처럼 게시하지 않습니다.</p>'
    label = "오늘의 브리핑" if home else "일일 브리핑"
    if post.get("brief_type") == "sectioned":
        revision = f'<span class="hero-revision">{stamp(post["updated_at"])} 보강 · 06:00 이전 자료로 재편집</span>' if "updated_at" in post else ""
        highlights = []
        for section in ("미국 시장", "한국 시장", "글로벌 변수"):
            item = next(i for i in post["items"] if i["section"] == section)
            highlights.append(f'<li><span>{e(section)}</span><a href="#{SECTIONS[section]}">{e(item["title"])}</a></li>')
        nav = ''.join(f'<a href="#{slug}">{e(section)}</a>' for section, slug in SECTIONS.items() if any(i["section"] == section for i in post["items"]))
        nav += '<a href="#money-flow">돈의 흐름</a>'
        if post.get("calendar"):
            nav += '<a href="#calendar">이번 주 일정</a>'
        sections = []
        for section, slug in SECTIONS.items():
            group = [item for item in post["items"] if item["section"] == section]
            if group:
                sections.append(f'<section class="brief-section" id="{slug}"><div class="section-heading"><h2>{e(section)}</h2><span>{len(group)}건의 확인된 소식</span></div><div class="news-list">{"".join(item_card(i) for i in group)}</div></section>')
        events = ''.join(f'<li><time datetime="{e(ev["at"])}">{stamp(ev["at"])}</time><div><strong>{e(ev["event"])}</strong><p>{e(ev["watch"])}</p><a href="{e(ev["url"])}" target="_blank" rel="noopener noreferrer">일정 원문 · {e(ev["source"])} ↗</a></div></li>' for ev in post.get("calendar", []))
        calendar_html = f'<section class="calendar-panel" id="calendar"><h2>이번 주 일정</h2><ol>{events}</ol></section>' if events else ''
        return f'''<main id="main" class="wrap"><section class="hero"><div class="eyebrow"><span class="live-dot"></span> {label} <span class="hero-date">{published} {cutoff} KST 기준</span></div>
<h1>{e(post['headline'])}</h1><p class="hero-description">{e(post['lead'])}</p>{revision}<a class="terms-prompt" href="/terms/">기사 속 용어가 낯설다면 · 경제 용어 보기 →</a></section>
<section class="at-a-glance" aria-label="오늘 한눈에 보기"><div class="eyebrow">THE BRIEF</div><h2>오늘 한눈에 보기</h2><ol>{''.join(highlights)}</ol></section>
<nav class="brief-jump" aria-label="브리핑 섹션">{nav}</nav>
<div class="content-grid"><div class="main-column">{''.join(sections)}</div>
<aside class="side-column" aria-label="돈의 흐름"><div class="flow-panel" id="money-flow"><div class="panel-label">FOCUS / MONEY FLOW</div><h2>돈의 흐름</h2><p class="panel-intro">통계의 대상 기간과 자금 유입액을 구분합니다.</p>{flow_html}</div></aside></div>
{calendar_html}<div class="bottom-note">06:00 KST 이후 발표된 자료는 이 글에 소급해 넣지 않습니다. 발표 시각과 실제 집계 기간은 다를 수 있습니다.</div></main>'''
    return f'''<main id="main" class="wrap"><section class="hero"><div class="eyebrow"><span class="live-dot"></span> {label} <span class="hero-date">{published} {cutoff} KST 기준</span></div>
<h1>{e(post['headline'])}</h1><p class="hero-description">{e(post['lead'])}</p><a class="terms-prompt" href="/terms/">기사 속 용어가 낯설다면 · 경제 용어 보기 →</a></section>
<div class="content-grid"><div class="main-column"><div class="section-heading"><h2>오늘의 소식</h2><span>{len(post['items'])}건의 확인된 소식</span></div><div class="news-list">{items}</div></div>
<aside class="side-column" aria-label="돈의 흐름"><div class="flow-panel"><div class="panel-label">FOCUS / MONEY FLOW</div><h2>돈의 흐름</h2><p class="panel-intro">가격·비용·지원제도의 신호를 구분합니다. 실제 자금 유입액과 혼동하지 않습니다.</p>{flow_html}</div></aside></div>
<div class="bottom-note">숫자에는 집계 시점이 있습니다. 기사의 발표 시각과 자료 기준일을 구분해 읽어주세요.</div></main>'''


def simple_page(title: str, body: str, root_url: str, slug: str) -> str:
    return head(title, title, f"{root_url}/{slug}/") + f'<main id="main" class="wrap simple-page">{body}</main>' + foot()


def write_page(out: Path, slug: str, content: str) -> None:
    path = out / slug / "index.html" if slug else out / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def terms_body(terms: list[dict]) -> str:
    groups = list(dict.fromkeys(term["category"] for term in terms))
    jumps = ''.join(f'<a href="#terms-{index}">{e(group)}</a>' for index, group in enumerate(groups))
    sections = []
    for index, group in enumerate(groups):
        cards = ''.join(f'''<article class="term-card"><div class="term-kind">{e(group)}</div><h3>{e(t['term'])}</h3>
<p class="term-definition">{e(t['definition'])}</p><div class="term-detail"><strong>이번 브리핑에서는</strong><p>{e(t['example'])}</p></div>
<div class="term-detail caution"><strong>헷갈리기 쉬운 점</strong><p>{e(t['caution'])}</p></div>
<a class="source" href="{e(t['url'])}" target="_blank" rel="noopener noreferrer">출처 · {e(t['source'])} ↗</a></article>''' for t in terms if t["category"] == group)
        sections.append(f'<section class="term-section" id="terms-{index}"><h2>{e(group)}</h2><div class="terms-grid">{cards}</div></section>')
    return f'<div class="eyebrow">ECONOMIC GLOSSARY</div><h1>경제 용어</h1><p>기사에 나온 숫자를 제대로 읽기 위한 짧은 설명입니다. 각 용어마다 실제 브리핑 예시와 원자료를 연결했습니다.</p><nav class="term-jump" aria-label="용어 분류">{jumps}</nav>' + ''.join(sections)


def render_site(content_dir: Path, output_dir: Path, *, root_url: str) -> None:
    """Render verified JSON posts to a dependency-free Pages artifact."""
    posts = []
    for path in sorted(content_dir.glob("*.json"), reverse=True):
        post = json.loads(path.read_text(encoding="utf-8"))
        validate_post(post)
        if path.stem != post["date"]:
            raise ValueError(f"filename/date mismatch: {path.name}")
        posts.append(post)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    css = Path(__file__).resolve().parents[1] / "assets/style.css"
    (output_dir / "assets").mkdir()
    shutil.copy2(css, output_dir / "assets/style.css")
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")
    terms = json.loads((Path(__file__).resolve().parents[1] / "data/terms.json").read_text(encoding="utf-8"))
    validate_terms(terms)
    if posts:
        latest = posts[0]
        write_page(output_dir, "", head(latest["headline"], "경제·주식·부동산과 돈의 흐름을 출처와 함께 읽는 매일 브리핑", root_url + "/") + brief_body(latest, home=True) + foot())
        for post in posts:
            write_page(output_dir, post["date"], head(post["headline"], post["headline"], f"{root_url}/{post['date']}/") + brief_body(post) + foot())
    else:
        write_page(output_dir, "", head("첫 브리핑 준비 중", "시장노트가 첫 브리핑을 준비하고 있습니다", root_url + "/") + '<main id="main" class="wrap simple-page"><div class="eyebrow">MARKET NOTE</div><h1>숫자를 읽고,<br>흐름을 잇습니다.</h1><p>첫 번째 근거 있는 브리핑을 준비하고 있습니다. 출처와 자료 기준일을 함께 공개합니다.</p><a class="button" href="/method/">작성 방법 보기 ↗</a></main>' + foot())
    write_page(output_dir, "terms", simple_page("경제 용어", terms_body(terms), root_url, "terms"))
    for name, slug in CATEGORIES.items():
        matched = [(p, item) for p in posts for item in p["items"] if item["category"] == name]
        cards = ''.join(f'<div class="category-date"><a href="/{e(p["date"])}/">{e(p["date"])} 브리핑 →</a></div>{item_card(item)}' for p, item in matched)
        body = f'<div class="eyebrow">CATEGORY</div><h1>{e(name)}</h1><div class="news-list">{cards or "<p>아직 확인된 소식이 없습니다.</p>"}</div>'
        write_page(output_dir, slug, simple_page(name, body, root_url, slug))
    matched_flows = [(p, flow) for p in posts for flow in p.get("money_flow", [])]
    flows = ''.join(f'<div class="category-date"><a href="/{e(p["date"])}/">{e(p["date"])} 브리핑 →</a></div>{flow_card(flow)}' for p, flow in matched_flows)
    write_page(output_dir, "money-flow", simple_page("돈의 흐름", f'<div class="eyebrow">MONEY FLOW</div><h1>돈의 흐름</h1><p>발표 주기가 다른 지표를 억지로 같은 날의 흐름으로 엮지 않습니다.</p><div class="flow-list">{flows or "<p>검증된 자료가 올라오면 이곳에 게시합니다.</p>"}</div>', root_url, "money-flow"))
    method = '''<div class="eyebrow">METHOD</div><h1>출처와 작성 방법</h1><div class="method-copy"><h2>자료를 고르는 법</h2><p>공시·기관 발표·공개 자료를 우선합니다. 모든 소식에 원문 링크와 발표 시각을 표시하고, 자금 흐름 자료에는 별도로 집계 기준일을 표시합니다.</p><h2>요약과 해석</h2><p>원문 전체를 복제하지 않고 자체 문장으로 요약합니다. 추정이나 맥락은 확인된 사실과 분리하여 씁니다. 출처·날짜·형식 검사를 통과하지 못한 브리핑은 발행하지 않습니다.</p><h2>한계</h2><p>자료의 공표 시점과 실제 집계 대상 기간은 다를 수 있으며 이후 정정될 수 있습니다. 이 사이트는 투자 권유가 아닙니다. 자료 확인이 불가능한 날에는 내용을 만들어내지 않습니다.</p></div>'''
    write_page(output_dir, "method", simple_page("출처·작성 방법", method, root_url, "method"))
    entries = ''.join(f'<item><title>{xml_escape(p["headline"])}</title><link>{root_url}/{p["date"]}/</link><guid>{root_url}/{p["date"]}/</guid><description>{xml_escape(str(len(p["items"])) + "건의 확인된 소식과 돈의 흐름")}</description></item>' for p in posts[:30])
    (output_dir / "feed.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>시장노트</title><link>{root_url}/</link><description>출처와 함께 읽는 매일 시장 브리핑</description>{entries}</channel></rss>', encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--content", type=Path, default=Path("content"))
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--root-url", default="https://tom-choi-bot.github.io")
    args = parser.parse_args()
    render_site(args.content, args.output, root_url=args.root_url)
    print(f"built {args.output}: {len(list(args.content.glob('*.json')))} posts")


if __name__ == "__main__":
    main()
