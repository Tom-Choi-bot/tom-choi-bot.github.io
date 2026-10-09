import json
import tempfile
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path

from scripts.intake import accept
from scripts.magazine import article_url, link_text, policy_status, term_url, validate_entry
from scripts.site import render_site, validate_terms
from scripts.watchdog import check_home


def manuscript(channel='news'):
    entry = {
        'id': 'verified-story', 'date': '2020-01-02',
        'title': '검증된 기사 제목', 'category': '국내',
        'summary': '기사의 확인된 사실과 발표 기준을 충분히 설명하는 테스트 원고입니다.',
        'context': '사건의 배경과 이전의 흐름을 근거에 연결해 충분히 설명하는 테스트 문장입니다.',
        'why_it_matters': '영향의 조건과 한계를 구분해 독자가 의미를 이해할 수 있도록 설명합니다.',
        'watch_next': '다음 공식 발표를 확인하고 현재의 사실이 어떻게 바뀌는지 비교합니다.',
        'source': '공식 발표', 'url': 'https://example.org/source',
        'published_on': '2020-01-01', 'checked_at': '2020-01-02T09:00:00+09:00',
        'event_on': '2020-01-01',
    }
    if channel == 'policies':
        entry.update(region='서울', topic='주거', eligibility='연령, 거주지, 소득 조건은 공식 공고를 확인해야 합니다.',
                     benefit='공고에서 확인한 지원 범위와 지급 조건을 설명합니다.',
                     application='공식 신청 페이지에서 조건을 확인하고 서류를 제출합니다.',
                     exclusions='중복 지원 제한은 공식 공고 확인이 필요합니다.',
                     documents=['공식 공고에 명시된 제출 서류 확인'],
                     apply_url='https://example.org/apply', opens_on='2020-01-01', deadline='2020-01-15')
    return entry


class MagazineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.content = self.root / 'content'
        self.content.mkdir()
        self.output = self.root / 'dist'
        self.post = json.loads((Path(__file__).resolve().parents[1] / 'content/2026-10-09.json').read_text())
        (self.content / '2026-10-09.json').write_text(json.dumps(self.post))

    def build(self):
        render_site(self.content, self.output, root_url='https://example.org')
        return (self.output / 'index.html').read_text()

    def test_home_previews_link_to_full_independent_articles(self):
        home = self.build()
        self.assertIn('data-magazine="true"', home)
        for label in ('주요 뉴스', '경제·시장', '청년 정책', '용어 사전'):
            self.assertIn(label, home)
        self.assertNotIn('class="analysis-block mechanism"', home)
        for item in self.post['items']:
            url = article_url(self.post, item)
            self.assertIn(f'href="{url}"', home)
            detail = (self.output / url.strip('/') / 'index.html').read_text()
            self.assertIn(item['watch_next'], detail)
            self.assertIn('작동 원리', detail)
        daily = (self.output / '2026-10-09/index.html').read_text()
        self.assertIn('class="trend-chart"', daily)
        self.assertEqual(check_home(home, '2026-10-09', daily), '')

    def test_missing_channels_are_not_misrepresented_as_current(self):
        home = self.build()
        self.assertIn('최근 확인된 뉴스가 없습니다', home)
        self.assertIn('최근 확인된 정책 공고가 없습니다', home)
        self.assertEqual(home.count('확인된 원고 없음'), 2)
        self.assertTrue((self.output / 'news/index.html').is_file())
        self.assertTrue((self.output / 'policies/index.html').is_file())

    def test_news_and_policy_input_reach_listing_detail_history_and_feed(self):
        news, policy = manuscript(), manuscript('policies')
        policy['id'] = 'housing-support'
        accept(news, 'news', self.content)
        accept(policy, 'policies', self.content)
        home = self.build()
        self.assertNotIn('최근 확인된 뉴스가 없습니다', home)
        for channel, entry in [('news', news), ('policies', policy)]:
            url = f'/{channel}/{entry["date"]}/{entry["id"]}/'
            self.assertIn(url, home)
            self.assertTrue((self.output / url.strip('/') / 'index.html').exists())
            self.assertIn(url, (self.output / 'history/index.html').read_text())
            self.assertIn(url, (self.output / 'feed.xml').read_text())
        policy_detail = (self.output / 'policies/2020-01-02/housing-support/index.html').read_text()
        for key in ('eligibility', 'benefit', 'application', 'exclusions', 'apply_url'):
            self.assertIn(policy[key], policy_detail)
        listing = (self.output / 'policies/index.html').read_text()
        self.assertIn('data-filter-key="region"', listing)
        self.assertIn('data-filter-key="policyStatus"', listing)

    def test_bad_input_preserves_previously_generated_site(self):
        self.build()
        before = (self.output / 'index.html').read_bytes()
        directory = self.content / 'news'
        directory.mkdir()
        invalid = manuscript()
        invalid['url'] = 'javascript:alert(1)'
        (directory / '2020-01-02-verified-story.json').write_text(json.dumps(invalid))
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual((self.output / 'index.html').read_bytes(), before)

    def test_intake_is_idempotent_and_requires_newer_reviewed_correction(self):
        entry = manuscript()
        path, changed = accept(entry, 'news', self.content)
        self.assertTrue(changed)
        self.assertFalse(accept(entry, 'news', self.content)[1])
        corrected = deepcopy(entry)
        corrected['title'] = '정정된 기사 제목'
        with self.assertRaises(ValueError):
            accept(corrected, 'news', self.content)
        with self.assertRaises(ValueError):
            accept(corrected, 'news', self.content, replace=True)
        self.assertEqual(json.loads(path.read_text()), entry)
        corrected['checked_at'] = '2020-01-02T10:00:00+09:00'
        self.assertTrue(accept(corrected, 'news', self.content, replace=True)[1])

    def test_missing_source_and_inconsistent_dates_are_rejected(self):
        for key, value in [('url',''),('source',''),('checked_at','2020-01-02T09:00:00'),('checked_at','2020-01-03T09:00:00+09:00'),('published_on','2020-01-02'),('event_on','2020-01-03'),('id','../../escape')]:
            entry = manuscript()
            entry[key] = value
            with self.subTest(field=key, value=value), self.assertRaises(ValueError):
                validate_entry(entry, 'news')
        entry = manuscript('policies')
        entry['apply_url'] = 'javascript:alert(1)'
        with self.assertRaises(ValueError):
            validate_entry(entry, 'policies')

    def test_policy_status_uses_dates_and_does_not_assume_eligibility(self):
        policy = manuscript('policies')
        self.assertEqual(policy_status(policy,date(2019,12,31)), '접수 예정')
        self.assertEqual(policy_status(policy,date(2020,1,2)), '접수 기간 내 · 자격 확인')
        self.assertEqual(policy_status(policy,date(2020,1,15)), '마감일 당일 · 시각 확인')
        self.assertEqual(policy_status(policy,date(2020,1,16)), '마감')
        policy['deadline'] = None
        self.assertEqual(policy_status(policy,date(2020,1,2)), '기간 확인 필요')

    def test_policy_listing_uses_latest_version_and_preserves_old_detail(self):
        first = manuscript('policies')
        accept(first, 'policies', self.content)
        second = deepcopy(first)
        second.update(date='2020-01-03',checked_at='2020-01-03T09:00:00+09:00',title='변경 사항을 확인한 새 공고')
        accept(second, 'policies', self.content)
        self.build()
        listing = (self.output / 'policies/index.html').read_text()
        self.assertIn(second['title'],listing)
        self.assertNotIn(first['title'],listing)
        self.assertTrue((self.output / 'policies/2020-01-02/verified-story/index.html').exists())
        older = (self.output / 'policies/2020-01-02/verified-story/index.html').read_text()
        self.assertIn('더 최근 확인본', older)
        self.assertIn('/policies/2020-01-03/verified-story/', older)

    def test_last_checked_date_is_shown_in_kst_even_for_utc_input(self):
        entry = manuscript()
        entry['checked_at'] = '2020-01-01T23:00:00+00:00'
        accept(entry, 'news', self.content)
        home = self.build()
        self.assertIn('마지막 확인 2020-01-02', home)
        self.assertNotIn('마지막 확인 2020-01-01', home)

    def test_glossary_links_escape_content_and_link_only_first_mention(self):
        term = {'term':'기준금리','aliases':['base rate']}
        seen = set()
        text = link_text('<script>기준금리 기준금리</script>',[term],seen)
        self.assertNotIn('<script>',text)
        self.assertIn('&lt;script&gt;',text)
        self.assertEqual(text.count('data-term='),1)
        self.assertIn(term_url(term),text)
        self.assertNotIn('data-term=',link_text('기준금리',[term],seen))
        alias = {'term':'경제심리지수','aliases':['ESI']}
        self.assertNotIn('data-term=',link_text('DESIGN',[alias]))
        self.assertIn('data-term=',link_text('ESI 지표',[alias]))

    def test_dictionary_has_stable_details_sources_and_related_articles(self):
        self.build()
        terms = json.loads((Path(__file__).resolve().parents[1] / 'data/terms.json').read_text())
        term = next(t for t in terms if t['term']=='경상수지')
        detail = (self.output / term_url(term).strip('/') / 'index.html').read_text()
        self.assertIn('가상의 예',detail)
        self.assertIn(term['url'].replace('&','&amp;'),detail)
        self.assertIn('/articles/2026-10-09/',detail)
        glossary = (self.output / 'terms/index.html').read_text()
        self.assertIn('data-search-input',glossary)
        self.assertIn('data-filter-key="category"',glossary)

    def test_duplicate_alias_cannot_link_to_ambiguous_definition(self):
        terms = json.loads((Path(__file__).resolve().parents[1] / 'data/terms.json').read_text())
        terms[0]['aliases'] = [terms[1]['term']]
        with self.assertRaises(ValueError):
            validate_terms(terms)

    def test_magazine_watchdog_requires_valid_current_detail(self):
        home = self.build()
        self.assertIn('상세 브리핑',check_home(home,'2026-10-09'))
        self.assertIn('미발행',check_home(home,'2026-10-10'))
        thin = home.replace('data-market-card','data-other-card')
        self.assertIn('미완성',check_home(thin,'2026-10-09'))
        broken_detail = '<span class="hero-date">2026-10-09 06:00 KST 기준</span>'
        self.assertIn('미완성',check_home(home,'2026-10-09',broken_detail))


if __name__ == '__main__':
    unittest.main()
