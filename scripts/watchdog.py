"""Check that the public homepage shows today's 06:00 KST briefing."""
from __future__ import annotations

import re
from datetime import datetime
from html import unescape
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


def check_home(html: str, expected_date: str) -> str:
    match = re.search(r'<span\s+class="hero-date"[^>]*>([^<]+)</span>', html)
    actual = unescape(match.group(1)).strip() if match else "없음"
    expected = f"{expected_date} 06:00 KST 기준"
    if actual != expected:
        return f"시장노트 {expected_date} 06시 브리핑 미발행: 홈 화면 표시값={actual}"
    required_sections = ("us-market", "kr-market", "global")
    missing = [section for section in required_sections
               if not re.search(r'<section\s+class="brief-section"\s+id="' + section + r'"', html)]
    item_count = len(re.findall(r'<article\s+class="news-card"', html))
    if missing or item_count < 4:
        return f"시장노트 {expected_date} 섹션별 브리핑 미완성: 소식 {item_count}건, 누락 섹션 {', '.join(missing)}"
    mechanism_count = len(re.findall(r'<div\s+class="analysis-block mechanism"', html))
    if mechanism_count != item_count:
        return f"시장노트 {expected_date} 작동 원리 설명 누락: 소식 {item_count}건 중 원리 {mechanism_count}건"
    return ""


def main() -> None:
    today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    request = Request(f"https://tom-choi-bot.github.io/?watchdog={today}", headers={"User-Agent": "MarketNoteWatchdog/1.0"})
    try:
        with urlopen(request, timeout=15) as response:
            html = response.read(1_000_000).decode("utf-8", "replace")
        message = check_home(html, today)
    except Exception as exc:
        message = f"시장노트 {today} 발행 상태 확인 실패: {type(exc).__name__}: {exc}"
    if message:
        print(message)


if __name__ == "__main__":
    main()
