import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from scripts.site import render_site, validate_post, validate_terms
from scripts.collect import parse_feed


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.post = {
            "date": "2026-10-05",
            "cutoff_at": "2026-10-05T06:00:00+09:00",
            "headline": "오늘의 시장 브리핑",
            "lead": "주가와 금리, 주택 정책을 발표일과 자료 기준일로 구분해 읽습니다. 확인 가능한 원자료만 연결합니다.",
            "items": [{
                "category": "경제", "title": "확인된 발표", "summary": "공식 발표에서 확인된 숫자와 발표 시점을 구분해 자세히 설명합니다.",
                "context": "이 자료는 과거 월간 통계입니다. 발표일을 오늘의 실시간 시장가격으로 오해해서는 안 됩니다.",
                "why_it_matters": "같은 수치라도 기준일이 다르면 해석과 비교 대상이 달라집니다.",
                "watch_next": "다음 달 공표될 수치를 확인하고 이번 발표와 비교합니다.", "source": "발표 기관",
                "url": "https://example.org/release/1", "published_at": "2026-10-02T16:00:00+09:00",
            }],
            "money_flow": [{
                "label": "금리·환율", "text": "출처가 있는 흐름만 설명합니다.",
                "as_of": "2026-10-04", "source": "발표 기관", "url": "https://example.org/data/1",
            }],
        }

    def test_rejects_unsourced_item(self):
        self.post["items"][0]["url"] = ""
        with self.assertRaises(ValueError):
            validate_post(self.post)

    def test_rejects_duplicate_item_link(self):
        self.post["items"].append(dict(self.post["items"][0]))
        with self.assertRaises(ValueError):
            validate_post(self.post)

    def test_rejects_item_published_after_briefing_cutoff(self):
        self.post["items"][0]["published_at"] = "2026-10-05T10:00:00+09:00"
        with self.assertRaises(ValueError):
            validate_post(self.post)

    def test_rejects_unsourced_money_flow(self):
        self.post["money_flow"][0]["source"] = ""
        with self.assertRaises(ValueError):
            validate_post(self.post)

    def test_rejects_thin_editorial_content(self):
        self.post["items"][0]["context"] = "짧음"
        with self.assertRaises(ValueError):
            validate_post(self.post)

    def test_keeps_long_explanations_as_escaped_paragraphs(self):
        from scripts.site import item_card
        item = deepcopy(self.post['items'][0])
        first = '첫 번째 설명은 길어도 모두 표시합니다. ' * 30
        last = '마지막 문단도 생략하지 않습니다. <script>alert(1)</script>'
        item['context'] = first + '\n\n' + last
        rendered = item_card(item)
        self.assertIn(first.strip() + '</p><p>', rendered)
        self.assertIn('마지막 문단도 생략하지 않습니다.', rendered)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', rendered)
        self.assertNotIn('<script>', rendered)

    def test_accepts_older_date_only_release_without_invented_time(self):
        item = self.post["items"][0]
        item.pop("published_at")
        item["published_on"] = "2026-10-04"
        validate_post(self.post)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content"
            content.mkdir()
            (content / "2026-10-05.json").write_text(json.dumps(self.post), encoding="utf-8")
            render_site(content, root / "dist", root_url="https://tom-choi-bot.github.io")
            home = (root / "dist/index.html").read_text(encoding="utf-8")
            self.assertIn("발표 2026-10-04 (시각 미공개)", home)

    def add_briefing(self, post):
        from scripts.site import BRIEFING_TITLES
        post['briefing'] = [
            {'title': title, 'points': [
                {'text': '검증한 사실과 시장 해석을 구분하고 <script> 문자를 그대로 설명합니다.',
                 'references': [post['items'][0]['url']]}
                for _ in range(3 if title == '시장 해석' else 1)]}
            for title in BRIEFING_TITLES]
        return post

    def test_briefing_is_rendered_before_details_with_sources_and_escaped_text(self):
        from scripts.site import brief_body, BRIEFING_TITLES
        post = self.add_briefing(self.sectioned_post())
        validate_post(post)
        rendered = brief_body(post)
        self.assertLess(rendered.index('id="five-minute-brief"'), rendered.index('id="us-market"'))
        positions = [rendered.index(f'{i}. {title}</h3>') for i, title in enumerate(BRIEFING_TITLES, 1)]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('&lt;script&gt;', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertIn('href="https://example.org/usa"', rendered)

    def test_briefing_rejects_unknown_or_unsafe_references_and_wrong_counts(self):
        baseline = self.add_briefing(self.sectioned_post())
        for url in ('https://example.org/unverified', 'javascript:alert(1)'):
            post = deepcopy(baseline)
            post['briefing'][0]['points'][0]['references'] = [url]
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_post(post)
        for block, count in ((0, 6), (5, 2)):
            post = deepcopy(baseline)
            post['briefing'][block]['points'] = [deepcopy(post['briefing'][block]['points'][0]) for _ in range(count)]
            with self.subTest(block=block), self.assertRaises(ValueError):
                validate_post(post)

    def test_briefing_additional_sources_cannot_bypass_cutoff_or_url_checks(self):
        post = self.add_briefing(self.sectioned_post())
        source = {'source': '추가 원문', 'url': 'https://example.org/extra',
                  'published_at': '2026-10-05T05:30:00+09:00'}
        post['briefing_sources'] = [source]
        post['briefing'][0]['points'][0]['references'] = [source['url']]
        validate_post(post)
        source['published_at'] = '2026-10-05T06:01:00+09:00'
        with self.assertRaises(ValueError):
            validate_post(post)
        source['published_at'] = '2026-10-05T05:30:00+09:00'
        source['url'] = 'javascript:alert(1)'
        with self.assertRaises(ValueError):
            validate_post(post)

    def test_rejects_date_only_release_on_cutoff_day(self):
        item = self.post["items"][0]
        item.pop("published_at")
        item["published_on"] = "2026-10-05"
        with self.assertRaises(ValueError):
            validate_post(self.post)

    def test_converts_release_timestamp_to_korea_time(self):
        self.post["items"][0]["published_at"] = "2026-10-04T18:00:00+00:00"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content"
            content.mkdir()
            (content / "2026-10-05.json").write_text(json.dumps(self.post), encoding="utf-8")
            render_site(content, root / "dist", root_url="https://tom-choi-bot.github.io")
            home = (root / "dist/index.html").read_text(encoding="utf-8")
            self.assertIn("발표 2026-10-05 03:00 KST", home)

    def test_rejects_unsourced_glossary_entry(self):
        with self.assertRaises(ValueError):
            validate_terms([{"term": "금리", "definition": "설명", "example": "예시", "source": "기관", "url": ""}])

    def sectioned_post(self):
        post = deepcopy(self.post)
        post["brief_type"] = "sectioned"
        post["items"] = []
        for section, category, suffix in [
            ("미국 시장", "경제", "usa"), ("미국 시장", "주식", "stocks"),
            ("한국 시장", "주식", "korea"), ("글로벌 변수", "경제", "global"),
            ("부동산", "부동산", "housing"),
        ]:
            item = deepcopy(self.post["items"][0])
            item.update(section=section, category=category, title=f"{section} 분석 {suffix}", url=f"https://example.org/{suffix}",
                        mechanism="통계의 대상 기간과 실제 가격 결정 경로를 구분해야 합니다. 하나의 지표가 가격을 직접 결정하지는 않습니다.")
            post["items"].append(item)
        post["calendar"] = [{
            "at": "2026-10-08T03:00:00+09:00", "event": "9월 FOMC 의사록 공개",
            "watch": "연준의 금리 판단 근거를 원문에서 확인합니다.",
            "source": "연준 발표 일정", "url": "https://example.org/calendar",
        }]
        return post

    def test_sectioned_brief_renders_editorial_sections_and_sourced_schedule(self):
        post = self.sectioned_post()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content"
            content.mkdir()
            (content / "2026-10-05.json").write_text(json.dumps(post), encoding="utf-8")
            render_site(content, root / "dist", root_url="https://tom-choi-bot.github.io")
            home = (root / "dist/2026-10-05/index.html").read_text(encoding="utf-8")
            for label, slug in [("미국 시장", "us-market"), ("한국 시장", "kr-market"), ("글로벌 변수", "global"), ("부동산", "housing")]:
                self.assertIn(f'id="{slug}"', home)
                self.assertIn(f'<h2>{label}</h2>', home)
            self.assertIn('href="#us-market"', home)
            self.assertIn("오늘 한눈에 보기", home)
            self.assertIn("이번 주 일정", home)
            self.assertIn("2026-10-08 03:00 KST", home)
            self.assertIn('https://example.org/calendar', home)
            self.assertIn('href="/terms/"', home)
            self.assertIn("확인된 정보", home)
            self.assertIn("작동 원리", home)
            self.assertIn("인사이트·한계", home)
            self.assertIn("통계의 대상 기간과 실제 가격 결정 경로", home)

    def test_sectioned_brief_requires_substantive_mechanism(self):
        post = self.sectioned_post()
        post["items"][0].pop("mechanism")
        with self.assertRaises(ValueError):
            validate_post(post)
        post["items"][0]["mechanism"] = "원리"
        with self.assertRaises(ValueError):
            validate_post(post)

    def test_sourced_visual_comparison_renders_glanceable_bars_and_fallback(self):
        post = self.sectioned_post()
        post["visuals"] = [{
            "title": "수출액 비교", "unit": "억 달러", "as_of": "2026-09-30",
            "caption": "9월 통계. 반도체는 전체 수출에 포함됩니다. 오늘 시세가 아닙니다.",
            "source": "산업통상부", "url": "https://example.org/export",
            "points": [{"label": "전체 수출", "value": 1209.4}, {"label": "반도체", "value": 603}],
        }]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content"
            content.mkdir()
            (content / "2026-10-05.json").write_text(json.dumps(post), encoding="utf-8")
            render_site(content, root / "dist", root_url="https://tom-choi-bot.github.io")
            home = (root / "dist/2026-10-05/index.html").read_text(encoding="utf-8")
            self.assertIn('class="visual-dashboard"', home)
            self.assertIn('<summary>오늘의 시장 맥락 읽기</summary>', home)
            self.assertNotIn('class="hero-description"', home)
            self.assertIn("1,209.4", home)
            self.assertIn("603", home)
            self.assertIn('style="width:49.9%"', home)
            self.assertIn("자료 기준 2026-09-30", home)
            self.assertIn('href="https://example.org/export"', home)
            self.assertIn("오늘 시세가 아닙니다", home)
            self.assertIn('aria-label="전체 수출 1,209.4억 달러"', home)
            self.assertIn("돈의 흐름", home)
            self.assertIn("작동 원리", home)
            self.assertIn('class="visual-dashboard"', (root / "dist/2026-10-05/index.html").read_text(encoding="utf-8"))
            post.pop("visuals")
            (content / "2026-10-05.json").write_text(json.dumps(post), encoding="utf-8")
            render_site(content, root / "fallback", root_url="https://tom-choi-bot.github.io")
            self.assertIn("오늘 한눈에 보기", (root / "fallback/2026-10-05/index.html").read_text(encoding="utf-8"))

    def test_renders_dated_trend_with_readable_data_table(self):
        post = self.sectioned_post()
        post["trends"] = [{
            "title": "미 국채 10년물 추이", "unit": "%", "as_of": "2026-09-08",
            "retrieved_at": "2026-10-05T08:30:00+09:00",
            "caption": "영업일의 수익률 관측치. 오늘 시세가 아닙니다.",
            "insight": "이 기간에는 4.8%에서 5.3%로 올랐지만 원인은 단정할 수 없습니다.",
            "source": "미 재무부", "url": "https://home.treasury.gov/example",
            "points": [{"date": f"2026-09-{d:02d}", "value": v} for d, v in
                       [(1, 4.8), (2, 4.9), (3, 5.0), (4, 5.1), (7, 5.2), (8, 5.3)]],
        }]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content"
            content.mkdir()
            (content / "2026-10-05.json").write_text(json.dumps(post), encoding="utf-8")
            render_site(content, root / "dist", root_url="https://tom-choi-bot.github.io")
            home = (root / "dist/2026-10-05/index.html").read_text(encoding="utf-8")
            self.assertIn('class="trend-chart"', home)
            self.assertIn('<svg', home)
            self.assertIn('2026-09-08', home)
            self.assertIn('<table', home)
            self.assertIn('href="https://home.treasury.gov/example"', home)
            self.assertIn("API 조회 2026-10-05 08:30 KST", home)
            self.assertIn("원인은 단정할 수 없습니다", home)
            self.assertIn("영업일의 수익률", home)

    def test_yesterday_delta_precedes_charts_and_links_both_sources(self):
        post = self.sectioned_post()
        post["changes"] = [{
            "label": "주가 변화", "before": "10월 3일 100", "after": "10월 4일 98",
            "insight": "실제 거래일과 비교 범위를 지킨 하락입니다.",
            "previous_url": "https://example.org/old", "url": "https://example.org/new",
        }]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content"
            content.mkdir()
            (content / "2026-10-05.json").write_text(json.dumps(post), encoding="utf-8")
            render_site(content, root / "dist", root_url="https://tom-choi-bot.github.io")
            home = (root / "dist/2026-10-05/index.html").read_text(encoding="utf-8")
            self.assertIn("어제와 달라진 점", home)
            self.assertLess(home.index("어제와 달라진 점"), home.index("오늘 한눈에 보기"))
            self.assertIn('href="https://example.org/old"', home)
            self.assertIn('href="https://example.org/new"', home)

    def test_delta_requires_sourced_comparable_or_explicitly_distinct_interpretation(self):
        post = self.sectioned_post()
        post["changes"] = [{"label": "변화", "before": "어제", "after": "오늘",
                            "insight": "관측 기간을 분명히 밝히고 섣불리 원인을 단정하지 않습니다.",
                            "previous_url": "https://example.org/old", "url": "https://example.org/new"}]
        validate_post(post)
        for key, bad in (("previous_url", ""), ("insight", "짧음"), ("after", "")):
            broken = deepcopy(post)
            broken["changes"][0][key] = bad
            with self.subTest(field=key), self.assertRaises(ValueError):
                validate_post(broken)

    def test_unchanged_prior_series_is_not_republished_as_a_new_chart(self):
        post = self.sectioned_post()
        post["date"] = "2026-10-06"
        post["cutoff_at"] = "2026-10-06T06:00:00+09:00"
        trend = {"title": "현물 추이", "unit": "달러", "caption": "과거 값입니다.",
                 "insight": "이것만으로 원인을 확정할 수는 없습니다.", "as_of": "2026-10-04",
                 "retrieved_at": "2026-10-06T08:00:00+09:00", "source": "공식 API",
                 "url": "https://example.org/raw", "points": [{"date": f"2026-10-{d:02d}", "value": d + 100}
                                                      for d in range(1, 5)] + [{"date": "2026-09-29", "value": 99}, {"date": "2026-09-30", "value": 100}]}
        trend["points"] = sorted(trend["points"], key=lambda x: x["date"])
        earlier = deepcopy(post)
        earlier["date"] = "2026-10-05"
        earlier["cutoff_at"] = "2026-10-05T06:00:00+09:00"
        earlier["trends"] = [deepcopy(trend)]
        earlier["trends"][0]["retrieved_at"] = "2026-10-05T08:00:00+09:00"
        post["trends"] = [trend]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content"
            content.mkdir()
            (content / "2026-10-05.json").write_text(json.dumps(earlier), encoding="utf-8")
            (content / "2026-10-06.json").write_text(json.dumps(post), encoding="utf-8")
            render_site(content, root / "dist", root_url="https://tom-choi-bot.github.io")
            home = (root / "dist/2026-10-06/index.html").read_text(encoding="utf-8")
            self.assertNotIn('class="trend-chart"', home)
            self.assertIn("전일 이후 새 관측치가 없어 같은 추이 그래프를 반복하지 않았습니다", home)
            self.assertIn('href="/2026-10-05/"', home)

    def test_trend_rejects_future_unsorted_and_nonfinite_observations(self):
        post = self.sectioned_post()
        post["trends"] = [{"title": "금리", "unit": "%", "caption": "과거 수치입니다.",
                           "insight": "같은 기간 비교입니다.", "as_of": "2026-09-08",
                           "retrieved_at": "2026-10-05T08:30:00+09:00",
                           "source": "공식 자료", "url": "https://example.org/api",
                           "points": [{"date": f"2026-09-{d:02d}", "value": 4.5 + n / 10}
                                      for n, d in enumerate([1, 2, 3, 4, 7, 8])] }]
        validate_post(post)
        for bad in (float("nan"), -1, True):
            broken = deepcopy(post)
            broken["trends"][0]["points"][0]["value"] = bad
            with self.subTest(value=bad), self.assertRaises(ValueError):
                validate_post(broken)
        for bad in ("2026-10-06", "2026-09-02"):
            broken = deepcopy(post)
            broken["trends"][0]["points"][-1]["date"] = bad
            with self.subTest(date=bad), self.assertRaises(ValueError):
                validate_post(broken)

    def test_visuals_reject_unsourced_future_and_invalid_numbers(self):
        post = self.sectioned_post()
        visual = {"title": "비교", "unit": "%", "caption": "과거 관측치입니다.",
                  "as_of": "2026-10-04", "source": "공식 발표", "url": "https://example.org/chart",
                  "points": [{"label": "첫째", "value": 5.2}, {"label": "둘째", "value": 4.8}]}
        post["visuals"] = [visual]
        validate_post(post)
        for bad in (float("nan"), -1, 0, True):
            broken = deepcopy(post)
            broken["visuals"][0]["points"][0]["value"] = bad
            with self.subTest(value=bad), self.assertRaises(ValueError):
                validate_post(broken)
        for key, value in (("url", ""), ("as_of", "2026-10-06"), ("source", "")):
            broken = deepcopy(post)
            broken["visuals"][0][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                validate_post(broken)

    def test_sectioned_brief_rejects_missing_market_region(self):
        post = self.sectioned_post()
        post["items"] = [i for i in post["items"] if i["section"] != "글로벌 변수"]
        with self.assertRaises(ValueError):
            validate_post(post)

    def test_calendar_rejects_missing_source_and_past_time(self):
        post = self.sectioned_post()
        post["calendar"][0]["url"] = ""
        with self.assertRaises(ValueError):
            validate_post(post)
        post["calendar"][0]["url"] = "https://example.org/calendar"
        post["calendar"][0]["at"] = "2026-10-04T03:00:00+09:00"
        with self.assertRaises(ValueError):
            validate_post(post)

    def test_revision_timestamp_is_displayed_without_changing_source_cutoff(self):
        post = self.sectioned_post()
        post["updated_at"] = "2026-10-05T08:30:00+09:00"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content"
            content.mkdir()
            (content / "2026-10-05.json").write_text(json.dumps(post), encoding="utf-8")
            render_site(content, root / "dist", root_url="https://tom-choi-bot.github.io")
            home = (root / "dist/2026-10-05/index.html").read_text(encoding="utf-8")
            self.assertIn("06:00 KST 기준", home)
            self.assertIn("08:30 KST 보강", home)
        post["updated_at"] = "2026-10-05T05:00:00+09:00"
        with self.assertRaises(ValueError):
            validate_post(post)

    def test_renders_versioned_stylesheet_to_avoid_stale_css(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content"
            content.mkdir()
            (content / "2026-10-05.json").write_text(json.dumps(self.post), encoding="utf-8")
            render_site(content, root / "dist", root_url="https://tom-choi-bot.github.io")
            home = (root / "dist/index.html").read_text(encoding="utf-8")
            self.assertRegex(home, r'href="/assets/style\.css\?v=[0-9a-f]{12}"')

    def test_renders_mobile_home_sections_glossary_and_rss(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content"
            content.mkdir()
            (content / "2026-10-05.json").write_text(json.dumps(self.post), encoding="utf-8")
            render_site(content, root / "dist", root_url="https://tom-choi-bot.github.io")
            home = (root / "dist/2026-10-05/index.html").read_text(encoding="utf-8")
            self.assertIn('name="viewport"', home)
            self.assertIn("돈의 흐름", home)
            self.assertIn("확인된 발표", home)
            self.assertIn("2026-10-04", home)
            self.assertIn("06:00 KST 기준", home)
            self.assertIn("다음 달 공표될 수치", home)
            self.assertIn("/terms/", home)
            self.assertNotIn("/archive/", home)
            self.assertTrue((root / "dist/2026-10-05/index.html").exists())
            self.assertTrue((root / "dist/terms/index.html").exists())
            self.assertFalse((root / "dist/archive/index.html").exists())
            glossary = (root / "dist/terms/index.html").read_text(encoding="utf-8")
            self.assertIn("주가지수", glossary)
            self.assertIn("한국은행", glossary)
            self.assertTrue((root / "dist/feed.xml").exists())

    def test_escapes_untrusted_headline(self):
        self.post["items"][0]["title"] = "<script>alert(1)</script>"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content"
            content.mkdir()
            (content / "2026-10-05.json").write_text(json.dumps(self.post), encoding="utf-8")
            render_site(content, root / "dist", root_url="https://tom-choi-bot.github.io")
            home = (root / "dist/index.html").read_text(encoding="utf-8")
            self.assertNotIn("<script>", home)
            self.assertIn("&lt;script&gt;", home)

    def test_parses_rss_and_ignores_entries_without_links(self):
        xml = b'''<rss version="2.0"><channel><title>Official</title>
          <item><title>Release</title><link>https://example.org/1</link><pubDate>Mon, 05 Oct 2026 01:00:00 GMT</pubDate><description>Details</description></item>
          <item><title>No link</title><description>skip</description></item>
          </channel></rss>'''
        entries = parse_feed(xml, source="기관", category="경제")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["url"], "https://example.org/1")
        self.assertEqual(entries[0]["source"], "기관")


if __name__ == "__main__":
    unittest.main()
