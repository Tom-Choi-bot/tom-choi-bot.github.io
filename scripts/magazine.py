"""Magazine views, independent articles, and sourced glossary interactions."""
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def e(value):
    return html.escape(str(value), quote=True)


def term_id(term):
    return hashlib.sha256(term["term"].encode()).hexdigest()[:12]


def term_url(term):
    return f'/terms/{term_id(term)}/'


def article_url(post, item):
    slug = hashlib.sha256(item["url"].encode()).hexdigest()[:12]
    return f'/articles/{post["date"]}/{slug}/'


def link_text(value, terms, seen=None):
    """Escape source text before linking the first mention of each known term."""
    seen = seen if seen is not None else set()
    names = {name: term for term in terms for name in [term["term"], *term.get("aliases", [])]}
    if not names:
        return e(value)
    pattern = re.compile('|'.join(re.escape(name) for name in sorted(names, key=len, reverse=True)))
    result, end = [], 0
    for match in pattern.finditer(value):
        result.append(e(value[end:match.start()]))
        name, term = match.group(), names[match.group()]
        # Short Latin abbreviations must be whole words, not substrings of other words.
        boundary = bool(re.fullmatch(r'[A-Za-z0-9]+', name)) and (
            (match.start() > 0 and value[match.start()-1].isascii() and value[match.start()-1].isalnum()) or
            (match.end() < len(value) and value[match.end()].isascii() and value[match.end()].isalnum()))
        if term["term"] in seen or boundary:
            result.append(e(name))
        else:
            seen.add(term["term"])
            result.append(f'<a class="term-link" href="{term_url(term)}" data-term="{term_id(term)}" aria-label="{e(name)} 용어 설명">{e(name)}</a>')
        end = match.end()
    result.append(e(value[end:]))
    return ''.join(result)


def term_dialog(terms):
    templates = ''.join(f'''<template id="term-preview-{term_id(t)}"><p class="eyebrow">{e(t['category'])} · 쉬운 용어</p>
<h2 id="term-dialog-title">{e(t['term'])}</h2><p>{e(t['definition'])}</p>
<h3>예시로 이해하기</h3><p>{e(t['example'])}</p><a class="text-link" href="{term_url(t)}">주의점과 출처까지 자세히 읽기 →</a></template>''' for t in terms)
    return templates + '''<dialog id="term-dialog" aria-labelledby="term-dialog-title"><div class="dialog-toolbar"><button type="button" data-close-dialog aria-label="용어 설명 닫기">닫기 ×</button></div><div id="term-dialog-content"></div></dialog>'''


def valid_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return parsed.scheme in {'http', 'https'} and bool(parsed.hostname) and not parsed.username and not parsed.password


