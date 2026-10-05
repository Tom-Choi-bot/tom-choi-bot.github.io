import unittest
from scripts.watchdog import check_home


class WatchdogTests(unittest.TestCase):
    def test_accepts_fresh_six_am_brief(self):
        html = '<span class="hero-date">2026-10-06 06:00 KST 기준</span>'
        self.assertEqual(check_home(html, "2026-10-06"), "")

    def test_alerts_if_site_still_shows_yesterday(self):
        html = '<span class="hero-date">2026-10-05 06:00 KST 기준</span>'
        self.assertIn("2026-10-06", check_home(html, "2026-10-06"))

    def test_archive_date_does_not_count_as_fresh_brief(self):
        html = '<a href="/2026-10-06/">archive</a><span class="hero-date">2026-10-05 06:00 KST 기준</span>'
        self.assertIn("미발행", check_home(html, "2026-10-06"))
