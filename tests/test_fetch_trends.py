import unittest
from datetime import date

from scripts.fetch_trends import parse_eia, parse_treasury


class TrendCollectorTests(unittest.TestCase):
    def test_treasury_xml_preserves_observation_dates_and_excludes_newer_rows(self):
        xml = b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata" xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"><entry><content><m:properties><d:NEW_DATE>2026-10-01T00:00:00</d:NEW_DATE><d:BC_10YEAR>5.24</d:BC_10YEAR></m:properties></content></entry><entry><content><m:properties><d:NEW_DATE>2026-10-02T00:00:00</d:NEW_DATE><d:BC_10YEAR>5.28</d:BC_10YEAR></m:properties></content></entry><entry><content><m:properties><d:NEW_DATE>2026-10-05T00:00:00</d:NEW_DATE><d:BC_10YEAR>5.31</d:BC_10YEAR></m:properties></content></entry></feed>'''
        points = parse_treasury(xml, date(2026, 10, 1), date(2026, 10, 2))
        self.assertEqual(points, [{"date": "2026-10-01", "value": 5.24},
                                  {"date": "2026-10-02", "value": 5.28}])

    def test_eia_json_accepts_only_spot_brent_and_skips_missing_values(self):
        data = {"response": {"total": "4", "data": [
            {"period": "2026-09-01", "series": "RBRTE", "value": "96.02", "units": "$/BBL"},
            {"period": "2026-09-02", "series": "RBRTE", "value": None, "units": "$/BBL"},
            {"period": "2026-09-03", "series": "OTHER", "value": "99", "units": "$/BBL"},
            {"period": "2026-10-05", "series": "RBRTE", "value": "120", "units": "$/BBL"},
        ]}}
        self.assertEqual(parse_eia(data, date(2026, 9, 1), date(2026, 10, 2)),
                         [{"date": "2026-09-01", "value": 96.02}])


if __name__ == "__main__":
    unittest.main()