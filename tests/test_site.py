import json
import tempfile
import unittest
from pathlib import Path

from scripts.site import render_site, validate_post
from scripts.collect import parse_feed


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.post = {
            "date": "2026-10-05",
            "headline": "오늘의 시장 브리핑",
            "items": [{
                "category": "경제", "title": "확인된 발표", "summary": "공식 발표의 핵심을 요약합니다.",
                "why_it_matters": "해석은 사실과 구분합니다.", "source": "발표 기관",
                "url": "https://example.org/release/1", "published_at": "2026-10-05T09:00:00+09:00",
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

    def test_rejects_unsourced_money_flow(self):
        self.post["money_flow"][0]["source"] = ""
        with self.assertRaises(ValueError):
            validate_post(self.post)

    def test_renders_mobile_home_sections_archive_and_rss(self):
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
            self.assertTrue((root / "dist/2026-10-05/index.html").exists())
            self.assertTrue((root / "dist/archive/index.html").exists())
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
