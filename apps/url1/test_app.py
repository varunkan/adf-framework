import os
import time
import json
import threading
import unittest
import http.client

import server


class URLShortenerTest(unittest.TestCase):
    def setUp(self):
        # Use a fresh data file for tests so state is isolated.
        self.data_file = server.DATA_FILE
        if os.path.exists(self.data_file):
            os.remove(self.data_file)
        self.server = server.make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if os.path.exists(self.data_file):
            os.remove(self.data_file)

    def _conn(self):
        return http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)

    # --- helpers -------------------------------------------------------
    def _request(self, method, path, body=None):
        conn = self._conn()
        headers = {}
        data = None
        if body is not None:
            data = json.dumps(body)
            headers['Content-Type'] = 'application/json'
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        status = resp.status
        ctype = resp.getheader('Content-Type') or ''
        conn.close()
        return status, raw, ctype

    def _json(self, method, path, body=None):
        status, raw, _ = self._request(method, path, body)
        return status, json.loads(raw.decode('utf-8')) if raw else None

    def _shorten(self, **body):
        return self._json('POST', '/api/shorten', body)

    def _seed(self, store):
        """Write a store dict straight to the data file the server reads."""
        server._save_store(store)

    def test_index_served(self):
        conn = self._conn()
        conn.request('GET', '/')
        resp = conn.getresponse()
        body = resp.read().decode('utf-8')
        self.assertEqual(resp.status, 200)
        self.assertIn('text/html', resp.getheader('Content-Type'))
        self.assertIn('URL Shortener', body)
        conn.close()

    def test_url_input_has_accessible_label(self):
        # The URL field must have a programmatic accessible name, not just a
        # placeholder, so screen-reader users can identify it (WCAG 1.3.1 / 4.1.2).
        conn = self._conn()
        conn.request('GET', '/')
        resp = conn.getresponse()
        body = resp.read().decode('utf-8')
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn('<label', body)
        self.assertIn('for="url"', body)
        # The status region must be a live region so messages are announced.
        self.assertIn('aria-live', body)

    def test_shorten_and_redirect(self):
        # Create a short URL
        conn = self._conn()
        payload = json.dumps({'url': 'https://example.com/some/long/path'})
        conn.request('POST', '/api/shorten', body=payload,
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        body = json.loads(resp.read().decode('utf-8'))
        self.assertEqual(resp.status, 201)
        self.assertIn('code', body)
        self.assertEqual(body['url'], 'https://example.com/some/long/path')
        code = body['code']
        conn.close()

        # Redirect should be a 301 to the original URL (no auto-follow)
        conn = self._conn()
        conn.request('GET', '/' + code)
        resp = conn.getresponse()
        resp.read()
        self.assertEqual(resp.status, 301)
        self.assertEqual(resp.getheader('Location'), 'https://example.com/some/long/path')
        conn.close()

    def test_shorten_dedup_returns_200(self):
        url = 'https://example.org/page'
        conn = self._conn()
        conn.request('POST', '/api/shorten', body=json.dumps({'url': url}),
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        first = json.loads(resp.read().decode('utf-8'))
        self.assertEqual(resp.status, 201)
        conn.close()

        conn = self._conn()
        conn.request('POST', '/api/shorten', body=json.dumps({'url': url}),
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        second = json.loads(resp.read().decode('utf-8'))
        self.assertEqual(resp.status, 200)
        self.assertEqual(first['code'], second['code'])
        conn.close()

    def test_invalid_url_returns_400(self):
        conn = self._conn()
        conn.request('POST', '/api/shorten', body=json.dumps({'url': 'not-a-url'}),
                     headers={'Content-Type': 'application/json'})
        resp = conn.getresponse()
        body = json.loads(resp.read().decode('utf-8'))
        self.assertEqual(resp.status, 400)
        self.assertIn('error', body)
        conn.close()

    def test_missing_body_returns_400(self):
        conn = self._conn()
        conn.request('POST', '/api/shorten')
        resp = conn.getresponse()
        body = json.loads(resp.read().decode('utf-8'))
        self.assertEqual(resp.status, 400)
        self.assertIn('error', body)
        conn.close()

    def test_unknown_code_returns_404(self):
        conn = self._conn()
        conn.request('GET', '/nonexistentcode')
        resp = conn.getresponse()
        resp.read()
        self.assertEqual(resp.status, 404)
        conn.close()

    def test_list_endpoint(self):
        conn = self._conn()
        conn.request('POST', '/api/shorten', body=json.dumps({'url': 'https://a.com'}),
                     headers={'Content-Type': 'application/json'})
        conn.getresponse().read()
        conn.close()

        conn = self._conn()
        conn.request('GET', '/api/urls')
        resp = conn.getresponse()
        body = json.loads(resp.read().decode('utf-8'))
        self.assertEqual(resp.status, 200)
        self.assertTrue(any(i['url'] == 'https://a.com' for i in body['items']))
        conn.close()


    # === Custom alias ==================================================
    def test_custom_alias_and_redirect(self):
        status, body = self._shorten(url='https://ex.com/p', custom='my-link')
        self.assertEqual(status, 201)
        self.assertEqual(body['code'], 'my-link')
        self.assertTrue(body['custom'])
        status, raw, _ = self._request('GET', '/my-link')
        self.assertEqual(status, 301)

    def test_custom_alias_conflict_returns_409(self):
        self._shorten(url='https://a.com', custom='dup')
        status, body = self._shorten(url='https://b.com', custom='dup')
        self.assertEqual(status, 409)
        self.assertIn('error', body)

    def test_custom_alias_same_url_dedups_200(self):
        s1, b1 = self._shorten(url='https://a.com', custom='keep')
        self.assertEqual(s1, 201)
        s2, b2 = self._shorten(url='https://a.com', custom='keep')
        self.assertEqual(s2, 200)
        self.assertEqual(b1['code'], b2['code'])

    def test_invalid_custom_alias_returns_400(self):
        status, body = self._shorten(url='https://a.com', custom='bad alias!')
        self.assertEqual(status, 400)
        self.assertIn('error', body)

    # === Titles ========================================================
    def test_shorten_with_title(self):
        status, body = self._shorten(url='https://a.com', title='My Home')
        self.assertEqual(status, 201)
        self.assertEqual(body['title'], 'My Home')
        # Title surfaces through stats too.
        status, item = self._json('GET', '/api/stats/' + body['code'])
        self.assertEqual(status, 200)
        self.assertEqual(item['title'], 'My Home')

    def test_title_too_long_returns_400(self):
        status, body = self._shorten(url='https://a.com', title='x' * 201)
        self.assertEqual(status, 400)
        self.assertIn('error', body)

    def test_title_shows_in_list(self):
        self._shorten(url='https://a.com', title='Labelled')
        status, body = self._json('GET', '/api/urls')
        self.assertTrue(any(i.get('title') == 'Labelled' for i in body['items']))

    # === Expiry ========================================================
    def test_expired_link_returns_410(self):
        self._seed({'gone': {'url': 'https://x.com', 'clicks': 0,
                             'created': 1.0, 'expires': 1.0, 'custom': False}})
        status, raw, _ = self._request('GET', '/gone')
        self.assertEqual(status, 410)

    def test_expires_in_must_be_positive_int(self):
        status, body = self._shorten(url='https://a.com', expires_in='soon')
        self.assertEqual(status, 400)
        status, body = self._shorten(url='https://a.com', expires_in=-5)
        self.assertEqual(status, 400)

    def test_future_expiry_still_redirects(self):
        status, body = self._shorten(url='https://a.com', expires_in=10000)
        self.assertEqual(status, 201)
        status, raw, _ = self._request('GET', '/' + body['code'])
        self.assertEqual(status, 301)

    # === Click tracking + reset =======================================
    def test_clicks_increment(self):
        _, body = self._shorten(url='https://a.com')
        code = body['code']
        self._request('GET', '/' + code)
        self._request('GET', '/' + code)
        status, item = self._json('GET', '/api/stats/' + code)
        self.assertEqual(item['clicks'], 2)
        self.assertIsNotNone(item['last_clicked'])

    def test_reset_clicks(self):
        _, body = self._shorten(url='https://a.com')
        code = body['code']
        self._request('GET', '/' + code)
        status, item = self._json('POST', '/api/urls/' + code + '/reset')
        self.assertEqual(status, 200)
        self.assertEqual(item['clicks'], 0)
        self.assertIsNone(item['last_clicked'])

    def test_reset_unknown_returns_404(self):
        status, body = self._json('POST', '/api/urls/nope/reset')
        self.assertEqual(status, 404)

    # === Stats / top / health =========================================
    def test_stats_unknown_returns_404(self):
        status, body = self._json('GET', '/api/stats/missing')
        self.assertEqual(status, 404)

    def test_top_endpoint_orders_by_clicks(self):
        _, a = self._shorten(url='https://a.com')
        _, b = self._shorten(url='https://b.com')
        for _ in range(3):
            self._request('GET', '/' + b['code'])
        self._request('GET', '/' + a['code'])
        status, body = self._json('GET', '/api/top')
        self.assertEqual(status, 200)
        self.assertEqual(body['items'][0]['code'], b['code'])

    def test_top_invalid_limit_returns_400(self):
        status, body = self._json('GET', '/api/top?limit=abc')
        self.assertEqual(status, 400)

    def test_health_endpoint(self):
        self._shorten(url='https://a.com')
        status, body = self._json('GET', '/api/health')
        self.assertEqual(status, 200)
        self.assertEqual(body['status'], 'ok')
        self.assertEqual(body['count'], 1)

    # === Search filter ================================================
    def test_search_filter(self):
        self._shorten(url='https://findme.com')
        self._shorten(url='https://other.com')
        status, body = self._json('GET', '/api/urls?q=findme')
        self.assertEqual(status, 200)
        self.assertTrue(all('findme' in i['url'] for i in body['items']))
        self.assertEqual(len(body['items']), 1)

    # === Delete / patch ===============================================
    def test_delete_url(self):
        _, body = self._shorten(url='https://a.com')
        code = body['code']
        status, b = self._json('DELETE', '/api/urls/' + code)
        self.assertEqual(status, 200)
        self.assertTrue(b['deleted'])
        status, raw, _ = self._request('GET', '/' + code)
        self.assertEqual(status, 404)

    def test_delete_unknown_returns_404(self):
        status, body = self._json('DELETE', '/api/urls/ghost')
        self.assertEqual(status, 404)

    def test_patch_url(self):
        _, body = self._shorten(url='https://old.com')
        code = body['code']
        status, item = self._json('PATCH', '/api/urls/' + code,
                                  {'url': 'https://new.com'})
        self.assertEqual(status, 200)
        self.assertEqual(item['url'], 'https://new.com')
        status, raw, _ = self._request('GET', '/' + code)
        self.assertEqual(status, 301)

    def test_patch_invalid_url_returns_400(self):
        _, body = self._shorten(url='https://old.com')
        status, b = self._json('PATCH', '/api/urls/' + body['code'],
                               {'url': 'nope'})
        self.assertEqual(status, 400)

    def test_patch_unknown_returns_404(self):
        status, b = self._json('PATCH', '/api/urls/ghost',
                               {'url': 'https://x.com'})
        self.assertEqual(status, 404)

    # === Bulk =========================================================
    def test_bulk_shorten(self):
        status, body = self._json('POST', '/api/shorten/bulk',
                                  {'urls': ['https://a.com', 'https://b.com',
                                            'not-a-url']})
        self.assertEqual(status, 200)
        self.assertEqual(body['ok'], 2)
        self.assertEqual(body['failed'], 1)

    def test_bulk_empty_returns_400(self):
        status, body = self._json('POST', '/api/shorten/bulk', {'urls': []})
        self.assertEqual(status, 400)

    def test_bulk_over_limit_returns_400(self):
        status, body = self._json('POST', '/api/shorten/bulk',
                                  {'urls': ['https://a.com'] * 101})
        self.assertEqual(status, 400)

    # === CSV export ===================================================
    def test_export_csv(self):
        self._shorten(url='https://a.com', title='Alpha')
        status, raw, ctype = self._request('GET', '/api/export')
        self.assertEqual(status, 200)
        self.assertIn('text/csv', ctype)
        text = raw.decode('utf-8')
        self.assertIn('code,url,title,clicks', text)
        self.assertIn('https://a.com', text)
        self.assertIn('Alpha', text)

    # === Purge expired ================================================
    def test_purge_expired(self):
        self._seed({
            'old': {'url': 'https://x.com', 'clicks': 0, 'created': 1.0,
                    'expires': 1.0, 'custom': False},
            'live': {'url': 'https://y.com', 'clicks': 0, 'created': 1.0,
                     'expires': None, 'custom': False},
        })
        status, body = self._json('DELETE', '/api/expired')
        self.assertEqual(status, 200)
        self.assertEqual(body['purged'], 1)
        self.assertIn('old', body['codes'])
        status, listing = self._json('GET', '/api/urls')
        codes = [i['code'] for i in listing['items']]
        self.assertNotIn('old', codes)
        self.assertIn('live', codes)

    # === UI wiring ====================================================
    def test_ui_has_title_field(self):
        status, raw, _ = self._request('GET', '/')
        html = raw.decode('utf-8')
        self.assertIn('for="title"', html)
        self.assertIn('id="title"', html)

    def test_ui_has_export_and_purge_buttons(self):
        status, raw, _ = self._request('GET', '/')
        html = raw.decode('utf-8')
        self.assertIn('id="exportBtn"', html)
        self.assertIn('id="purgeBtn"', html)

    def test_ui_sends_optional_fields(self):
        # The form must actually forward alias/expiry/title, not just render them.
        status, raw, _ = self._request('GET', '/')
        html = raw.decode('utf-8')
        self.assertIn('body.custom', html)
        self.assertIn('body.expires_in', html)
        self.assertIn('body.title', html)

    # === Domain-level unit tests (no HTTP) ============================
    def test_encode_base62(self):
        self.assertEqual(server._encode(0), server.ALPHABET[0])
        self.assertEqual(len(server._encode(100000)) >= 1, True)
        # Distinct integers must encode to distinct codes.
        self.assertNotEqual(server._encode(1), server._encode(2))

    def test_is_expired_domain(self):
        rec = {'expires': 100.0}
        self.assertTrue(server._is_expired(rec, now=200.0))
        self.assertFalse(server._is_expired(rec, now=50.0))
        self.assertFalse(server._is_expired({'expires': None}, now=999.0))

    def test_clean_title_domain(self):
        self.assertEqual(server._clean_title(None), ('', None))
        self.assertEqual(server._clean_title('  hi  '), ('hi', None))
        title, err = server._clean_title('x' * 201)
        self.assertIsNotNone(err)

    def test_normalize_legacy_string_record(self):
        rec = server._normalize_record('https://legacy.com')
        self.assertEqual(rec['url'], 'https://legacy.com')
        self.assertEqual(rec['title'], '')
        self.assertEqual(rec['clicks'], 0)

    def test_reserved_codes_not_issued(self):
        # _make_code must skip reserved codes that collide with routes.
        store = {}
        for i in range(200):
            code = server._make_code(store, 'https://u{}.com'.format(i))
            self.assertNotIn(code, server.RESERVED_CODES)
            store[code] = {'url': 'https://u{}.com'.format(i), 'clicks': 0,
                           'created': 0, 'expires': None, 'custom': False}

    # === Max clicks (click-limited links) =============================
    def test_shorten_with_max_clicks(self):
        status, body = self._shorten(url='https://a.com', max_clicks=2)
        self.assertEqual(status, 201)
        self.assertEqual(body['max_clicks'], 2)

    def test_max_clicks_exhausts_after_limit(self):
        _, body = self._shorten(url='https://a.com', max_clicks=2)
        code = body['code']
        # First two clicks redirect, the third is exhausted.
        s1, _, _ = self._request('GET', '/' + code)
        s2, _, _ = self._request('GET', '/' + code)
        s3, _, _ = self._request('GET', '/' + code)
        self.assertEqual(s1, 301)
        self.assertEqual(s2, 301)
        self.assertEqual(s3, 410)
        status, item = self._json('GET', '/api/stats/' + code)
        self.assertTrue(item['exhausted'])
        self.assertEqual(item['clicks'], 2)

    def test_max_clicks_invalid_returns_400(self):
        status, body = self._shorten(url='https://a.com', max_clicks=0)
        self.assertEqual(status, 400)
        status, body = self._shorten(url='https://a.com', max_clicks='lots')
        self.assertEqual(status, 400)

    def test_reset_revives_exhausted_link(self):
        _, body = self._shorten(url='https://a.com', max_clicks=1)
        code = body['code']
        self._request('GET', '/' + code)
        s_exhausted, _, _ = self._request('GET', '/' + code)
        self.assertEqual(s_exhausted, 410)
        # Resetting the counter should let it redirect again.
        self._json('POST', '/api/urls/' + code + '/reset')
        s_after, _, _ = self._request('GET', '/' + code)
        self.assertEqual(s_after, 301)

    # === Tags =========================================================
    def test_shorten_with_tags_list(self):
        status, body = self._shorten(url='https://a.com', tags=['Work', 'Fun'])
        self.assertEqual(status, 201)
        self.assertEqual(body['tags'], ['work', 'fun'])

    def test_shorten_with_tags_csv_string(self):
        status, body = self._shorten(url='https://a.com', tags='alpha, beta, alpha')
        self.assertEqual(status, 201)
        # de-duplicated and lower-cased
        self.assertEqual(body['tags'], ['alpha', 'beta'])

    def test_tag_filter_on_list(self):
        self._shorten(url='https://a.com', tags=['keep'])
        self._shorten(url='https://b.com', tags=['drop'])
        status, body = self._json('GET', '/api/urls?tag=keep')
        self.assertEqual(status, 200)
        self.assertEqual(len(body['items']), 1)
        self.assertEqual(body['items'][0]['url'], 'https://a.com')

    def test_invalid_tag_returns_400(self):
        status, body = self._shorten(url='https://a.com', tags=['ok', 'bad!@#'])
        self.assertEqual(status, 400)
        self.assertIn('error', body)

    # === Enable / disable =============================================
    def test_disable_link_blocks_redirect(self):
        _, body = self._shorten(url='https://a.com')
        code = body['code']
        status, item = self._json('POST', '/api/urls/' + code + '/disable')
        self.assertEqual(status, 200)
        self.assertFalse(item['active'])
        s, _, _ = self._request('GET', '/' + code)
        self.assertEqual(s, 403)

    def test_enable_restores_redirect(self):
        _, body = self._shorten(url='https://a.com')
        code = body['code']
        self._json('POST', '/api/urls/' + code + '/disable')
        status, item = self._json('POST', '/api/urls/' + code + '/enable')
        self.assertEqual(status, 200)
        self.assertTrue(item['active'])
        s, _, _ = self._request('GET', '/' + code)
        self.assertEqual(s, 301)

    def test_disable_unknown_returns_404(self):
        status, body = self._json('POST', '/api/urls/ghost/disable')
        self.assertEqual(status, 404)

    def test_enable_unknown_returns_404(self):
        status, body = self._json('POST', '/api/urls/ghost/enable')
        self.assertEqual(status, 404)

    def test_health_counts_disabled(self):
        _, body = self._shorten(url='https://a.com')
        self._json('POST', '/api/urls/' + body['code'] + '/disable')
        status, health = self._json('GET', '/api/health')
        self.assertEqual(health['disabled'], 1)

    # === Active filter on list ========================================
    def test_active_filter(self):
        _, a = self._shorten(url='https://a.com')
        _, b = self._shorten(url='https://b.com')
        self._json('POST', '/api/urls/' + b['code'] + '/disable')
        status, only_active = self._json('GET', '/api/urls?active=true')
        codes = [i['code'] for i in only_active['items']]
        self.assertIn(a['code'], codes)
        self.assertNotIn(b['code'], codes)
        status, only_disabled = self._json('GET', '/api/urls?active=false')
        codes = [i['code'] for i in only_disabled['items']]
        self.assertIn(b['code'], codes)
        self.assertNotIn(a['code'], codes)

    # === PATCH partial updates ========================================
    def test_patch_title_only(self):
        _, body = self._shorten(url='https://a.com')
        code = body['code']
        status, item = self._json('PATCH', '/api/urls/' + code,
                                  {'title': 'Renamed'})
        self.assertEqual(status, 200)
        self.assertEqual(item['title'], 'Renamed')
        # The url must be untouched.
        self.assertEqual(item['url'], 'https://a.com')

    def test_patch_tags(self):
        _, body = self._shorten(url='https://a.com')
        status, item = self._json('PATCH', '/api/urls/' + body['code'],
                                  {'tags': ['One', 'Two']})
        self.assertEqual(status, 200)
        self.assertEqual(item['tags'], ['one', 'two'])

    def test_patch_max_clicks_and_active(self):
        _, body = self._shorten(url='https://a.com')
        code = body['code']
        status, item = self._json('PATCH', '/api/urls/' + code,
                                  {'max_clicks': 5, 'active': False})
        self.assertEqual(status, 200)
        self.assertEqual(item['max_clicks'], 5)
        self.assertFalse(item['active'])
        s, _, _ = self._request('GET', '/' + code)
        self.assertEqual(s, 403)

    def test_patch_invalid_title_returns_400(self):
        _, body = self._shorten(url='https://a.com')
        status, b = self._json('PATCH', '/api/urls/' + body['code'],
                               {'title': 'x' * 201})
        self.assertEqual(status, 400)

    def test_patch_invalid_max_clicks_returns_400(self):
        _, body = self._shorten(url='https://a.com')
        status, b = self._json('PATCH', '/api/urls/' + body['code'],
                               {'max_clicks': -3})
        self.assertEqual(status, 400)

    # === Export includes new columns ==================================
    def test_export_has_tags_and_active_columns(self):
        self._shorten(url='https://a.com', tags=['x'])
        status, raw, ctype = self._request('GET', '/api/export')
        self.assertEqual(status, 200)
        text = raw.decode('utf-8')
        self.assertIn('active', text.splitlines()[0])
        self.assertIn('max_clicks', text.splitlines()[0])
        self.assertIn('tags', text.splitlines()[0])

    # === Shorten payload exposes new metadata =========================
    def test_shorten_payload_has_new_fields(self):
        status, body = self._shorten(url='https://a.com')
        self.assertIn('tags', body)
        self.assertIn('max_clicks', body)
        self.assertIn('active', body)
        self.assertTrue(body['active'])

    # === UI wiring for new fields =====================================
    def test_ui_has_tags_and_max_clicks_fields(self):
        status, raw, _ = self._request('GET', '/')
        html = raw.decode('utf-8')
        self.assertIn('id="tags"', html)
        self.assertIn('id="maxClicks"', html)
        self.assertIn('body.tags', html)
        self.assertIn('body.max_clicks', html)

    def test_ui_has_disable_enable_wiring(self):
        status, raw, _ = self._request('GET', '/')
        html = raw.decode('utf-8')
        self.assertIn('/disable', html)
        self.assertIn('/enable', html)

    # === Domain-level unit tests for new helpers ======================
    def test_parse_max_clicks_domain(self):
        self.assertEqual(server._parse_max_clicks(None), (None, None))
        self.assertEqual(server._parse_max_clicks(3), (3, None))
        n, err = server._parse_max_clicks(0)
        self.assertIsNotNone(err)

    def test_clean_tags_domain(self):
        tags, err = server._clean_tags('A, b, A')
        self.assertEqual(tags, ['a', 'b'])
        self.assertIsNone(err)
        bad, err = server._clean_tags(['ok', '!!'])
        self.assertIsNotNone(err)

    def test_is_exhausted_domain(self):
        self.assertTrue(server._is_exhausted({'clicks': 5, 'max_clicks': 5}))
        self.assertFalse(server._is_exhausted({'clicks': 1, 'max_clicks': 5}))
        self.assertFalse(server._is_exhausted({'clicks': 9, 'max_clicks': None}))


if __name__ == '__main__':
    unittest.main()
