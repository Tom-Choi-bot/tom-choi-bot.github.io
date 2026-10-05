import json
import tempfile
import unittest
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

    def test_rejects_unsourced_glossary_entry(self):
        with self.assertRaises(ValueError):
            validate_terms([{"term": "금리", "definition": "설명", "example": "예시", "source": "기관", "url": ""}])

    def test_renders_mobile_home_sections_glossary_and_rss(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            content = root / "content"
            content.mkdir()
            (content / "2026-10-05.json").write_text(json.dumps(self.post), encoding="utf-8")
            render_site(content, root / "dist", root_url="https://tom-choi-bot.github.io")
            home = (root / "dist/index.html").read_text(encoding="utf-8")
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
