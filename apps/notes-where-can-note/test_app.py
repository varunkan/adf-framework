import json
import os
import threading
import unittest
import http.client

# Use a temp data file so tests do not clobber real data
os.environ.setdefault('PORT', '0')

import server


class NotesAppTest(unittest.TestCase):
    def setUp(self):
        # isolate data file for tests
        self._orig_data = server.DATA_FILE
        server.DATA_FILE = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'notes_data_test.json'
        )
        if os.path.exists(server.DATA_FILE):
            os.remove(server.DATA_FILE)

        self.server = server.make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if os.path.exists(server.DATA_FILE):
            os.remove(server.DATA_FILE)
        server.DATA_FILE = self._orig_data

    def _conn(self):
        return http.client.HTTPConnection('127.0.0.1', self.port)

    def _create(self, text, tags=None):
        c = self._conn()
        payload = {'text': text}
        if tags is not None:
            payload['tags'] = tags
        c.request('POST', '/api/notes', body=json.dumps(payload),
                  headers={'Content-Type': 'application/json'})
        r = c.getresponse()
        created = json.loads(r.read().decode('utf-8'))
        status = r.status
        c.close()
        return status, created

    def _get(self, path):
        c = self._conn()
        c.request('GET', path)
        r = c.getresponse()
        status = r.status
        body = r.read().decode('utf-8')
        c.close()
        return status, body

    def _get_json(self, path):
        status, body = self._get(path)
        return status, json.loads(body)

    def _req(self, method, path, payload=None):
        c = self._conn()
        body = json.dumps(payload) if payload is not None else None
        headers = {'Content-Type': 'application/json'} if body else {}
        c.request(method, path, body=body, headers=headers)
        r = c.getresponse()
        status = r.status
        raw = r.read().decode('utf-8')
        c.close()
        data = json.loads(raw) if raw else {}
        return status, data

    def test_index_served(self):
        c = self._conn()
        c.request('GET', '/')
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        self.assertIn('text/html', r.getheader('Content-Type'))
        body = r.read().decode('utf-8')
        self.assertIn('<title>Notes</title>', body)
        c.close()

    def test_create_and_list(self):
        c = self._conn()
        payload = json.dumps({'text': 'Buy milk'})
        c.request('POST', '/api/notes', body=payload,
                  headers={'Content-Type': 'application/json'})
        r = c.getresponse()
        self.assertEqual(r.status, 201)
        created = json.loads(r.read().decode('utf-8'))
        self.assertEqual(created['text'], 'Buy milk')
        self.assertIn('id', created)
        c.close()

        c = self._conn()
        c.request('GET', '/api/notes')
        r = c.getresponse()
        self.assertEqual(r.status, 200)
        data = json.loads(r.read().decode('utf-8'))
        self.assertEqual(len(data['notes']), 1)
        self.assertEqual(data['notes'][0]['text'], 'Buy milk')
        c.close()

    def test_empty_text_returns_400(self):
        c = self._conn()
        payload = json.dumps({'text': '   '})
        c.request('POST', '/api/notes', body=payload,
                  headers={'Content-Type': 'application/json'})
        r = c.getresponse()
        self.assertEqual(r.status, 400)
        data = json.loads(r.read().decode('utf-8'))
        self.assertIn('error', data)
        c.close()

    def test_unknown_route_404(self):
        c = self._conn()
        c.request('GET', '/api/does-not-exist')
        r = c.getresponse()
        self.assertEqual(r.status, 404)
        c.close()

    # --- create with tags ----------------------------------------------------

    def test_create_with_tags_normalized(self):
        status, note = self._create('tagged', tags=['Work', 'work', ' HOME '])
        self.assertEqual(status, 201)
        self.assertEqual(note['tags'], ['home', 'work'])

    def test_create_invalid_tags_400(self):
        status, data = self._req('POST', '/api/notes',
                                 {'text': 'x', 'tags': 'notalist'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_create_invalid_json_400(self):
        c = self._conn()
        c.request('POST', '/api/notes', body='{not json',
                  headers={'Content-Type': 'application/json'})
        r = c.getresponse()
        self.assertEqual(r.status, 400)
        c.close()

    # --- get single note -----------------------------------------------------

    def test_get_single_note(self):
        _, created = self._create('fetch me')
        status, note = self._get_json('/api/notes/%d' % created['id'])
        self.assertEqual(status, 200)
        self.assertEqual(note['text'], 'fetch me')

    def test_get_missing_note_404(self):
        status, data = self._get_json('/api/notes/9999')
        self.assertEqual(status, 404)
        self.assertIn('error', data)

    def test_get_bad_id_404(self):
        status, _ = self._get('/api/notes/abc')
        self.assertEqual(status, 404)

    # --- update --------------------------------------------------------------

    def test_update_text(self):
        _, created = self._create('before')
        status, note = self._req('PUT', '/api/notes/%d' % created['id'],
                                 {'text': 'after'})
        self.assertEqual(status, 200)
        self.assertEqual(note['text'], 'after')

    def test_update_pin_and_archive(self):
        _, created = self._create('flag me')
        nid = created['id']
        status, note = self._req('PUT', '/api/notes/%d' % nid, {'pinned': True})
        self.assertEqual(status, 200)
        self.assertTrue(note['pinned'])
        status, note = self._req('PUT', '/api/notes/%d' % nid, {'archived': True})
        self.assertTrue(note['archived'])

    def test_update_empty_text_400(self):
        _, created = self._create('keep')
        status, data = self._req('PUT', '/api/notes/%d' % created['id'],
                                 {'text': '   '})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_update_no_fields_400(self):
        _, created = self._create('keep')
        status, data = self._req('PUT', '/api/notes/%d' % created['id'],
                                 {'irrelevant': 1})
        self.assertEqual(status, 400)

    def test_update_missing_note_404(self):
        status, data = self._req('PUT', '/api/notes/9999', {'text': 'x'})
        self.assertEqual(status, 404)

    # --- delete --------------------------------------------------------------

    def test_delete_note(self):
        _, created = self._create('delete me')
        status, data = self._req('DELETE', '/api/notes/%d' % created['id'])
        self.assertEqual(status, 200)
        self.assertEqual(data['deleted'], created['id'])
        status, _ = self._get_json('/api/notes/%d' % created['id'])
        self.assertEqual(status, 404)

    def test_delete_missing_404(self):
        status, _ = self._req('DELETE', '/api/notes/9999')
        self.assertEqual(status, 404)

    # --- search / filter -----------------------------------------------------

    def test_search_filters_list(self):
        self._create('buy milk')
        self._create('call dentist')
        status, data = self._get_json('/api/notes?q=milk')
        self.assertEqual(status, 200)
        self.assertEqual([n['text'] for n in data['notes']], ['buy milk'])

    def test_filter_by_tag(self):
        self._create('a', tags=['work'])
        self._create('b', tags=['home'])
        status, data = self._get_json('/api/notes?tag=work')
        self.assertEqual([n['text'] for n in data['notes']], ['a'])

    def test_archived_filter_modes(self):
        _, a = self._create('active note')
        _, b = self._create('archived note')
        self._req('PUT', '/api/notes/%d' % b['id'], {'archived': True})
        # default excludes archived
        _, active = self._get_json('/api/notes')
        self.assertEqual([n['text'] for n in active['notes']], ['active note'])
        # archived-only
        _, only = self._get_json('/api/notes?archived=only')
        self.assertEqual([n['text'] for n in only['notes']], ['archived note'])
        # all
        _, every = self._get_json('/api/notes?archived=all')
        self.assertEqual(len(every['notes']), 2)

    def test_pinned_sorts_first(self):
        _, a = self._create('first')
        _, b = self._create('second')
        self._req('PUT', '/api/notes/%d' % a['id'], {'pinned': True})
        _, data = self._get_json('/api/notes')
        self.assertEqual(data['notes'][0]['text'], 'first')

    # --- tags / stats endpoints ----------------------------------------------

    def test_tags_endpoint(self):
        self._create('a', tags=['work', 'urgent'])
        self._create('b', tags=['work'])
        status, data = self._get_json('/api/tags')
        self.assertEqual(status, 200)
        self.assertEqual(data['tags'], [{'tag': 'urgent', 'count': 1},
                                        {'tag': 'work', 'count': 2}])

    def test_stats_endpoint(self):
        self._create('one two', tags=['x'])
        status, data = self._get_json('/api/stats')
        self.assertEqual(status, 200)
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['words'], 2)
        self.assertEqual(data['tags'], 1)

    # --- duplicate -----------------------------------------------------------

    def test_duplicate_note(self):
        _, created = self._create('clone source', tags=['t'])
        status, copy = self._req('POST', '/api/notes/%d/duplicate' % created['id'])
        self.assertEqual(status, 201)
        self.assertNotEqual(copy['id'], created['id'])
        self.assertEqual(copy['text'], 'clone source')
        self.assertEqual(copy['tags'], ['t'])
        _, data = self._get_json('/api/notes')
        self.assertEqual(len(data['notes']), 2)

    def test_duplicate_missing_404(self):
        status, _ = self._req('POST', '/api/notes/9999/duplicate')
        self.assertEqual(status, 404)

    # --- export --------------------------------------------------------------

    def test_export_bundle(self):
        self._create('one')
        self._create('two')
        status, data = self._get_json('/api/export')
        self.assertEqual(status, 200)
        self.assertEqual(data['count'], 2)
        self.assertEqual(data['version'], 1)
        self.assertIn('exported_at', data)
        self.assertEqual(len(data['notes']), 2)

    # --- colors --------------------------------------------------------------

    def test_colors_endpoint(self):
        status, data = self._get_json('/api/colors')
        self.assertEqual(status, 200)
        self.assertIn('default', data['colors'])
        self.assertIn('red', data['colors'])

    def test_create_with_color(self):
        status, note = self._req('POST', '/api/notes',
                                 {'text': 'colorful', 'color': 'Green'})
        self.assertEqual(status, 201)
        self.assertEqual(note['color'], 'green')

    def test_create_default_color(self):
        _, note = self._create('plain')
        self.assertEqual(note['color'], 'default')

    def test_create_bad_color_400(self):
        status, data = self._req('POST', '/api/notes',
                                 {'text': 'x', 'color': 'neon'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_update_color_only(self):
        _, created = self._create('recolor')
        status, note = self._req('PUT', '/api/notes/%d' % created['id'],
                                 {'color': 'blue'})
        self.assertEqual(status, 200)
        self.assertEqual(note['color'], 'blue')

    # --- tag rename ----------------------------------------------------------

    def test_rename_tag_endpoint(self):
        self._create('a', tags=['work'])
        self._create('b', tags=['work', 'urgent'])
        status, data = self._req('POST', '/api/tags/rename',
                                 {'old': 'work', 'new': 'office'})
        self.assertEqual(status, 200)
        self.assertEqual(data['renamed'], 2)
        _, tags = self._get_json('/api/tags')
        names = [t['tag'] for t in tags['tags']]
        self.assertIn('office', names)
        self.assertNotIn('work', names)

    def test_rename_tag_remove(self):
        self._create('a', tags=['drop'])
        status, data = self._req('POST', '/api/tags/rename',
                                 {'old': 'drop', 'new': ''})
        self.assertEqual(status, 200)
        self.assertEqual(data['renamed'], 1)
        _, tags = self._get_json('/api/tags')
        self.assertEqual(tags['tags'], [])

    def test_rename_tag_missing_old_400(self):
        status, data = self._req('POST', '/api/tags/rename',
                                 {'old': '', 'new': 'x'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    # --- import --------------------------------------------------------------

    def test_import_bundle(self):
        self._create('existing')
        bundle = {
            'version': 1,
            'notes': [
                {'text': 'imported one', 'tags': ['t'], 'color': 'red'},
                {'text': 'imported two'},
            ],
        }
        status, data = self._req('POST', '/api/import', bundle)
        self.assertEqual(status, 201)
        self.assertEqual(data['imported'], 2)
        self.assertEqual(data['total'], 3)
        _, listing = self._get_json('/api/notes')
        texts = sorted(n['text'] for n in listing['notes'])
        self.assertEqual(texts, ['existing', 'imported one', 'imported two'])

    def test_export_import_round_trip(self):
        _, created = self._create('round trip', tags=['x'])
        self._req('PUT', '/api/notes/%d' % created['id'], {'color': 'purple'})
        _, bundle = self._get_json('/api/export')
        # wipe and re-import into an empty collection
        self._req('DELETE', '/api/notes/%d' % created['id'])
        status, data = self._req('POST', '/api/import', bundle)
        self.assertEqual(status, 201)
        self.assertEqual(data['imported'], 1)
        _, listing = self._get_json('/api/notes')
        self.assertEqual(listing['notes'][0]['text'], 'round trip')
        self.assertEqual(listing['notes'][0]['color'], 'purple')

    def test_import_assigns_fresh_ids(self):
        _, created = self._create('seed')
        bundle = {'notes': [{'text': 'collide', 'id': created['id']}]}
        status, _ = self._req('POST', '/api/import', bundle)
        self.assertEqual(status, 201)
        _, listing = self._get_json('/api/notes')
        ids = [n['id'] for n in listing['notes']]
        self.assertEqual(len(ids), len(set(ids)))  # no duplicate ids

    def test_import_invalid_bundle_400(self):
        status, data = self._req('POST', '/api/import', {'version': 1})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_import_bad_note_400(self):
        status, _ = self._req('POST', '/api/import',
                              {'notes': [{'text': '   '}]})
        self.assertEqual(status, 400)

    # --- persistence ---------------------------------------------------------

    def test_notes_persist_across_loads(self):
        self._create('durable')
        notes, next_id = server._load_notes()
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]['text'], 'durable')
        self.assertGreater(next_id, 1)


if __name__ == '__main__':
    unittest.main()