def validate_entry(entry, channel):
    """Validate independent news and policy input before any output is replaced."""
    if channel not in ('news', 'policies') or not isinstance(entry, dict):
        raise ValueError('invalid channel or entry')
    if not isinstance(entry.get('id'), str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', entry['id']):
        raise ValueError('entry.id must be a lowercase URL slug')
    for key in ('title', 'summary', 'context', 'why_it_matters', 'watch_next', 'source'):
        if not isinstance(entry.get(key), str) or len(entry[key].strip()) < (20 if key in ('summary', 'context', 'why_it_matters', 'watch_next') else 2):
            raise ValueError(f'entry.{key} needs a substantive explanation')
    if not valid_url(entry.get('url')):
        raise ValueError('entry.url requires a public source')
    try:
        checked = datetime.fromisoformat(entry['checked_at'])
        if checked.tzinfo is None or checked.astimezone(KST).date() != date.fromisoformat(entry['date']):
            raise ValueError('checked_at and date mismatch')
        if checked > datetime.now(KST):
            raise ValueError('checked_at cannot be in the future')
        if ('published_at' in entry) == ('published_on' in entry):
            raise ValueError('exactly one publication date required')
        if 'published_at' in entry:
            published = datetime.fromisoformat(entry['published_at'])
            if published.tzinfo is None or published > checked:
                raise ValueError('source published after checking')
        elif date.fromisoformat(entry['published_on']) >= checked.astimezone(KST).date():
            raise ValueError('same-day source needs a verified publication timestamp')
        if channel == 'news' and date.fromisoformat(entry['event_on']) > checked.astimezone(KST).date():
            raise ValueError('event date cannot follow checking')
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('entry dates require consistent ISO dates and timezone-aware checking') from exc
    if channel == 'news':
        if entry.get('category') not in ('국내', '국제', '사회', '산업', '과학기술'):
            raise ValueError('invalid news category')
    else:
        for key in ('region', 'topic', 'eligibility', 'benefit', 'application', 'exclusions'):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                raise ValueError(f'policy.{key} required; state unknown conditions explicitly')
        if not valid_url(entry.get('apply_url')):
            raise ValueError('policy.apply_url requires an official application page')
        if not isinstance(entry.get('documents'), list) or not entry['documents'] or any(not isinstance(d, str) or not d.strip() for d in entry['documents']):
            raise ValueError('policy.documents must explain required documents or unknown requirements')
        for key in ('opens_on', 'deadline'):
            if key not in entry:
                raise ValueError(f'policy.{key} required; null means not verified')
            if entry[key] is not None:
                try:
                    date.fromisoformat(entry[key])
                except (TypeError, ValueError) as exc:
                    raise ValueError(f'policy.{key} requires ISO date or null') from exc
        if entry['opens_on'] and entry['deadline'] and entry['opens_on'] > entry['deadline']:
            raise ValueError('policy closes before it opens')


def load_entries(content_dir, channel):
    entries, ids = [], set()
    for path in sorted((content_dir / channel).glob('*.json')):
        entry = json.loads(path.read_text(encoding='utf-8'))
        validate_entry(entry, channel)
        if path.stem != f'{entry["date"]}-{entry["id"]}':
            raise ValueError(f'entry filename mismatch: {path.name}')
        identity = (entry['date'], entry['id'])
        if identity in ids:
            raise ValueError('duplicate channel entry')
        ids.add(identity)
        entries.append(entry)
    return sorted(entries, key=lambda entry: datetime.fromisoformat(entry['checked_at']), reverse=True)


def entry_url(entry, channel):
    return f'/{channel}/{entry["date"]}/{entry["id"]}/'


def excerpt(text, limit=135):
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(' ', 1)[0] + '…'


def release(entry):
    if 'published_at' in entry:
        return datetime.fromisoformat(entry['published_at']).astimezone(KST).strftime('%Y-%m-%d %H:%M KST')
    return entry['published_on'] + ' (시각 미공개)'


def preview(title, summary, url, label, meta, terms, extra=''):
    return f'''<article class="magazine-card" {extra}><div class="card-top"><span class="tag">{e(label)}</span><span class="published">{e(meta)}</span></div>
<h3><a href="{e(url)}">{e(title)}</a></h3><p>{link_text(excerpt(summary), terms)}</p><a class="read-more" href="{e(url)}">자세히 읽기 <span aria-hidden="true">↗</span></a></article>'''


def policy_status(entry, today=None):
    today = today or datetime.now(KST).date()
    if entry['deadline'] and date.fromisoformat(entry['deadline']) < today:
        return '마감'
    if entry['opens_on'] and date.fromisoformat(entry['opens_on']) > today:
        return '접수 예정'
    if not entry['opens_on'] or not entry['deadline']:
        return '기간 확인 필요'
    return '마감일 당일 · 시각 확인' if date.fromisoformat(entry['deadline']) == today else '접수 기간 내 · 자격 확인'


def entry_preview(entry, channel, terms):
    label = entry['category'] if channel == 'news' else entry['topic']
    attrs = f'data-search="{e(entry["title"] + " " + entry["summary"])}" data-category="{e(label)}"'
    meta = '발표 ' + release(entry)
    if channel == 'policies':
        attrs += f' data-region="{e(entry["region"])}" data-opens="{e(entry["opens_on"] or "")}" data-deadline="{e(entry["deadline"] or "")}" data-policy-status="{e(policy_status(entry))}"'
        meta = entry['region'] + ' · ' + policy_status(entry)
    card = preview(entry['title'], entry['summary'], entry_url(entry, channel), label, meta, terms, attrs)
    if channel == 'policies':
        card = card.replace('<p>', f'<p class="policy-dates">신청 마감 {e(entry["deadline"] or "공고 확인 필요")} · <span data-live-policy-status>{e(policy_status(entry))}</span></p><p>', 1)
    return card


def empty(channel):
    label = '뉴스' if channel == 'news' else '정책 공고'
    return f'<div class="empty-state"><span class="empty-icon" aria-hidden="true">＋</span><h3>최근 확인된 {label}가 없습니다</h3><p>{"배경과 출처를 확인한 소식을 안내합니다." if channel == "news" else "대상 조건과 신청 기간이 확인된 공고를 안내합니다."}</p></div>'


def section_header(label, description, url):
    return f'<div class="magazine-heading"><div><h2>{e(label)}</h2><p>{e(description)}</p></div><a class="text-link" href="{url}">모두 보기 ↗</a></div>'


def freshness(label, value, url, kind):
    return f'<a class="edition-status" href="{url}"><strong>{label}</strong><span>{kind} {e(value) if value else "확인된 원고 없음"}</span><small data-fresh-date="{e(value[:10] if value else "")}">{"기록 보기 →" if value else "자료 준비 전"}</small></a>'


def home(posts, terms, news, policies):
    latest = posts[0] if posts else None
    headline = latest['headline'] if latest else '오늘을 이해하는 새로운 읽기'
    lead = latest['lead'] if latest else '뉴스의 배경, 시장의 흐름, 생활에 필요한 정책을 근거와 함께 읽습니다.'
    feature_url = f'/{latest["date"]}/' if latest else '/economy/'
    feature = f'''<section class="magazine-hero"><div class="feature-story"><div class="eyebrow">THE DAILY NOTE · 경제 브리핑</div><h1><a href="{feature_url}">{e(headline)}</a></h1><p>{link_text(excerpt(lead, 240), terms)}</p><a class="feature-link" href="{feature_url}">브리핑 전체 읽기 <span aria-hidden="true">↗</span></a></div><aside class="editor-note"><span class="issue-number">READ / UNDERSTAND / ACT</span><h2>흐름을 읽고,<br>내일을 준비합니다.</h2><p>핵심은 간결하게.<br>배경과 근거는 충분하게.</p><a href="/terms/">낯선 용어부터 알아보기 →</a></aside></section>'''
    status = '<nav class="edition-status-grid" aria-label="분야별 자료 업데이트">' + freshness('뉴스', news[0]['checked_at'][:10] if news else '', '/news/', '마지막 확인') + freshness('경제', latest['date'] if latest else '', '/economy/', '자료 기준') + freshness('청년 정책', policies[0]['checked_at'][:10] if policies else '', '/policies/', '마지막 확인') + '</nav>'
    news_cards = ''.join(entry_preview(n, 'news', terms) for n in news[:3]) or empty('news')
    policy_cards = ''.join(entry_preview(p, 'policies', terms) for p in sorted(policies, key=lambda p: (policy_status(p) == '마감', p['deadline'] or '9999'))[:3]) or empty('policies')
    markets = ''.join(preview(i['title'], i['summary'], article_url(latest, i), i.get('section', i['category']), '발표 ' + release(i), terms, 'data-market-card') for i in latest['items']) if latest else '<p>확인된 경제 브리핑이 없습니다.</p>'
    changes = ''.join(f'<li><strong>{e(c["label"])}</strong><span>{e(c["after"])}</span><p>{e(c["insight"])}</p><a href="{e(c["previous_url"])}">이전 원문</a> · <a href="{e(c["url"])}">이번 원문 ↗</a></li>' for c in (latest or {}).get('changes', []))
    changes_html = f'<aside class="magazine-changes"><h3>어제와 달라진 점</h3><ul>{changes}</ul></aside>' if changes else ''
    date_label = f'<span class="hero-date">{e(latest["date"])} {e(latest["cutoff_at"][11:16])} KST 기준</span>' if latest else '<span>확인된 브리핑 준비 전</span>'
    dates = []
    now = datetime.now(KST)
    for event in (latest or {}).get('calendar', []):
        if datetime.fromisoformat(event['at']) > now:
            dates.append(f'<li><time>{datetime.fromisoformat(event["at"]).astimezone(KST).strftime("%m.%d %H:%M KST")}</time><a href="{e(event["url"])}">{e(event["event"])}</a><p>{e(event["watch"])}</p></li>')
    for policy in policies:
        if policy['deadline'] and date.fromisoformat(policy['deadline']) >= now.date():
            dates.append(f'<li><time>{e(policy["deadline"])} 마감 · 시각은 공고 확인</time><a href="{entry_url(policy,"policies")}">{e(policy["title"])}</a></li>')
    calendar = '<section class="magazine-calendar"><h2>앞으로의 일정</h2><ul>' + (''.join(dates) or '<li>현재 확인된 예정 일정이 없습니다.</li>') + '</ul></section>'
    return f'''<div class="edition-line"><span>THE MARKET NOTE</span>{date_label}</div>{feature}{status}
<section class="magazine-section" id="news">{section_header('주요 뉴스', '사건 너머의 배경과 맥락', '/news/')}<div class="magazine-cards">{news_cards}</div></section>
<section class="magazine-section" id="markets">{section_header('경제·시장', '숫자에서 원리까지, 한국과 세계를 함께', '/economy/')}<div class="market-layout"><div class="magazine-cards">{markets}</div>{changes_html}</div></section>
<section class="magazine-section" id="policies">{section_header('청년 정책', '대상부터 신청까지, 알아두면 쓸모 있는 지원', '/policies/')}<div class="magazine-cards">{policy_cards}</div></section>{calendar}
<section class="reading-banner"><div><span class="eyebrow">KEEP READING</span><h2>오늘의 이야기를 이어 읽으세요.</h2><p>지난 브리핑과 낯선 용어의 쉬운 설명을 모았습니다.</p></div><div><a class="button" href="/history/">지난 기록</a><a class="text-link" href="/terms/">용어 사전 ↗</a></div></section>'''


def filters(entries, channel):
    category_key = 'category' if channel == 'news' else 'topic'
    categories = sorted({x[category_key] for x in entries})
    category = '<select data-filter-key="category" aria-label="분야"><option value="">모든 분야</option>' + ''.join(f'<option>{e(c)}</option>' for c in categories) + '</select>'
    region = ''
    if channel == 'policies':
        region = '<select data-filter-key="region" aria-label="지역"><option value="">모든 지역</option>' + ''.join(f'<option>{e(r)}</option>' for r in sorted({x['region'] for x in entries})) + '</select><select data-filter-key="policyStatus" aria-label="접수 상태"><option value="">모든 접수 상태</option><option>접수 예정</option><option>접수 기간 내 · 자격 확인</option><option>마감일 당일 · 시각 확인</option><option>마감</option><option>기간 확인 필요</option></select>'
    return '<div class="filter-controls" hidden><label><span>검색</span><input type="search" data-search-input placeholder="제목이나 키워드 검색"></label>' + category + region + '<p class="filter-count" aria-live="polite"></p></div>'


def listing(entries, channel, terms):
    title = '뉴스' if channel == 'news' else '청년 정책'
    description = '무슨 일이 있었고, 왜 중요한지. 출처와 배경을 함께 읽습니다.' if channel == 'news' else '지원 조건, 혜택, 신청 절차를 확인하고 공식 공고로 이어갑니다.'
    cards = ''.join(entry_preview(entry, channel, terms) for entry in entries)
    return f'<header class="page-intro"><span class="eyebrow">{"NEWS & CONTEXT" if channel == "news" else "YOUTH & OPPORTUNITY"}</span><h1>{title}</h1><p>{description}</p></header><section data-filter-scope>{filters(entries,channel) if entries else ""}<div class="magazine-cards" data-filter-list>{cards or empty(channel)}</div><p class="filter-empty" hidden>검색 조건에 맞는 글이 없습니다. 다른 조건으로 찾아보세요.</p></section>'


def entry_body(entry, channel, terms):
    seen = set()
    text = lambda v: link_text(v, terms, seen)
    blocks = [('배경과 맥락', entry['context']), ('왜 중요한가', entry['why_it_matters'])]
    if channel == 'policies':
        blocks += [('누가 신청할 수 있나요', entry['eligibility']), ('받을 수 있는 지원', entry['benefit']), ('신청 방법', entry['application']), ('중복 지원과 확인할 조건', entry['exclusions'])]
    blocks += [('다음에 확인할 것', entry['watch_next'])]
    body = f'<a class="breadcrumb" href="/{channel}/">← {"뉴스" if channel == "news" else "청년 정책"} 전체 보기</a><header class="article-intro"><span class="eyebrow">{e(entry.get("category",entry.get("topic")))}</span><h1>{e(entry["title"])}</h1><p class="article-meta">발표 {e(release(entry))} · 확인 {datetime.fromisoformat(entry["checked_at"]).astimezone(KST).strftime("%Y-%m-%d %H:%M KST")}</p><p class="article-lead">{text(entry["summary"])}</p></header>'
    if channel == 'news':
        body += f'<p class="article-meta">사건일 {e(entry["event_on"])}</p>'
    else:
        body += f'<aside class="policy-facts"><p>지역 <strong>{e(entry["region"])}</strong></p><p>신청 기간 <strong>{e(entry["opens_on"] or "공고 확인 필요")} ~ {e(entry["deadline"] or "공고 확인 필요")}</strong></p><p data-opens="{e(entry["opens_on"] or "")}" data-deadline="{e(entry["deadline"] or "")}"><span data-live-policy-status>{e(policy_status(entry))}</span></p><p>자격과 마감 시각은 공식 공고에서 최종 확인하세요.</p></aside>'
    body += '<div class="article-copy">' + ''.join(f'<section><h2>{label}</h2><p>{text(value)}</p></section>' for label, value in blocks)
    if channel == 'policies':
        body += '<section><h2>준비할 서류</h2><ul>' + ''.join(f'<li>{text(d)}</li>' for d in entry['documents']) + f'</ul><a class="button" href="{e(entry["apply_url"])}" target="_blank" rel="noopener noreferrer">공식 신청 안내 ↗</a></section>'
    body += f'<section class="article-sources"><h2>확인한 출처</h2><a href="{e(entry["url"])}" target="_blank" rel="noopener noreferrer">{e(entry["source"])} ↗</a></section></div>'
    return body


def glossary(terms):
    categories = sorted({t['category'] for t in terms})
    options = ''.join(f'<option>{e(c)}</option>' for c in categories)
    controls = f'<div class="filter-controls" hidden><label><span>용어 검색</span><input data-search-input type="search" placeholder="용어·약어·설명으로 검색"></label><select data-filter-key="category" aria-label="용어 분야"><option value="">모든 분야</option>{options}</select><p class="filter-count" aria-live="polite"></p></div>'
    cards = ''.join(f'<article class="term-card" data-category="{e(t["category"])}" data-search="{e(t["term"] + " " + " ".join(t.get("aliases",[])) + " " + t["definition"])}"><span class="term-kind">{e(t["category"])}</span><h2><a href="{term_url(t)}">{e(t["term"])}</a></h2><p>{e(t["definition"])}</p><a class="text-link" href="{term_url(t)}">예시와 주의점 읽기 →</a></article>' for t in terms)
    return f'<header class="page-intro"><span class="eyebrow">WORDS MADE SIMPLE</span><h1>용어 사전</h1><p>어려운 말은 쉽게, 숫자의 의미는 정확하게.<br>본문의 밑줄 친 용어를 누르면 짧은 설명을 바로 볼 수 있습니다.</p></header><section data-filter-scope>{controls}<div class="terms-grid" data-filter-list>{cards}</div><p class="filter-empty" hidden>찾는 용어가 없습니다. 다른 표현으로 검색해 보세요.</p></section>'


def term_body(term, terms, references):
    related = [t for t in terms if t['category'] == term['category'] and t != term]
    links = ''.join(f'<li><a href="{url}">{e(title)}</a></li>' for title, url in references[:8])
    return f'''<a class="breadcrumb" href="/terms/">← 용어 사전</a><header class="article-intro"><span class="eyebrow">{e(term['category'])}</span><h1>{e(term['term'])}</h1><p class="article-lead">{e(term['definition'])}</p></header><div class="article-copy"><section><h2>예시로 이해하기</h2><p>{e(term['example'])}</p></section><section><h2>헷갈리기 쉬운 점</h2><p>{e(term['caution'])}</p></section><section><h2>관련 용어</h2><div class="related-terms">{''.join(f'<a href="{term_url(t)}">{e(t["term"])}</a>' for t in related) or '<p>같은 분야의 다른 용어는 아직 없습니다.</p>'}</div></section><section><h2>이 용어가 쓰인 글</h2><ul class="related-reading">{links or '<li>관련 글이 아직 없습니다.</li>'}</ul></section><section class="article-sources"><h2>설명의 출처</h2><a href="{e(term['url'])}" target="_blank" rel="noopener noreferrer">{e(term['source'])} ↗</a></section></div>'''


def pages(posts, terms, news, policies, render_item):
    """Return page bodies; the site builder owns document wrappers and assets."""
    latest_policies = list({entry['id']: entry for entry in reversed(policies)}.values())
    latest_policies.sort(key=lambda entry: datetime.fromisoformat(entry['checked_at']), reverse=True)
    result = [('', '오늘의 시장노트', home(posts,terms,news,latest_policies)), ('news','뉴스',listing(news,'news',terms)), ('policies','청년 정책',listing(latest_policies,'policies',terms)), ('terms','용어 사전',glossary(terms))]
    references = {term_id(t): [] for t in terms}
    all_articles = []
    for post in posts:
        for item in post['items']:
            url = article_url(post,item)
            plain = {k: v for k,v in item.items() if k != '_detail_url'}
            body = f'<a class="breadcrumb" href="/{post["date"]}/">← {post["date"]} 브리핑</a><header class="article-intro"><span class="eyebrow">{e(item.get("section",item["category"]))}</span><h1>{e(item["title"])}</h1><p class="article-meta">{post["date"]} 브리핑 · 자료 기준 {e(post["cutoff_at"][11:16])} KST · 발표 {e(release(item))}</p></header><div class="article-copy article-market">{render_item(plain)}</div>'
            related = [other for other in post['items'] if other['url'] != item['url']]
            body += '<aside class="related-stories"><h2>같이 읽을 이야기</h2><ul>' + ''.join(f'<li><a href="{article_url(post,other)}">{e(other["title"])}</a></li>' for other in related[:3]) + '</ul></aside>'
            result.append((url.strip('/'),item['title'],body))
            all_articles.append((item,url,post))
    market_cards = ''.join(preview(i['title'],i['summary'],url,i.get('section',i['category']),p['date']+' 브리핑',terms) for i,url,p in all_articles)
    result.append(('economy','경제·시장','<header class="page-intro"><span class="eyebrow">ECONOMY & MARKETS</span><h1>경제·시장</h1><p>숫자의 변화부터 작동 원리까지. 관심 있는 이슈를 골라 깊게 읽으세요.</p><nav class="term-jump"><a href="/stocks/">주식</a><a href="/housing/">부동산</a><a href="/money-flow/">돈의 흐름</a></nav></header><div class="magazine-cards">'+(market_cards or '<p>확인된 브리핑이 없습니다.</p>')+'</div>'))
    history = [(p['date'], f'<li><time>{p["date"]}</time><a href="/{p["date"]}/">{e(p["headline"])}</a><span>경제 · {len(p["items"])}개 이슈</span></li>') for p in posts]
    for channel, entries in [('news',news),('policies',policies)]:
        for entry in entries:
            url = entry_url(entry,channel)
            result.append((url.strip('/'),entry['title'],entry_body(entry,channel,terms)))
            all_articles.append((entry,url,None))
            history.append((entry['date'], f'<li><time>{e(entry["date"])}</time><a href="{url}">{e(entry["title"])}</a><span>{"뉴스" if channel == "news" else "청년 정책"}</span></li>'))
    history_html = ''.join(body for _, body in sorted(history, key=lambda item: item[0], reverse=True))
    result.append(('history','지난 기록','<header class="page-intro"><span class="eyebrow">THE READING ROOM</span><h1>지난 기록</h1><p>날짜가 지나도 맥락은 남습니다. 이전 글을 이어 읽어보세요.</p></header><ul class="history-list">'+(history_html or '<li>아직 발행 기록이 없습니다.</li>')+'</ul>'))
    for item,url,_ in all_articles:
        text = ' '.join(v for v in item.values() if isinstance(v,str))
        for term in terms:
            if any(name in text for name in [term['term'],*term.get('aliases',[])]):
                references[term_id(term)].append((item['title'],url))
    for term in terms:
        result.append((term_url(term).strip('/'),term['term'],term_body(term,terms,references[term_id(term)])))
    return result
