"""Network-free web publication regressions. Run with .venv/bin/python test_web.py."""
import contextlib
import io
import json
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import relay as r


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    @property
    def text(self):
        return ''.join(c.text if isinstance(c, Node) else c for c in self.children)

    def find(self, tag=None, cls=None):
        result = []
        if (tag is None or self.tag == tag) and (cls is None or cls in self.attrs.get('class', '').split()):
            result.append(self)
        for child in self.children:
            if isinstance(child, Node):
                result.extend(child.find(tag, cls))
        return result


class Document(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, text):
        super().__init__()
        self.root = Node()
        self.stack = [self.root]
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    def find(self, tag=None, cls=None):
        return self.root.find(tag, cls)

    def section(self, cls):
        nodes = self.find(cls=cls)
        assert len(nodes) == 1, (cls, len(nodes))
        return nodes[0]

    def links(self, rel=None):
        return [n.attrs['href'] for n in self.find('a') if 'href' in n.attrs and
                (rel is None or rel in n.attrs.get('rel', '').split())]


def price_history():
    dates = r.pd.bdate_range('2026-08-03', '2026-10-16')
    values = 100 * (1.01 ** r.np.arange(len(dates)))
    frame = r.pd.DataFrame({'Open': values * 1.002, 'Close': values}, index=dates)
    return {key: frame.copy() for key in r.TICK}


def legacy_record(day, status='done', missing=False, reused=False):
    # Deliberately poisoned stored aggregates and SVGs must never reach the web.
    return {
        'date': day, 'status': status,
        'prev': {'date': str((r.pd.Timestamp(day) - r.pd.offsets.BDay()).date()), 'kospi': .01, 'kosdaq': -.01},
        'us': {key: None if missing else [.004, .01] for key in r.US},
        'vix': 17.0, 'open': None if status == 'pending' else .0123,
        'close': -.0045 if status == 'done' else None,
        'freq': {'bin': '강한 상승', 'n': 987654, 'up': 987654, 'flat': 0, 'down': 0, 'years': 999},
        'head': {'cond': 'LEGACY_HEAD', 'claim': 'LEGACY_CLAIM', 'zone': 'up'},
        'sentence': 'LEGACY_SENTENCE', 'ny': '<svg>LEGACY_NY</svg>', 'kr': '<svg>LEGACY_KR</svg>',
        'tail': '오늘 코스피는 -0.45%로 마감했어요.' if status == 'done' else None,
        'source_states': {key: 'missing' if missing else 'reused' if reused else 'fresh' for key in r.US},
        'source_dates': {key: None if missing else '2026-09-22' for key in r.US},
        'source_note': 'LEGACY_SOURCE_NOTE', 'built_at': day + 'T16:00:00+09:00',
    }


class Clock(r.dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 19, 16, tzinfo=r.KST)


class BandTests(unittest.TestCase):
    """kospi-threshold.md: 보이는 반올림 값 기준, ±0.3% 이내(경계 포함) 거의 그대로, 시가·마감 같은 구간."""

    def test_flat_is_inclusive_on_displayed_value(self):
        self.assertEqual(r.FLAT, 0.003)
        for x in (0.0, 0.002, 0.003, -0.003, 0.00304, -0.00304):   # 0.304% shows as 0.30%
            self.assertEqual(r.zone_of(x), 'flat', x)
            self.assertEqual(r.color(x), 'var(--flat)', x)
            self.assertIsNone(r.band_of(x), x)
        self.assertEqual(r.pct(0.00306), '+0.31%')
        self.assertEqual(r.zone_of(0.00306), 'up')      # shows +0.31%
        self.assertEqual(r.zone_of(-0.0031), 'down')
        self.assertEqual(r.color(0.0031), 'var(--up)')
        self.assertEqual(r.color(-0.0031), 'var(--down)')

    def test_plus_point_two_is_gray_and_flat_worded(self):
        self.assertEqual(r.color(0.002), 'var(--flat)')
        self.assertEqual(r.web_words(0.002, '마감'), '0.20% 올라 거의 그대로 마감했어요')
        self.assertEqual(r.web_words(-0.003, '시작'), '0.30% 내려 거의 그대로 시작했어요')
        self.assertEqual(r.web_words(0.0, '마감'), '어제 마감과 같게 마감했어요')

    def test_magnitude_band_boundaries_both_signs(self):
        cases = [(0.0031, '조금'), (0.00994, '조금'), (0.009949, '조금'), (0.00996, '꽤'), (0.01, '꽤'),
                 (0.0199, '꽤'), (0.02, '많이'), (0.0499, '많이'), (0.04996, '아주 크게'), (0.05, '아주 크게'), (0.1791, '아주 크게')]
        for x, word in cases:
            for sign in (1, -1):
                with self.subTest(x=x * sign):
                    self.assertEqual(r.band_of(x * sign), word)
        for x in (0.00996, 0.04996, 0.0199, 0.00306):   # band follows the printed number
            self.assertEqual(r.pct(x)[1:5], f'{r.shown_pct(x):.2f}')
        self.assertEqual(r.web_words(0.006, '시작'), '0.60% 조금 올라서 시작했어요')
        self.assertEqual(r.web_words(-0.0397, '마감'), '3.97% 많이 내려서 마감했어요')
        self.assertEqual(r.web_words(-0.01, '시작'), '1.00% 꽤 내려서 시작했어요')
        self.assertEqual(r.web_words(0.05, '마감'), '5.00% 아주 크게 올라서 마감했어요')
        self.assertEqual(r.web_words(0.0031, '마감'), '0.31% 조금 올라서 마감했어요')


