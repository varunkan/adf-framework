import json
import threading
import unittest
import http.client
from datetime import datetime, timezone, timedelta

import server


class URLShortenerTest(unittest.TestCase):
    def setUp(self):
        # use a fresh in-memory store for tests
        server.STORE = {}
        self.server = server.make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _conn(self):
        return http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)

    def test_index_served(self):
        conn = self._conn()
        conn.request('GET', '/')
        resp = conn.getresponse()
        body = resp.read().decode('utf-8')
        self.assertEqual(resp.status, 200)
        self.assertIn('text/html', resp.getheader('Content-Type'))
        self.assertIn('URL Shortener', body)
        conn.close()

    def test_url_input_has_accessible_name(self):
        # A11y: the URL field must have an accessible name (label/aria-label),
        # not just a placeholder, so screen readers can announce it.
        conn = self._conn()
        conn.request('GET', '/')
        resp = conn.getresponse()
        body = resp.read().decode('utf-8')
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn('for="urlInput"', body)
        self.assertIn('aria-label="Long URL to shorten"', body)

    def test_shorten_and_redirect(self):
        # REQ-001/002: create short code
        conn = self._conn()
        payload = json.dumps({'url': 'https://example.com/some/long/path'})
        conn.request('POST', '/api/shorten', body=payload,
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 201)
        data = json.loads(resp.read().decode('utf-8'))
        conn.close()
        self.assertIn('code', data)
        self.assertEqual(data['url'], 'https://example.com/some/long/path')
        code = data['code']

        # REQ-003: visiting short URL redirects (302) without auto-follow
        conn = self._conn()
        conn.request('GET', '/' + code)
        resp = conn.getresponse()
        self.assertEqual(resp.status, 302)
        self.assertEqual(resp.getheader('Location'),
                         'https://example.com/some/long/path')
        resp.read()
        conn.close()

        # expand API returns the mapping
        conn = self._conn()
        conn.request('GET', '/api/expand/' + code)
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        edata = json.loads(resp.read().decode('utf-8'))
        self.assertEqual(edata['url'], 'https://example.com/some/long/path')
        conn.close()

    def test_list_contains_entry(self):
        conn = self._conn()
        conn.request('POST', '/api/shorten',
                     body=json.dumps({'url': 'https://test.org/page'}),
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 201)
        resp.read()
        conn.close()

        conn = self._conn()
        conn.request('GET', '/api/list')
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode('utf-8'))
        conn.close()
        urls = [item['url'] for item in data['items']]
        self.assertIn('https://test.org/page', urls)

    def test_invalid_url_returns_400(self):
        conn = self._conn()
        conn.request('POST', '/api/shorten',
                     body=json.dumps({'url': 'not-a-valid-url'}),
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        data = json.loads(resp.read().decode('utf-8'))
        self.assertIn('error', data)
        conn.close()

    def test_empty_url_returns_400(self):
        conn = self._conn()
        conn.request('POST', '/api/shorten',
                     body=json.dumps({'url': '   '}),
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        resp.read()
        conn.close()

    def test_unknown_code_returns_404(self):
        conn = self._conn()
        conn.request('GET', '/api/expand/doesnotexist')
        resp = conn.getresponse()
        self.assertEqual(resp.status, 404)
        data = json.loads(resp.read().decode('utf-8'))
        self.assertIn('error', data)
        conn.close()

    def test_redirect_unknown_code_404(self):
        conn = self._conn()
        conn.request('GET', '/nope123')
        resp = conn.getresponse()
        self.assertEqual(resp.status, 404)
        resp.read()
        conn.close()

    # ---- helpers -------------------------------------------------------

    def _shorten(self, url, **extra):
        body = {'url': url}
        body.update(extra)
        conn = self._conn()
        conn.request('POST', '/api/shorten', body=json.dumps(body),
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        data = json.loads(resp.read().decode('utf-8'))
        status = resp.status
        conn.close()
        return status, data

    def _get(self, path):
        conn = self._conn()
        conn.request('GET', path)
        resp = conn.getresponse()
        raw = resp.read()
        status = resp.status
        ctype = resp.getheader('Content-Type')
        conn.close()
        return status, raw, ctype

    # ---- backfill: previously-untested existing features ---------------

    def test_summary_endpoint(self):
        self._shorten('https://a.example.com/')
        self._shorten('https://b.example.com/', alias='mylink')
        status, raw, _ = self._get('/api/summary')
        self.assertEqual(status, 200)
        data = json.loads(raw.decode('utf-8'))
        self.assertEqual(data['total_links'], 2)
        self.assertEqual(data['custom_links'], 1)
        self.assertEqual(data['active_links'], 2)
        self.assertEqual(data['expired_links'], 0)
        self.assertIn('total_clicks', data)

    def test_stats_endpoint(self):
        _, data = self._shorten('https://stats.example.com/')
        code = data['code']
        status, raw, _ = self._get('/api/stats/' + code)
        self.assertEqual(status, 200)
        sdata = json.loads(raw.decode('utf-8'))
        self.assertEqual(sdata['code'], code)
        self.assertEqual(sdata['clicks'], 0)

    def test_stats_unknown_code_404(self):
        status, raw, _ = self._get('/api/stats/missing')
        self.assertEqual(status, 404)

    def test_click_count_increments(self):
        _, data = self._shorten('https://clicks.example.com/')
        code = data['code']
        for _ in range(3):
            self._get('/' + code)
        _, raw, _ = self._get('/api/stats/' + code)
        sdata = json.loads(raw.decode('utf-8'))
        self.assertEqual(sdata['clicks'], 3)
        self.assertIsNotNone(sdata['last_clicked'])

    def test_duplicate_url_returns_same_code(self):
        _, a = self._shorten('https://dup.example.com/path')
        _, b = self._shorten('https://dup.example.com/path')
        self.assertEqual(a['code'], b['code'])

    def test_custom_alias(self):
        status, data = self._shorten('https://aliased.example.com/', alias='promo')
        self.assertEqual(status, 201)
        self.assertEqual(data['code'], 'promo')
        self.assertTrue(data['custom'])
        # redirect via the alias works
        s, _, _ = self._get('/promo')
        self.assertEqual(s, 302)

    def test_alias_conflict_returns_409(self):
        self._shorten('https://first.example.com/', alias='taken')
        status, data = self._shorten('https://second.example.com/', alias='taken')
        self.assertEqual(status, 409)
        self.assertIn('error', data)

    def test_invalid_alias_returns_400(self):
        status, data = self._shorten('https://bad.example.com/', alias='no spaces!')
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_reserved_alias_returns_400(self):
        status, _ = self._shorten('https://x.example.com/', alias='api')
        self.assertEqual(status, 400)

    def test_expires_in_sets_expiry(self):
        status, data = self._shorten('https://exp.example.com/', expires_in=3600)
        self.assertEqual(status, 201)
        self.assertIsNotNone(data['expires_at'])
        self.assertFalse(data['expired'])

    def test_invalid_expires_in_returns_400(self):
        status, data = self._shorten('https://exp.example.com/', expires_in=-5)
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_expired_link_redirect_returns_410(self):
        # Seed an entry whose expiry is already in the past.
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        server.STORE['gone'] = {'url': 'https://old.example.com/', 'clicks': 0,
                                'created': server._now_iso(), 'custom': False,
                                'expires_at': past}
        s, _, _ = self._get('/gone')
        self.assertEqual(s, 410)
        s2, _, _ = self._get('/api/expand/gone')
        self.assertEqual(s2, 410)

    def test_update_repoints_url_via_put(self):
        _, data = self._shorten('https://before.example.com/')
        code = data['code']
        conn = self._conn()
        conn.request('PUT', '/api/update/' + code,
                     body=json.dumps({'url': 'https://after.example.com/'}),
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        udata = json.loads(resp.read().decode('utf-8'))
        conn.close()
        self.assertEqual(udata['url'], 'https://after.example.com/')
        # redirect now points at the new destination
        conn = self._conn()
        conn.request('GET', '/' + code)
        resp = conn.getresponse()
        self.assertEqual(resp.getheader('Location'), 'https://after.example.com/')
        resp.read()
        conn.close()

    def test_update_via_post_fallback(self):
        _, data = self._shorten('https://orig.example.com/')
        code = data['code']
        conn = self._conn()
        conn.request('POST', '/api/update/' + code,
                     body=json.dumps({'url': 'https://new.example.com/'}),
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        resp.read()
        conn.close()

    def test_update_unknown_code_returns_404(self):
        conn = self._conn()
        conn.request('PUT', '/api/update/nope',
                     body=json.dumps({'url': 'https://x.example.com/'}),
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 404)
        resp.read()
        conn.close()

    def test_update_invalid_url_returns_400(self):
        _, data = self._shorten('https://valid.example.com/')
        code = data['code']
        conn = self._conn()
        conn.request('PUT', '/api/update/' + code,
                     body=json.dumps({'url': 'ftp://nope'}),
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        resp.read()
        conn.close()

    def test_delete_removes_code(self):
        _, data = self._shorten('https://del.example.com/')
        code = data['code']
        conn = self._conn()
        conn.request('DELETE', '/api/delete/' + code)
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        resp.read()
        conn.close()
        # gone now
        s, _, _ = self._get('/api/expand/' + code)
        self.assertEqual(s, 404)

    def test_delete_via_post_fallback(self):
        _, data = self._shorten('https://delp.example.com/')
        code = data['code']
        conn = self._conn()
        conn.request('POST', '/api/delete/' + code)
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        resp.read()
        conn.close()

    def test_delete_unknown_code_returns_404(self):
        conn = self._conn()
        conn.request('DELETE', '/api/delete/missing')
        resp = conn.getresponse()
        self.assertEqual(resp.status, 404)
        resp.read()
        conn.close()

    def test_search_filters_list(self):
        self._shorten('https://apples.example.com/')
        self._shorten('https://bananas.example.com/')
        _, raw, _ = self._get('/api/list?q=apples')
        items = json.loads(raw.decode('utf-8'))['items']
        urls = [it['url'] for it in items]
        self.assertIn('https://apples.example.com/', urls)
        self.assertNotIn('https://bananas.example.com/', urls)

    # ---- new features --------------------------------------------------

    def test_health_endpoint(self):
        self._shorten('https://h.example.com/')
        status, raw, _ = self._get('/api/health')
        self.assertEqual(status, 200)
        data = json.loads(raw.decode('utf-8'))
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['links'], 1)

    def test_export_csv(self):
        self._shorten('https://csv.example.com/page', alias='exp1')
        status, raw, ctype = self._get('/api/export')
        self.assertEqual(status, 200)
        self.assertIn('text/csv', ctype)
        text = raw.decode('utf-8')
        lines = [ln for ln in text.splitlines() if ln.strip()]
        self.assertEqual(lines[0],
                         'code,url,clicks,created,custom,expires_at,expired')
        self.assertTrue(any('exp1' in ln and 'csv.example.com' in ln
                            for ln in lines[1:]))

    def test_shorten_bulk(self):
        conn = self._conn()
        payload = json.dumps({'urls': [
            'https://one.example.com/',
            'https://two.example.com/',
            'https://three.example.com/',
        ]})
        conn.request('POST', '/api/shorten_bulk', body=payload,
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode('utf-8'))
        conn.close()
        self.assertEqual(data['total'], 3)
        self.assertEqual(data['created'], 3)
        self.assertTrue(all(r['ok'] for r in data['results']))
        # each created code redirects
        for r in data['results']:
            s, _, _ = self._get('/' + r['code'])
            self.assertEqual(s, 302)

    def test_shorten_bulk_mixed_valid_invalid(self):
        conn = self._conn()
        payload = json.dumps({'urls': [
            'https://good.example.com/',
            'not-a-url',
            {'url': 'https://obj.example.com/', 'alias': 'bulkalias'},
        ]})
        conn.request('POST', '/api/shorten_bulk', body=payload,
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode('utf-8'))
        conn.close()
        self.assertEqual(data['total'], 3)
        self.assertEqual(data['created'], 2)
        self.assertFalse(data['results'][1]['ok'])
        self.assertEqual(data['results'][1]['status'], 400)
        self.assertEqual(data['results'][2]['code'], 'bulkalias')

    def test_shorten_bulk_empty_returns_400(self):
        conn = self._conn()
        conn.request('POST', '/api/shorten_bulk',
                     body=json.dumps({'urls': []}),
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        resp.read()
        conn.close()

    def test_list_sort_by_clicks_desc(self):
        _, a = self._shorten('https://low.example.com/')
        _, b = self._shorten('https://high.example.com/')
        # give b more clicks
        for _ in range(2):
            self._get('/' + b['code'])
        _, raw, _ = self._get('/api/list?sort=clicks&order=desc')
        items = json.loads(raw.decode('utf-8'))['items']
        self.assertEqual(items[0]['code'], b['code'])

    def test_list_sort_by_code_asc(self):
        self._shorten('https://z.example.com/', alias='zeta')
        self._shorten('https://a.example.com/', alias='alpha')
        _, raw, _ = self._get('/api/list?sort=code&order=asc')
        codes = [it['code'] for it in json.loads(raw.decode('utf-8'))['items']]
        self.assertEqual(codes, sorted(codes))

    # ---- new features: tags --------------------------------------------

    def _post(self, path, body=None):
        conn = self._conn()
        if body is None:
            conn.request('POST', path)
        else:
            conn.request('POST', path, body=json.dumps(body),
                         headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        raw = resp.read()
        status = resp.status
        conn.close()
        data = json.loads(raw.decode('utf-8')) if raw else {}
        return status, data

    def test_shorten_with_tags(self):
        # tags supplied as a comma-separated string are normalized + stored
        status, data = self._shorten('https://tagged.example.com/',
                                     tags='Work, Reading , work')
        self.assertEqual(status, 201)
        # deduped, lowercased, order preserved
        self.assertEqual(data['tags'], ['work', 'reading'])

    def test_shorten_with_tags_list(self):
        # tags may also be supplied as a JSON array
        status, data = self._shorten('https://taglist.example.com/',
                                     tags=['news', 'tech'])
        self.assertEqual(status, 201)
        self.assertEqual(data['tags'], ['news', 'tech'])

    def test_list_filter_by_tag(self):
        self._shorten('https://red.example.com/', tags='color')
        self._shorten('https://blue.example.com/', tags='other')
        _, raw, _ = self._get('/api/list?tag=color')
        urls = [it['url'] for it in json.loads(raw.decode('utf-8'))['items']]
        self.assertIn('https://red.example.com/', urls)
        self.assertNotIn('https://blue.example.com/', urls)

    def test_tags_endpoint_counts(self):
        self._shorten('https://t1.example.com/', tags='alpha,beta')
        self._shorten('https://t2.example.com/', tags='alpha')
        status, raw, _ = self._get('/api/tags')
        self.assertEqual(status, 200)
        data = json.loads(raw.decode('utf-8'))
        counts = {t['tag']: t['count'] for t in data['tags']}
        self.assertEqual(counts['alpha'], 2)
        self.assertEqual(counts['beta'], 1)
        self.assertEqual(data['total'], 2)

    def test_bulk_with_tags(self):
        status, data = self._post('/api/shorten_bulk', {'urls': [
            {'url': 'https://b1.example.com/', 'tags': 'promo'},
            {'url': 'https://b2.example.com/', 'tags': ['promo', 'sale']},
        ]})
        self.assertEqual(status, 200)
        self.assertEqual(data['created'], 2)
        self.assertEqual(data['results'][0]['tags'], ['promo'])
        self.assertEqual(data['results'][1]['tags'], ['promo', 'sale'])

    def test_summary_counts_tagged(self):
        self._shorten('https://has.example.com/', tags='x')
        self._shorten('https://none.example.com/')
        status, raw, _ = self._get('/api/summary')
        self.assertEqual(status, 200)
        data = json.loads(raw.decode('utf-8'))
        self.assertEqual(data['tagged_links'], 1)
        self.assertEqual(data['tags'].get('x'), 1)

    # ---- new features: disable / enable --------------------------------

    def test_disable_blocks_redirect(self):
        _, data = self._shorten('https://dis.example.com/')
        code = data['code']
        status, ddata = self._post('/api/disable/' + code)
        self.assertEqual(status, 200)
        self.assertTrue(ddata['disabled'])
        # the short link no longer redirects
        s, _, _ = self._get('/' + code)
        self.assertEqual(s, 403)

    def test_disabled_link_does_not_count_clicks(self):
        _, data = self._shorten('https://noclick.example.com/')
        code = data['code']
        self._post('/api/disable/' + code)
        self._get('/' + code)  # blocked, should not increment
        _, raw, _ = self._get('/api/stats/' + code)
        self.assertEqual(json.loads(raw.decode('utf-8'))['clicks'], 0)

    def test_enable_restores_redirect(self):
        _, data = self._shorten('https://en.example.com/')
        code = data['code']
        self._post('/api/disable/' + code)
        status, edata = self._post('/api/enable/' + code)
        self.assertEqual(status, 200)
        self.assertFalse(edata['disabled'])
        s, _, _ = self._get('/' + code)
        self.assertEqual(s, 302)

    def test_disabled_expand_returns_403(self):
        _, data = self._shorten('https://exp403.example.com/')
        code = data['code']
        self._post('/api/disable/' + code)
        s, _, _ = self._get('/api/expand/' + code)
        self.assertEqual(s, 403)

    def test_disable_unknown_code_returns_404(self):
        status, data = self._post('/api/disable/missing')
        self.assertEqual(status, 404)
        self.assertIn('error', data)

    def test_summary_counts_disabled(self):
        _, data = self._shorten('https://d1.example.com/')
        self._shorten('https://d2.example.com/')
        self._post('/api/disable/' + data['code'])
        status, raw, _ = self._get('/api/summary')
        sdata = json.loads(raw.decode('utf-8'))
        self.assertEqual(sdata['disabled_links'], 1)
        # a disabled link is no longer "active"
        self.assertEqual(sdata['active_links'], 1)

    # ---- new features: partial update ----------------------------------

    def test_update_sets_tags_without_repointing(self):
        _, data = self._shorten('https://retag.example.com/')
        code = data['code']
        conn = self._conn()
        conn.request('PUT', '/api/update/' + code,
                     body=json.dumps({'tags': 'fresh,Labels'}),
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        udata = json.loads(resp.read().decode('utf-8'))
        conn.close()
        # url is preserved (partial update), tags applied + normalized
        self.assertEqual(udata['url'], 'https://retag.example.com/')
        self.assertEqual(udata['tags'], ['fresh', 'labels'])

    def test_update_toggles_disabled(self):
        _, data = self._shorten('https://toggle.example.com/')
        code = data['code']
        conn = self._conn()
        conn.request('PUT', '/api/update/' + code,
                     body=json.dumps({'disabled': True}),
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        udata = json.loads(resp.read().decode('utf-8'))
        conn.close()
        self.assertTrue(udata['disabled'])
        s, _, _ = self._get('/' + code)
        self.assertEqual(s, 403)


if __name__ == '__main__':
    unittest.main()
