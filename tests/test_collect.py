import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from scripts.collect import collect


class CookieFeed(BaseHTTPRequestHandler):
    def do_GET(self):
        if "session=yes" not in self.headers.get("Cookie", ""):
            self.send_response(302)
            self.send_header("Set-Cookie", "session=yes; Path=/")
            self.send_header("Location", "/feed")
            self.end_headers()
            return
        payload = b'<rss version="2.0"><channel><item><title>Public notice</title><link>https://example.org/notice</link><pubDate>Fri, 02 Oct 2026 16:00:00 +0900</pubDate></item></channel></rss>'
        self.send_response(200)
        self.send_header("Content-Type", "application/rss+xml")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class CollectorTests(unittest.TestCase):
    def test_follows_cookie_protected_public_feed(self):
        server = HTTPServer(("127.0.0.1", 0), CookieFeed)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            sources = [{"name": "테스트 기관", "url": f"http://127.0.0.1:{server.server_port}/feed", "category": "경제"}]
            result = collect(sources, now=datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc))
            self.assertEqual(len(result["entries"]), 1)
            self.assertEqual(result["source_failures"], [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