class WebTests(unittest.TestCase):
    def restyle_fixture(self):
        source = '<!doctype html><html lang="ko"><head><title>기존 기록</title><style>old</style></head><body><div class="wrap"><header class="site-header">밤사이 코스피</header><main><h1>기록</h1><p>수치는 +1.23% · 자료 대기</p><table class="comparison-table"><thead><tr><th>날짜</th><th>시가</th></tr></thead><tbody><tr><th>09/23</th><td>+1.23%</td></tr></tbody></table></main></div></body></html>'
        (self.site / 'index.html').write_text(source)
        (self.site / 'latest.json').write_text('{"date":"2026-09-23","open":0.0123}')
        (self.site / 'relay.png').write_bytes(b'published fixture image')
        (self.site / 'CNAME').write_text('kospi.ditoaxis.com\n')
        return source

    def test_restyle_preserves_published_values_files_and_is_idempotent_without_fetch(self):
        source = self.restyle_fixture()
        for name in ('favicon.svg',):
            (self.site / name).write_text('stale presentation asset')
        protected = {p.name: p.read_bytes() for p in self.site.iterdir()
                     if p.suffix != '.html' and p.name != 'favicon.svg'}
        r.restyle()
        once = (self.site / 'index.html').read_text()
        self.assertIn('수치는 +1.23% · 자료 대기', once)
        self.assertEqual(once.count('id="market-table-keys"'), 1)
        self.assertEqual(once.count('class="table-scroll"'), 1)
        r.restyle()
        self.assertEqual((self.site / 'index.html').read_text(), once)
        self.assertEqual({self.site / name: (self.site / name).read_bytes() for name in protected},
                         {self.site / name: content for name, content in protected.items()})
        for name in ('favicon.svg',):
            self.assertEqual((self.site / name).read_bytes(), (Path(r.__file__).parent / 'assets' / name).read_bytes())
        self.assertEqual([n.attrs['href'] for n in self.read().find('link') if n.attrs.get('rel') == 'icon'],
                         [r.web_url('favicon.svg')])
        self.fetch.assert_not_called()
        self.assertFalse(self.captures)

    def assert_web_analytics(self, doc):
        loaders = [n for n in doc.find('script') if 'ditoaxis.com/m.js' in n.attrs.get('src', '')]
        self.assertEqual(len(loaders), 1)
        self.assertEqual(loaders[0].attrs, {'defer': None, 'src': 'https://ditoaxis.com/m.js'})
        self.assertIn(loaders[0], doc.find('head')[0].find('script'))
        self.assertFalse(any('cloudflareinsights.com' in n.attrs.get('src', '') for n in doc.find('script')))

    def test_analytics_in_every_generated_web_head_with_or_without_ads(self):
        self.write(legacy_record('2026-09-23'))
        self.write(legacy_record('2026-10-12'))
        orphan = self.site / '2026-10-13'
        orphan.mkdir()
        (orphan / 'index.html').write_text('<div>old orphan page</div>')
        for client in ('', 'ca-pub-fixture'):
            with self.subTest(client=client), patch.object(r, 'ADSENSE', client), patch.object(r, 'ADSENSE_SLOT', '12345'):
                r.regenerate(self.hist)
                pages = list(self.site.rglob('*.html'))
                self.assertEqual(len(pages), 8)
                for page in pages:
                    source = page.read_text()
                    doc = Document(source)
                    self.assert_web_analytics(doc)
                    self.assertEqual(source.count('<script defer src="https://ditoaxis.com/m.js"></script>'), 1)
                    if client and page.parent.name != 'privacy':
                        head_scripts = doc.find('head')[0].find('script')
                        # Only the JSON-LD data block may be inline; any other inline script is a regression.
                        self.assertEqual([n.attrs.get('type') for n in head_scripts if 'src' not in n.attrs], ['application/ld+json'])
                        scripts = [n for n in head_scripts if 'src' in n.attrs]
                        self.assertEqual(len(scripts), 2)
                        self.assertIn('pagead2.googlesyndication.com', scripts[0].attrs['src'])
                        self.assertEqual(scripts[1].attrs['src'], 'https://ditoaxis.com/m.js')
        self.fetch.assert_not_called()
        self.assertEqual(len(self.captures), 2)

    def test_every_generated_page_has_one_schema_org_json_ld_in_head(self):
        self.write(legacy_record('2026-09-23'))
        self.write(legacy_record('2026-10-12'))
        orphan = self.site / '2026-10-13'
        orphan.mkdir()
        (orphan / 'index.html').write_text('<div>old orphan page</div>')
        r.regenerate(self.hist)
        home = r.web_url()
        pages = sorted(self.site.rglob('*.html'))
        self.assertEqual(len(pages), 8)
        for page in pages:
            route = page.parent.relative_to(self.site).as_posix()
            route = '' if route == '.' else route + '/'
            with self.subTest(page=route or 'home'):
                doc = Document(page.read_text(encoding='utf-8'))
                blocks = [n for n in doc.find('script') if n.attrs.get('type') == 'application/ld+json']
                self.assertEqual(len(blocks), 1)
                self.assertIn(blocks[0], doc.find('head')[0].find('script'))
                data = json.loads(blocks[0].text)
                self.assertEqual(data['@context'], 'https://schema.org')
                nodes = {node['@type']: node for node in data.get('@graph', [data])}
                metas = [n.attrs['content'] for n in doc.find('meta') if n.attrs.get('name') == 'description']
                if not route:
                    app = nodes['WebApplication']
                    self.assertEqual((app['name'], app['url'], app['description']), ('밤사이 코스피', home, metas[0]))
                    self.assertEqual((app['applicationCategory'], app['operatingSystem'], app['inLanguage'], app['isAccessibleForFree']),
                                     ('FinanceApplication', 'Web', 'ko', True))
                    self.assertEqual((app['offers']['price'], app['offers']['priceCurrency']), ('0', 'KRW'))
                    self.assertEqual(app['publisher'], {'@type': 'Organization', 'name': '디토엑시스', 'url': 'https://ditoaxis.com/'})
                    self.assertEqual(nodes['WebSite']['url'], home)
                    continue
                webpage = nodes['WebPage']
                self.assertEqual((webpage['url'], webpage['inLanguage'], webpage['isPartOf']['url']), (r.web_url(route), 'ko', home))
                self.assertEqual(webpage.get('description'), metas[0] if metas else None)
                self.assertNotIn('datePublished', webpage)
                if route.startswith('archive/') or route in ('2026-09-23/', '2026-10-12/'):
                    crumbs = nodes['BreadcrumbList']['itemListElement']
                    self.assertEqual(crumbs[0]['item'], home)
                    self.assertEqual(crumbs[-1]['item'], r.web_url(route))
                    self.assertEqual([c['position'] for c in crumbs], list(range(1, len(crumbs) + 1)))
                    if not route.startswith('archive/'):
                        self.assertTrue((self.site / crumbs[1]['item'][len(home):] / 'index.html').is_file())
                else:
                    self.assertEqual(set(nodes), {'WebPage'})
        self.fetch.assert_not_called()

    def test_privacy_explains_cookie_free_aggregate_analytics(self):
        r.regenerate(self.hist)
        doc = self.read('privacy')
        self.assert_web_analytics(doc)
        self.assertIn('https://www.cloudflare.com/web-analytics/', doc.links())
        for text in ('Cloudflare Web Analytics', '페이지 주소', '유입 경로', '브라우저·기기 종류',
                     '국가', '로딩 성능', '쿠키나 기기 식별자를 사용하지 않으며', '개인을 알아볼 수 없는 집계'):
            self.assertIn(text, doc.root.text)
        self.assertIn('https://adssettings.google.com', doc.links())
        self.assertIn('https://policies.google.com/technologies/ads', doc.links())

    def test_generated_assets_and_landscape_metadata_without_changing_legacy_card(self):
        day = '2026-10-16'
        self.publish(day, 'close')
        for route in ('', day, 'archive/2026-10', 'about', 'privacy'):
            doc = self.read(route)
            self.assertEqual([n.attrs for n in doc.find('link') if n.attrs.get('rel') == 'icon'],
                             [{'rel': 'icon', 'href': r.web_url('favicon.svg'), 'type': 'image/svg+xml'}])
        for route in ('', day, 'archive/2026-10'):
            meta = {n.attrs.get('property', n.attrs.get('name')): n.attrs.get('content') for n in self.read(route).find('meta')}
            self.assertEqual(meta['og:image'], r.web_url(day + '/og.png'))
            self.assertEqual(meta['twitter:image'], meta['og:image'])
            self.assertEqual((meta['og:image:width'], meta['og:image:height']), ('1200', '630'))
            self.assertEqual(meta['og:image:type'], 'image/png')
            self.assertEqual(meta['twitter:card'], 'summary_large_image')
        self.assertTrue((self.site / day / 'og.png').is_file())
        self.assertEqual((self.site / day / 'relay.png').read_bytes(), (self.site / 'relay.png').read_bytes())
        self.assertNotIn('class="og-card"', self.captures[0])
        self.assertIn('.sheet{width:540px;', self.captures[0])
        self.assertNotIn('.og-card .sheet{', self.captures[0])
        self.assertIn('class="og-card"', self.captures[1])
        self.assertIn('.og-card .sheet{width:600px;height:315px;', self.captures[1])
        self.assertEqual(self.capture_targets, [self.site / 'relay.png', self.site / day / 'og.png'])
        og = self.site / day / 'og.png'
        og.write_bytes(b'preserved landscape image')
        r.regenerate(self.hist)
        self.assertEqual(og.read_bytes(), b'preserved landscape image')
        self.assertEqual(len(self.captures), 2)
        for name in ('favicon.svg',):
            self.assertEqual((self.site / name).read_bytes(), (Path(r.__file__).parent / 'assets' / name).read_bytes())

    def test_restyle_rewrites_old_head_wording_without_touching_main(self):
        source = self.restyle_fixture()
        old = ('<meta name="description" content="2026-09-23 뉴욕 세 지표와 비슷한 밤의 과거 빈도, 코스피 시가와 종가를 함께 봐요">'
               '<meta property="og:description" content="2026-09-23 뉴욕 세 지표와 비슷한 밤의 과거 빈도, 코스피 시가와 종가를 함께 봐요">'
               '<meta property="og:image:alt" content="2026-09-23 코스피 기록 · 밤사이 뉴욕 지표와 코스피 시가">')
        (self.site / 'index.html').write_text(source.replace('</head>', old + '</head>'))
        r.restyle()
        once = (self.site / 'index.html').read_text()
        head = once.split('</head>')[0]
        for stale in ('뉴욕 세 지표', '뉴욕 지표', '코스피 시가'):
            self.assertNotIn(stale, head)
        self.assertEqual(head.count(r.web_description('2026-09-23')), 2)
        self.assertIn('2026-09-23 코스피 기록 · ' + r.WEB_IMAGE_ALT, head)
        self.assertNotIn('오늘', head)
        self.assertIn('수치는 +1.23% · 자료 대기', once)
        r.restyle()
        self.assertEqual((self.site / 'index.html').read_text(), once)

    def test_restyle_adds_analytics_to_all_html_once_and_preserves_ads_and_privacy(self):
        source = self.restyle_fixture()
        ad = '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-fixture" crossorigin="anonymous"></script>'
        privacy = r.PRIVACY.replace(r.WEB_ANALYTICS, '').replace(r.WEB_ANALYTICS_NOTICE, '')
        (self.site / 'privacy').mkdir()
        (self.site / 'legacy').mkdir()
        legacy = '<!doctype html><html><head><title>공유 기록</title></head><body><p>기존 공개 내용</p><script src="https://ditoaxis.com/m.js"></script></body></html>'
        for existing in ('', r.WEB_ANALYTICS,
                         r.WEB_ANALYTICS + "<script src='https://ditoaxis.com/m.js' defer></script>",
                         '<script defer src="//ditoaxis.com/m.js"></script>',
                         '<script defer src="https://ditoaxis.com/m.js?v=1"></script>'):
            with self.subTest(existing=existing):
                (self.site / 'index.html').write_text(source.replace('</head>', ad + existing + '</head>'))
                (self.site / 'privacy/index.html').write_text(privacy)
                (self.site / 'legacy/index.html').write_text(legacy)
                protected = {p: p.read_bytes() for p in self.site.rglob('*') if p.is_file() and p.suffix != '.html'}
                r.restyle()
                once = {p: p.read_text() for p in self.site.rglob('*.html')}
                for page, text in once.items():
                    self.assert_web_analytics(Document(text))
                home = once[self.site / 'index.html']
                self.assertIn(ad + r.WEB_ANALYTICS, home.replace('\n', ''))
                self.assertEqual(home.count(ad), 1)
                updated_privacy = once[self.site / 'privacy/index.html']
                self.assertEqual(updated_privacy.count(r.WEB_ANALYTICS_NOTICE), 1)
                self.assertEqual(Document(updated_privacy).find('body')[0].text,
                                 Document(privacy.replace('<h2>문의</h2>', r.WEB_ANALYTICS_NOTICE + '<h2>문의</h2>')).find('body')[0].text)
                self.assertEqual(Document(once[self.site / 'legacy/index.html']).find('body')[0].text,
                                 Document(legacy).find('body')[0].text)
                r.restyle()
                self.assertEqual({p: p.read_text() for p in once}, once)
                self.assertEqual({p: p.read_bytes() for p in protected}, protected)
        self.fetch.assert_not_called()
        self.assertFalse(self.captures)

    def test_restyle_unknown_template_fails_before_any_html_write(self):
        source = self.restyle_fixture()
        for broken in ('<html><head><title>unknown</title></head><body><header class="site-header">unknown</header><main>old</main></body></html>',
                       '<header class="site-header">unknown</header><main>old</main>'):
            with self.subTest(broken=broken):
                (self.site / 'broken.html').write_text(broken)
                with self.assertRaises(RuntimeError):
                    r.restyle()
                self.assertEqual((self.site / 'index.html').read_text(), source)
        self.fetch.assert_not_called()

    def test_restyle_warns_and_leaves_headless_html_unchanged(self):
        self.restyle_fixture()
        headless = self.site / 'fragment.html'
        source = '<div class="share">기존 조각</div><main>수치는 +1.23%</main>\r\n'.encode('utf-8')
        headless.write_bytes(source)
        for _ in range(2):
            r.restyle()
            self.assertEqual(headless.read_bytes(), source)
            self.assert_web_analytics(self.read())
        self.assertEqual(self.output.getvalue().count('::warning::Skipped headless HTML fragment.html; left unchanged'), 2)
        self.fetch.assert_not_called()
        self.assertFalse(self.captures)

    def test_restyle_headless_homepage_or_privacy_fails_before_any_html_write(self):
        home = self.restyle_fixture()
        privacy = self.site / 'privacy' / 'index.html'
        privacy.parent.mkdir()
        for required in (self.site / 'index.html', privacy):
            with self.subTest(page=required.relative_to(self.site)):
                (self.site / 'index.html').write_text(home)
                privacy.write_text(r.PRIVACY)
                required.write_text('<body>missing head</body>')
                before = {p: p.read_bytes() for p in self.site.rglob('*') if p.is_file()}
                with self.assertRaisesRegex(RuntimeError, 'Missing published head'):
                    r.restyle()
                self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.fetch.assert_not_called()
        self.assertFalse(self.captures)

    def test_restyle_missing_publication_never_bootstraps(self):
        with self.assertRaises(RuntimeError):
            r.restyle()
        self.assertEqual(list(self.site.iterdir()), [])
        self.fetch.assert_not_called()

    def test_keyboard_table_region_preserves_all_market_columns(self):
        record = legacy_record('2026-09-23')
        doc = Document(r.record_table([record], record['date'], archive=True))
        region = doc.section('table-scroll')
        self.assertEqual(region.attrs.get('role'), 'region')
        self.assertEqual(region.attrs.get('tabindex'), '0')
        self.assertTrue(region.attrs.get('aria-label'))
        table = region.find('table')[0]
        self.assertEqual(len(table.find('thead')[0].find('th')), 6)
        self.assertEqual(len(table.find('tbody')[0].find('td')), 5)
        self.assertEqual(table.find('tbody')[0].find('a')[0].attrs['href'], r.web_url('2026-09-23/'))

    def test_company_return_and_skip_link_reach_focusable_main(self):
        doc = Document(r.web_shell('검토', '', '<h1>검토</h1>'))
        self.assertIn('https://ditoaxis.com/#products', doc.links())
        self.assertIn('#main', doc.links())
        self.assertEqual(doc.find('main')[0].attrs.get('id'), 'main')
        self.assertEqual(doc.find('main')[0].attrs.get('tabindex'), '-1')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.site = Path(self.temp.name)
        self.raw = price_history()
        self.hist = r.align(self.raw)
        self.patch(r, 'SITE', self.site)
        self.patch(r.dt, 'datetime', Clock)
        self.fetch = self.patch(r, 'fetch', return_value=self.raw)
        self.patch(r, 'ADSENSE', '')
        self.patch(r, 'ADSENSE_SLOT', '')
        self.captures = []
        self.capture_targets = []

        def screenshot(source, target):
            self.captures.append(Path(source).read_text(encoding='utf-8'))
            self.capture_targets.append(Path(target))
            Path(target).write_bytes(b'fixture share image')

        self.patch(r, 'screenshot', side_effect=screenshot)
        self.output = io.StringIO()
        capture = contextlib.redirect_stdout(self.output)
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def patch(self, obj, name, *args, **kwargs):
        p = patch.object(obj, name, *args, **kwargs)
        result = p.start()
        self.addCleanup(p.stop)
        return result

    def write(self, record):
        path = self.site / 'days' / (record['date'] + '.json')
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        return path

    def read(self, route=''):
        return Document((self.site / route / 'index.html').read_text(encoding='utf-8'))

    def canonical(self, doc, route):
        self.assertEqual([n.attrs.get('href') for n in doc.find('link') if n.attrs.get('rel') == 'canonical'],
                         [r.SITE_URL.rstrip('/') + '/' + (route.strip('/') + '/' if route else '')])

    def publish(self, day, phase):
        with patch.dict(r.os.environ, {'RELAY_DATE': day}):
            r.build(phase)
        return json.loads((self.site / 'latest.json').read_text())

    def test_frequency_strict_cutoff(self):
        hist = r.pd.DataFrame({'gap': [.01, -.01, .0, -.02, -.02], 's': [.006] * 5},
                             index=r.pd.to_datetime(['2026-09-01', '2026-09-02', '2026-09-03', '2026-09-04', '2026-09-07']))
        f = r.frequency(hist, .006, r.pd.Timestamp('2026-09-04'))
        self.assertEqual((f['n'], f['up'], f['flat'], f['down']), (3, 1, 1, 1))
        self.assertEqual(r.frequency(hist, .006, r.pd.Timestamp('2026-09-01'))['n'], 0)
        self.assertEqual(r.frequency(hist, .006, r.pd.Timestamp('2026-09-02'))['n'], 1)
        self.assertEqual(r.frequency(hist, .006, r.pd.Timestamp('2026-09-08'))['n'], 5)

    def test_latest_no_us_window_is_distinct_from_pending_prices(self):
        day, prior = '2026-10-16', r.pd.Timestamp('2026-10-15')
        original = {key: frame.copy() for key, frame in self.raw.items()}
        # No peer has a US session in this window (for example, Good Friday).
        for key in (*r.US, 'VIX'):
            self.raw[key] = self.raw[key].drop(prior)
        self.assertIsNone(r.today_nodes(self.raw, r.pd.Timestamp(day))[1]['SPY'])
        published = self.publish(day, 'close')
        self.assertIsNone(published['freq'])
        self.assertEqual(published['head']['cond'], '비교할 뉴욕 자료가 없어요')
        for route in ('', day, 'archive/2026-10'):
            doc = self.read(route)
            for waiting in ('대기', '기다리', '채워지면'):
                self.assertNotIn(waiting, doc.find('body')[0].text)
            if route != 'archive/2026-10':
                self.assertIn('비교할 미국 증시 자료가 없어요', doc.section('ny-area').text)
                self.assertIn('비교할 미국 증시 자료가 없어요', doc.section('frequency-area').text)
        # An actual session with missing prices serializes identical null US values,
        # but retains a non-null frequency state instead of claiming no session.
        self.raw.update(original)
        for key in (*r.US, 'VIX'):
            self.raw[key].loc[prior, 'Close'] = r.np.nan
        self.assertIsNotNone(r.today_nodes(self.raw, r.pd.Timestamp(day))[1]['SPY'])
        pending = self.publish(day, 'close')
        self.assertEqual(pending['us'], published['us'])
        self.assertEqual(pending['freq']['bin'], '자료 대기')
        for route in ('', day):
            doc = self.read(route)
            self.assertIn('미국 증시 자료를 기다리고 있어요', doc.section('ny-area').text)
            self.assertIn('자료가 채워지면', doc.section('frequency-area').text)
            self.assertIn('자료 대기', doc.section('comparison').text)
        self.assertIn('자료 대기', self.read('archive/2026-10').section('archive-table').text)

    def test_bad_archive_files_warn_without_blocking_publication(self):
        self.write(legacy_record('2026-09-30'))
        malformed = {
            '2026-10-13.json': '{broken json',
            '2026-10-14.json': json.dumps({'open': .01, 'us': {}}),
            '2026-10-15.json': '[]',
            '2026-10-16.json': json.dumps({'date': '2026-10-16', 'us': {'SPY': [.01]}}),
        }
        for name, text in malformed.items():
            (self.site / 'days' / name).write_text(text)
        self.publish('2026-10-12', 'morning')
        for name, text in malformed.items():
            self.assertIn('::warning::Skipping web record ' + name, self.output.getvalue())
            self.assertEqual((self.site / 'days' / name).read_text(), text)
            self.assertNotIn(name[:-5], (self.site / 'sitemap.xml').read_text())
        self.assertEqual(self.read().find('time')[0].attrs['datetime'], '2026-10-12')
        self.assertTrue(any('2026-09-30' in link for link in self.read('2026-10-12').links('prev')))
        self.assertTrue((self.site / 'archive/2026-10/index.html').exists())
        self.assertTrue((self.site / 'about/index.html').exists())
        # An unreadable individual file also leaves the remaining records usable.
        read_text = Path.read_text
        def unreadable(path, *args, **kwargs):
            if path.name == '2026-10-13.json':
                raise OSError('fixture unreadable')
            return read_text(path, *args, **kwargs)
        with patch.object(Path, 'read_text', unreadable):
            r.regenerate(self.hist)
        self.assertIn('fixture unreadable', self.output.getvalue())

    def test_about_sample_period_has_complete_sentences_with_or_without_history(self):
        empty = Document(r.web_about(self.hist.iloc[:0])).find('body')[0].text
        self.assertIn('현재 가격 이력을 기다리고 있어요.', empty)
        self.assertNotIn('있어요예요', empty)
        available = Document(r.web_about(self.hist)).find('body')[0].text
        self.assertIn('이번에 확보한 유효 이력은 ', available)
        self.assertIn('까지예요.', available)
        self.assertNotIn('가격 이력을 기다리고', available)

    def test_orphan_date_pages_are_replaced_without_deleting_files(self):
        self.write(legacy_record('2026-10-12'))
        broken = self.site / 'days/2026-10-13.json'
        broken.write_text('{broken json')
        unreadable = self.write(legacy_record('2026-10-14'))
        orphans = ('2026-10-13', '2026-10-14', '2026-10-15')
        for date in (*orphans, 'not-a-date', '2026-02-30'):
            folder = self.site / date
            folder.mkdir()
            (folder / 'index.html').write_text('<div>LEGACY_FREQ 987654</div>')
            (folder / 'relay.png').write_bytes(b'preserved PNG')
        snapshots = {p: p.read_bytes() for p in self.site.rglob('*') if p.is_file() and p.suffix != '.html'}
        read_text = Path.read_text
        def deny_read(path, *args, **kwargs):
            if path == unreadable:
                raise OSError('fixture unreadable')
            return read_text(path, *args, **kwargs)
        with patch.object(Path, 'read_text', deny_read):
            r.regenerate(self.hist)
        for date in orphans:
            doc = self.read(date)
            self.canonical(doc, date)
            self.assertEqual(doc.find('h1')[0].text, '기록이 없어요')
            self.assertEqual([n.attrs['content'] for n in doc.find('meta') if n.attrs.get('name') == 'robots'], ['noindex'])
            self.assertIn(r.web_url(), doc.links())
            self.assertNotIn('LEGACY_FREQ', doc.root.text)
            self.assertNotIn('987654', doc.root.text)
            self.assertFalse(doc.find('ins', 'adsbygoogle'))
            self.assertIn(f'::warning::Replaced orphan date page {date}/index.html', self.output.getvalue())
        for path, data in snapshots.items():
            self.assertEqual(path.read_bytes(), data)
        for name in ('not-a-date', '2026-02-30'):
            self.assertIn('LEGACY_FREQ', self.read(name).root.text)
        self.assertNotIn('noindex', [n.attrs.get('content') for n in self.read('2026-10-12').find('meta')])
        # The cleanup must also run when no valid publication survives.
        with patch.object(r, 'load_web_records', return_value=[]):
            r.regenerate(self.hist)
        self.assertEqual(self.read('2026-10-12').find('h1')[0].text, '기록이 없어요')

    def test_frequency_counts_are_distinct_from_signed_results(self):
        doc = Document(r.web_frequency_graph({'n': 40, 'up': 18, 'flat': 12, 'down': 10}, True))
        self.assertEqual([n.text for n in doc.find(cls='frequency-value')],
                         ['40번 중 18번, 45%', '40번 중 12번, 30%', '40번 중 10번, 25%'])
        self.assertFalse(doc.find('strong'))
        result = Document(r.web_result(legacy_record('2026-10-12'), True))
        self.assertEqual([n.text for n in result.find('strong')], ['+1.23%', '-0.45%'])

    def test_close_only_record_keeps_close_in_tables_and_qualifies_for_ads(self):
        day = '2026-10-12'
        record = legacy_record(day)
        record['open'] = None
        with patch.object(r, 'ADSENSE', 'ca-pub-fixture'), patch.object(r, 'ADSENSE_SLOT', '12345'):
            for close in (-.0045, 0):
                record['close'] = close
                self.write(record)
                self.write({**record, 'date': '2026-10-13'})
                r.regenerate(self.hist)
                self.assertEqual(len(self.read().find('ins', 'adsbygoogle')), 1)
                self.write(legacy_record('2026-10-13', 'pending'))
                r.regenerate(self.hist)
                for route in ('', day, 'archive/2026-10'):
                    rows = [n for n in self.read(route).find('tr') if n.attrs.get('data-date') == day]
                    self.assertEqual(len(rows), 1)
                    cells = rows[0].find('td')
                    self.assertEqual(len(cells), 5)
                    self.assertEqual(cells[-2].text, '기록이 없어요')
                    self.assertEqual(cells[-1].text, r.pct(close))
                self.assertEqual(len(self.read(day).find('ins', 'adsbygoogle')), 1)
                self.assertFalse(self.read().find('ins', 'adsbygoogle'))
            for status in ('pending', 'filled'):
                stale_close = {**record, 'date': '2026-10-14', 'status': status}
                self.write(stale_close)
                r.regenerate(self.hist)
                self.assertFalse(self.read().find('ins', 'adsbygoogle'))
                rows = self.read().section('comparison').find('tr')
                self.assertNotIn('2026-10-14', [n.attrs.get('data-date') for n in rows])

    def test_date_comparison_ends_on_selected_date_and_marks_current_row(self):
        days = ['2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02',
                '2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09',
                '2026-10-12', '2026-10-16']
        pending = {'2026-10-05', '2026-10-09'}
        for day in days:
            self.write(legacy_record(day, 'pending' if day in pending else 'done'))
        r.regenerate(self.hist)
        for route in ('2026-09-28', '2026-09-30', '2026-10-08', '2026-10-09', ''):
            selected = route or days[-1]
            doc = self.read(route)
            rows = doc.section('comparison').find('tbody')[0].find('tr')
            expected = [d for d in reversed(days) if d <= selected and d not in pending][:5]
            self.assertEqual([row.attrs['data-date'] for row in rows], expected)
            current = [row for row in rows if row.attrs.get('aria-current') == 'date']
            self.assertEqual([row.attrs['data-date'] for row in current],
                             [] if selected in pending else [selected])
            self.assertTrue(all('current-row' in row.attrs.get('class', '').split() for row in current))
            year, month, day = map(int, selected.split('-'))
            self.assertEqual(doc.find('h1')[0].text, '어젯밤 미국 증시와 코스피')
            self.assertTrue(doc.find('time')[0].text.startswith(f'{year}년 {month}월 {day}일('))
            self.assertEqual(doc.find('time')[0].attrs['datetime'], selected)
            self.assertTrue(any('/archive/' + selected[:7] + '/' in a.attrs.get('href', '')
                                for a in doc.section('comparison').find('a')))

    def test_archive_shares_comparison_columns_and_korean_month_labels(self):
        record = legacy_record('2026-09-23', reused=True)
        record['us'] = {'SOXX': [0, .1123], 'QQQ': [0, -.1234], 'SPY': None}
        self.write(record)
        for day, status in [('2026-08-31', 'done'), ('2026-09-24', 'pending'),
                            ('2026-09-25', 'filled'), ('2026-10-01', 'done')]:
            self.write(legacy_record(day, status))
        r.regenerate(self.hist)
        doc = self.read('archive/2026-09')
        table = doc.section('archive-table')
        headers = [node.text for node in table.find('thead')[0].find('th')]
        self.assertEqual(headers, ['날짜', 'SOXX등락률', 'QQQ등락률', 'SPY등락률', '시가등락률', '종가등락률'])
        self.assertEqual(headers, [node.text for node in self.read().section('comparison').find('thead')[0].find('th')])
        rows = {row.attrs['data-date']: row for row in table.find('tbody')[0].find('tr')}
        self.assertEqual(list(rows), ['2026-09-25', '2026-09-24', '2026-09-23'])
        cells = rows['2026-09-23'].find('td')
        self.assertEqual([cell.text for cell in cells],
                         ['+11.23%기존 값', '-12.34%기존 값', '기록이 없어요', '+1.23%', '-0.45%'])
        self.assertIn('2026년 9월 22일', cells[0].find('span', 'source-state')[0].attrs['title'])
        no_record = rows['2026-09-24'].find('td', 'no-record')
        self.assertEqual(len(no_record), 1)
        self.assertEqual((no_record[0].text, no_record[0].attrs['colspan']), ('기록이 없어요', '2'))
        self.assertEqual([cell.text for cell in rows['2026-09-24'].find('td')[:3]], ['+1.00%'] * 3)
        self.assertEqual(rows['2026-09-25'].find('td')[-1].text, '기록이 없어요')
        self.assertEqual(doc.find('h1')[0].text, '2026년 9월 기록')
        self.assertEqual([a.text for a in doc.find('a') if a.attrs.get('rel') in ('prev', 'next')],
                         ['이전 달 8월', '다음 달 10월'])

    def test_regeneration_legacy_pending_navigation_and_contract(self):
        days = ['2026-09-21', '2026-09-22', '2026-09-23', '2026-09-24', '2026-09-25',
                '2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01', '2026-10-02',
                '2026-10-05', '2026-10-08', '2026-10-09', '2026-10-12']
        pending = {'2026-09-24', '2026-09-25', '2026-10-05', '2026-10-09', days[-1]}
        records = [legacy_record(d, 'pending' if d in pending else 'done') for d in days]
        for record in records:
            self.write(record)
            png = self.site / record['date'] / 'relay.png'
            png.parent.mkdir()
            png.write_bytes(('original PNG ' + record['date']).encode())
        latest = self.site / 'latest.json'
        latest.write_text(json.dumps(records[-1]), encoding='utf-8')
        index = self.site / 'index.json'
        index.write_text(json.dumps([{'d': d, 'z': None, 'extension': 'keep'} for d in days]))
        root_png = self.site / 'relay.png'
        root_png.write_bytes(b'original root share image')
        snapshots = {p: p.read_bytes() for p in [*self.site.glob('days/*.json'), *self.site.glob('*/relay.png'), root_png, latest, index]}
        r.regenerate(self.hist)
        self.fetch.assert_not_called()
        for path, payload in snapshots.items():
            self.assertEqual(path.read_bytes(), payload, str(path))
        home = self.read()
        self.canonical(home, '')
        comparison = home.section('comparison')
        observed = [d for d in days if d not in pending][-5:][::-1]
        row_links = [a.attrs.get('href', '') for table in comparison.find('table') for a in table.find('a')]
        self.assertEqual([next(d for d in days if d in href) for href in row_links], observed)
        self.assertNotIn('0.00%', home.section('result-area').text)
        self.assertTrue(any(word in home.section('result-area').text for word in ('기다', '대기')))
        for month in ('2026-09', '2026-10'):
            archive = self.read('archive/' + month)
            self.canonical(archive, 'archive/' + month)
            for d in [d for d in days if d.startswith(month)]:
                rows = [row for row in archive.find('tr') if any(d in a.attrs.get('href', '') for a in row.find('a'))]
                self.assertEqual(len(rows), 1, d)
                if d in pending:
                    if d == days[-1]:
                        self.assertIn('시가 대기', rows[0].text)
                        self.assertIn('종가 대기', rows[0].text)
                        self.assertNotIn('기록이 없어요', rows[0].text)
                    else:
                        self.assertIn('기록이 없어요', rows[0].text)
                        self.assertNotIn('대기', rows[0].text)
                    self.assertNotIn('휴장', rows[0].text)
        self.assertTrue(any('/archive/2026-10/' in x for x in self.read('archive/2026-09').links('next')))
        self.assertTrue(any('/archive/2026-09/' in x for x in self.read('archive/2026-10').links('prev')))
        for i, d in enumerate(days):
            doc = self.read(d)
            self.canonical(doc, d)
            # Even the latest publication can be a past date (weekends, late updates).
            # The shared ditoaxis menu (dx-bar) describes other services and is not dated content.
            self.assertNotIn('오늘', doc.find('main')[0].text)
            for meta in doc.find('meta'):
                self.assertNotIn('오늘', meta.attrs.get('content', ''))
            text = (self.site / d / 'index.html').read_text()
            for poisoned in ('987654', 'LEGACY_HEAD', 'LEGACY_CLAIM', 'LEGACY_SENTENCE', 'LEGACY_NY', 'LEGACY_KR'):
                self.assertNotIn(poisoned, text)
            if i:
                self.assertTrue(any(days[i-1] in x for x in doc.links('prev')))
            if i + 1 < len(days):
                self.assertTrue(any(days[i+1] in x for x in doc.links('next')))
                self.assertIn('최신 기록 보기', doc.root.text)
                for n in doc.find('title') + doc.find('h1') + doc.find('h2') + doc.find('meta'):
                    self.assertNotIn('오늘', n.text + n.attrs.get('content', ''))
            share_scripts = [n.text for n in doc.find('script') if 'navigator.share' in n.text]
            self.assertEqual(len(share_scripts), 1)
            self.assertIn(r.SITE_URL.rstrip('/') + '/' + d + '/', share_scripts[0])
        about = self.read('about')
        self.canonical(about, 'about')
        self.assertNotIn('해당 날짜', about.root.text)
        for word in ('SOXX', 'QQQ', 'SPY', 'ETF', '0.3%', 'Yahoo', '디토엑시스', 'help.ditoaxis@gmail.com'):
            self.assertIn(word, about.root.text)
        self.assertTrue(any('/privacy/' in a for a in about.links()))
        self.assertTrue((self.site / 'privacy/index.html').exists())
        self.assertIn('sitemap.xml', (self.site / 'robots.txt').read_text())
        sitemap = ET.parse(self.site / 'sitemap.xml')
        locations = {n.text for n in sitemap.findall('.//{*}loc')}
        for route in ['', *days, 'archive/2026-09', 'archive/2026-10', 'about']:
            self.assertIn(r.SITE_URL.rstrip('/') + '/' + (route + '/' if route else ''), locations)

    def test_regenerated_frequency_uses_history_and_unavailable_history_is_empty(self):
        day = '2026-09-04'
        self.write(legacy_record(day))
        hist = r.pd.DataFrame({'gap': [.01, .0, -.01, -.02], 's': [.004] * 4},
                             index=r.pd.to_datetime(['2026-09-01', '2026-09-02', day, '2026-09-07']))
        with patch.object(r, 'frequency', wraps=r.frequency) as freq:
            r.regenerate(hist)
        expected = r.frequency(hist, .004, r.pd.Timestamp(day))
        self.assertEqual(expected['n'], 2)
        self.assertTrue(freq.called)
        for call in freq.call_args_list:
            if len(call.args) >= 3:
                self.assertEqual(r.pd.Timestamp(call.args[2]), r.pd.Timestamp(day))
        doc = self.read(day)
        self.assertEqual(doc.section('frequency-area').attrs['data-sample-count'], '2')
        self.assertNotIn('987654', doc.root.text)
        r.regenerate(hist.iloc[2:])
        text = self.read(day).section('frequency-area').text
        self.assertTrue(any(word in text for word in ('없어요', '기다', '대기', '채워지면')), text)
        with patch.object(r, 'fetch', side_effect=RuntimeError('fixture offline')) as fetch:
            r.regenerate()
        fetch.assert_called_once()
        self.assertNotIn('987654', self.read(day).root.text)
        self.fetch.reset_mock()
        r.regenerate()
        self.fetch.assert_called_once()

    def test_waiting_copy_only_on_latest_record_across_pages_and_tables(self):
        # A missing NY window and an unobserved historical close are final gaps.
        self.write(legacy_record('2026-09-08', status='filled', missing=True))
        self.write(legacy_record('2026-09-09', status='filled'))
        self.write(legacy_record('2026-09-30', status='pending'))
        self.write(legacy_record('2026-10-01', status='pending', missing=True))
        r.regenerate(self.hist)
        for day in ('2026-09-08', '2026-09-09', '2026-09-30'):
            body = self.read(day).find('body')[0].text
            for waiting in ('대기', '기다리', '채워지면', '들어오면'):
                self.assertNotIn(waiting, body, day)
            self.assertIn('기록이 없어요', body)
        past = self.read('2026-09-08')
        self.assertIn('비교할 미국 증시 자료가 없어요', past.section('ny-area').text)
        self.assertIn('비교할 과거 기록이 없어요', past.section('frequency-area').text)
        past_cells = past.section('comparison').find('tbody')[0].find('tr')[0].find('td')
        self.assertEqual([cell.text for cell in past_cells[:3]], ['기록이 없어요'] * 3)
        self.assertEqual(past_cells[-1].text, '기록이 없어요')
        # The most recent row of a past month is not the latest publication.
        september = self.read('archive/2026-09').section('archive-table').text
        self.assertNotIn('대기', september)

        def latest_archive_cells():
            rows = self.read('archive/2026-10').section('archive-table').find('tbody')[0].find('tr')
            row = next(row for row in rows if row.attrs['data-date'] == '2026-10-01')
            return [cell.text for cell in row.find('td')]

        self.assertEqual(latest_archive_cells(), ['자료 대기'] * 3 + ['시가 대기', '종가 대기'])
        for route in ('', '2026-10-01'):
            doc = self.read(route)
            self.assertIn('미국 증시 자료를 기다리고 있어요', doc.section('ny-area').text)
            self.assertIn('자료가 채워지면', doc.section('frequency-area').text)
            self.assertIn('시가 대기', doc.section('result-area').text)
            self.assertIn('종가 대기', doc.section('result-area').text)

        self.write(legacy_record('2026-10-01', status='filled', missing=True))
        r.regenerate(self.hist)
        self.assertEqual(latest_archive_cells(), ['자료 대기'] * 3 + ['+1.23%', '종가 대기'])
        self.assertIn('종가 대기', self.read().section('comparison').text)

        # Once a newer publication arrives, the same gaps stop promising updates.
        self.write(legacy_record('2026-10-02', status='pending'))
        r.regenerate(self.hist)
        self.assertEqual(latest_archive_cells(), ['기록이 없어요'] * 3 + ['+1.23%', '기록이 없어요'])
        self.assertNotIn('대기', self.read('2026-10-01').find('body')[0].text)
        self.assertNotIn('대기', self.read().section('comparison').text)

    def test_sequential_publication_and_share_card(self):
        day = '2026-09-29'
        before = None
        for phase, status in [('morning', 'pending'), ('open', 'filled'), ('close', 'done')]:
            published = self.publish(day, phase)
            self.assertEqual(published['status'], status)
            self.assertEqual(published['open'] is None, phase == 'morning')
            self.assertEqual(published['close'] is None, phase != 'close')
            self.assertTrue(set(legacy_record(day)).issubset(published))
            signal = r.signal(published['us']['SPY'][1], published['us']['SOXX'][1])
            self.assertEqual(published['freq'], r.frequency(self.hist, signal, r.pd.Timestamp(day)))
            doc = self.read(day)
            result_area = doc.section('result-area')
            result = result_area.text
            self.assertEqual([n.attrs['data-observed'] for n in result_area.find(cls='result-row')],
                             ['false', 'false'] if phase == 'morning' else ['true', 'false'] if phase == 'open' else ['true', 'true'])
            self.assertEqual(doc.section('frequency-area').attrs['data-sample-count'], str(published['freq']['n']))
            if phase == 'morning':
                self.assertNotIn('0.00%', result)
                self.assertTrue(any(word in result for word in ('대기', '기다')))
            if phase == 'open':
                self.assertTrue(any(word in result for word in ('대기', '기다')))
            if phase != 'morning':
                self.assertIn(r.pct(published['open']), result)
            if phase == 'close':
                self.assertIn(r.pct(published['close']), result)
            if before is not None:
                self.assertNotEqual(before, (self.site / day / 'index.html').read_bytes())
            before = (self.site / day / 'index.html').read_bytes()
            self.assertNotIn('최신 기록 보기', doc.root.text)
            self.assertTrue(self.captures[-1].count('class="sheet"') == 1)
            self.assertNotIn('class="comparison"', self.captures[-1])
            index = json.loads((self.site / 'index.json').read_text())
            self.assertTrue(all({'d', 'z'}.issubset(row) for row in index))
        snapshot = (self.site / day / 'relay.png').read_bytes()
        self.publish('2026-09-30', 'morning')
        previous = self.read(day)
        self.assertTrue(any('2026-09-30' in x for x in previous.links('next')))
        self.assertIn('최신 기록 보기', previous.root.text)
        self.assertNotIn('오늘', ''.join(n.text for n in previous.find('h1') + previous.find('title')))
        self.publish('2026-10-01', 'morning')
        self.assertTrue(any('/archive/2026-10/' in x for x in self.read('archive/2026-09').links('next')))
        self.assertTrue(any('/archive/2026-09/' in x for x in self.read('archive/2026-10').links('prev')))
        self.assertEqual((self.site / day / 'relay.png').read_bytes(), snapshot)

    def test_missing_and_reused_sources_and_ad_eligibility(self):
        self.write(legacy_record('2026-09-28', missing=True))
        self.write(legacy_record('2026-09-29', reused=True))
        self.write(legacy_record('2026-09-30', status='pending'))
        r.regenerate(self.hist)
        missing_ny = self.read('2026-09-28').section('ny-area').text
        self.assertIn('비교할 미국 증시 자료가 없어요', missing_ny)
        self.assertNotIn('대기', missing_ny)
        self.assertNotIn('0.00%', missing_ny)
        self.assertIn('이전에 확인한', self.read('2026-09-29').root.text)
        for client, slot in [('', ''), ('ca-pub-fixture', ''), ('', '12345'), ('ca-pub-fixture', '12345')]:
            with patch.object(r, 'ADSENSE', client), patch.object(r, 'ADSENSE_SLOT', slot):
                r.regenerate(self.hist)
            for route in ('', '2026-09-28', '2026-09-29', '2026-09-30'):
                doc = self.read(route)
                units = doc.find('ins', 'adsbygoogle')
                expected = int(bool(client and slot) and route in ('2026-09-28', '2026-09-29'))
                self.assertEqual(len(units), expected, (client, slot, route))
                self.assertEqual(len(doc.find(cls='ad-slot')), expected)
                ad_scripts = [n for n in doc.find('script') if 'pagead2.googlesyndication.com' in n.attrs.get('src', '')]
                self.assertEqual(len(ad_scripts), int(bool(client)))
                if units:
                    self.assertEqual(units[0].attrs.get('data-ad-client'), client)
                    self.assertEqual(units[0].attrs.get('data-ad-slot'), slot)
                    self.assertIn('광고', doc.root.text)
        self.write(legacy_record('2026-09-30', status='filled'))
        with patch.object(r, 'ADSENSE', 'ca-pub-fixture'), patch.object(r, 'ADSENSE_SLOT', '12345'):
            r.regenerate(self.hist)
        self.assertEqual(len(self.read().find('ins', 'adsbygoogle')), 1)
        for route in ('about', 'archive/2026-09'):
            self.assertEqual(len(self.read(route).find('ins', 'adsbygoogle')), 0)

    def test_backfill_cutoff_and_reused_provenance(self):
        day = '2026-10-16'
        r.backfill(2)
        for date in ('2026-10-15', day):
            fresh = json.loads((self.site / 'days' / (date + '.json')).read_text())
            self.assertEqual(fresh['source_states'], {key: 'fresh' for key in r.US})
            self.assertTrue(all(fresh['source_dates'].values()))
            self.assertTrue(fresh['source_note'] and fresh['built_at'])
            self.assertEqual(fresh['freq'], r.frequency(self.hist, r.signal(fresh['us']['SPY'][1], fresh['us']['SOXX'][1]), r.pd.Timestamp(date)))
        original = self.publish(day, 'close')
        # Force same-day reuse with the exact basis preserved.
        for key in r.US:
            self.raw[key].loc[r.pd.Timestamp('2026-10-15'), 'Close'] = r.np.nan
        self.hist = r.align(self.raw)
        r.backfill(1)
        got = json.loads((self.site / 'days' / (day + '.json')).read_text())
        self.assertTrue(set(original).issubset(got))
        for key in ('source_states', 'source_dates', 'source_note', 'built_at'):
            self.assertIn(key, got)
        self.assertEqual(got['source_states'], {key: 'reused' for key in r.US})
        self.assertEqual(got['source_dates'], original['source_dates'])
        self.assertTrue(got['built_at'])
        self.assertIn('기존 게시값', got['source_note'])
        self.assertIn('이전에 확인한', got['head']['cond'])
        self.assertIn('이전에 확인한', got['sentence'])
        self.assertEqual(got['freq'], r.frequency(self.hist, r.signal(got['us']['SPY'][1], got['us']['SOXX'][1]), r.pd.Timestamp(day)))
        self.assertIn('이전에 확인한', self.read(day).root.text)
        self.assertEqual(self.read(day).section('frequency-area').attrs['data-sample-count'], str(got['freq']['n']))
        self.canonical(self.read(), '')
        self.assertTrue(any(day in href for href in self.read('archive/2026-10').links()))

    def test_backfill_refreshes_only_changed_day_images(self):
        day = '2026-10-16'
        r.backfill(1)
        archive = self.site / 'days' / (day + '.json')
        png = self.site / day / 'relay.png'
        original = json.loads(archive.read_text())
        self.assertEqual(len(self.captures), 2)
        png.write_bytes(b'unchanged publication PNG')
        archive.write_text(json.dumps({**original, 'built_at': '2026-10-16T16:00+09:00'}))
        r.backfill(1)
        self.assertEqual(len(self.captures), 2)
        self.assertEqual(png.read_bytes(), b'unchanged publication PNG')
        changed_us = {**original['us'], 'SPY': [0, -.02]}
        for key, value in [('status', 'filled'), ('open', .99), ('close', -.99), ('us', changed_us),
                           ('freq', {**original['freq'], 'n': 987654}),
                           ('head', {**original['head'], 'claim': 'stale claim'}),
                           ('kr', '<svg>stale statistics</svg>'), ('sentence', 'stale sentence'),
                           ('source_note', 'stale source note')]:
            archive.write_text(json.dumps({**original, key: value}))
            png.write_bytes(b'stale ' + key.encode())
            before = len(self.captures)
            r.backfill(1)
            self.assertEqual(len(self.captures), before + 2, key)
            self.assertEqual(json.loads(archive.read_text())[key], original[key])
            self.assertEqual(png.read_bytes(), b'fixture share image')
        before = len(self.captures)
        png.write_bytes(b'preserve during HTML regeneration')
        r.regenerate(self.hist)
        self.assertEqual(len(self.captures), before)
        self.assertEqual(png.read_bytes(), b'preserve during HTML regeneration')

    def test_share_card_loads_no_ads(self):
        # Ads on the capture page keep the network busy and time out the screenshot.
        self.patch(r, 'ADSENSE', 'ca-pub-fixture')
        r.backfill(1)
        self.assertTrue(self.captures)
        self.assertNotIn('googlesyndication', self.captures[-1])
        self.assertNotIn('https://ditoaxis.com/m.js', self.captures[-1])
        self.assertNotIn('cloudflareinsights.com', self.captures[-1])

    def test_backfill_keeps_no_session_flag(self):
        day = '2026-10-16'
        self.write({**legacy_record(day, missing=True), 'freq': None})
        for key in r.US:
            self.raw[key].loc[r.pd.Timestamp('2026-10-15'), 'Close'] = r.np.nan
        r.backfill(1)
        self.assertIsNone(json.loads((self.site / 'days' / (day + '.json')).read_text())['freq'])
        self.assertIn('비교할 미국 증시 자료가 없어요', self.read(day).root.text)

    def test_backfill_close_present_without_open_keeps_done_status(self):
        day = r.pd.Timestamp('2026-10-16')
        self.raw['KOSPI'].loc[day, 'Open'] = r.np.nan
        r.backfill(1)
        archive = self.site / 'days/2026-10-16.json'
        result = json.loads(archive.read_text())
        self.assertEqual(result['status'], 'done')
        self.assertIsNone(result['open'])
        self.assertIsNotNone(result['close'])
        # The original done ordering preserves that known close on a later miss.
        self.raw['KOSPI'].loc[day, 'Close'] = r.np.nan
        r.backfill(1)
        preserved = json.loads(archive.read_text())
        self.assertEqual(preserved['status'], 'done')
        self.assertIsNone(preserved['open'])
        self.assertEqual(preserved['close'], result['close'])



class ShareCardTests(unittest.TestCase):
    """공유 카드(relay.png·og.png 원본)는 밤사이 / 아침 시작 / 오후 마감 말로 써요. 줄표 자리표시 없음."""
    def test_card_labels_use_new_wording(self):
        D = r.pd.Timestamp('2026-10-21')
        for status, opened in (('pending', None), ('filled', 0.0205), ('done', 0.0205), ('closed', None)):
            for landscape in (False, True):
                page = r.share_card_page(D, None, {}, None, opened, None, status, None, landscape=landscape)
                visible = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', page, flags=re.S)
                visible = re.sub(r'<[^>]+>', ' ', visible)
                for stale in ('뉴욕 지표', '코스피 시가', '오늘 시가', '시가 반영', '—'):
                    self.assertNotIn(stale, visible, (status, landscape, stale))
                self.assertIn('밤사이 미국 증시', visible)
                self.assertIn('다음 날 코스피 아침 시작', visible)
        self.assertEqual(r.pct(None), '자료 없음')


if __name__ == '__main__':
    unittest.main(verbosity=2)
