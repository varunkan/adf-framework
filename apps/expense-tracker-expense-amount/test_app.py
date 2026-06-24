import os
import json
import threading
import unittest
import http.client

import server


class ExpenseAPITest(unittest.TestCase):
    def setUp(self):
        # isolate data + budget files so tests never touch real data
        self.data_file = os.path.join(server.BASE_DIR, 'expenses_test.json')
        self.budget_file = os.path.join(server.BASE_DIR, 'budget_test.json')
        self.cat_budget_file = os.path.join(server.BASE_DIR, 'category_budgets_test.json')
        server.DATA_FILE = self.data_file
        server.BUDGET_FILE = self.budget_file
        server.CAT_BUDGET_FILE = self.cat_budget_file
        for f in (self.data_file, self.budget_file, self.cat_budget_file):
            if os.path.exists(f):
                os.remove(f)

        self.server = server.make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        for f in (self.data_file, self.budget_file, self.cat_budget_file):
            if os.path.exists(f):
                os.remove(f)

    def _conn(self):
        return http.client.HTTPConnection('127.0.0.1', self.port)

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
        conn.close()
        parsed = None
        if raw:
            try:
                parsed = json.loads(raw.decode('utf-8'))
            except ValueError:
                parsed = None
        return resp.status, parsed

    def test_index_served(self):
        conn = self._conn()
        conn.request('GET', '/')
        resp = conn.getresponse()
        body = resp.read().decode('utf-8')
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn('Expense Tracker', body)

    def test_create_and_read_back(self):
        status, data = self._request('POST', '/api/expenses', {
            'amount': 12.5,
            'category': 'Food',
            'date': '2024-01-15',
            'note': 'Lunch'
        })
        self.assertEqual(status, 201)
        self.assertEqual(data['category'], 'Food')
        self.assertEqual(data['amount'], 12.5)
        self.assertIn('id', data)
        eid = data['id']

        status, listing = self._request('GET', '/api/expenses')
        self.assertEqual(status, 200)
        self.assertEqual(len(listing['expenses']), 1)
        self.assertEqual(listing['total'], 12.5)
        self.assertEqual(listing['breakdown']['Food'], 12.5)
        self.assertEqual(listing['breakdown']['Bills'], 0.0)

        # delete it
        status, _ = self._request('DELETE', '/api/expenses/' + eid)
        self.assertEqual(status, 200)
        status, listing = self._request('GET', '/api/expenses')
        self.assertEqual(len(listing['expenses']), 0)
        self.assertEqual(listing['total'], 0)

    def test_total_and_breakdown_multiple(self):
        self._request('POST', '/api/expenses', {'amount': 10, 'category': 'Food', 'date': '2024-01-01'})
        self._request('POST', '/api/expenses', {'amount': 5, 'category': 'Food', 'date': '2024-01-02'})
        self._request('POST', '/api/expenses', {'amount': 20, 'category': 'Bills', 'date': '2024-01-03'})
        status, listing = self._request('GET', '/api/expenses')
        self.assertEqual(status, 200)
        self.assertEqual(listing['total'], 35.0)
        self.assertEqual(listing['breakdown']['Food'], 15.0)
        self.assertEqual(listing['breakdown']['Bills'], 20.0)

    def test_persistence_across_restart(self):
        self._request('POST', '/api/expenses', {'amount': 7, 'category': 'Fun', 'date': '2024-02-02'})
        # raw file should contain it
        with open(self.data_file) as f:
            saved = json.load(f)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['category'], 'Fun')

    def test_invalid_amount_returns_400(self):
        status, data = self._request('POST', '/api/expenses', {
            'amount': -5, 'category': 'Food', 'date': '2024-01-15'
        })
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_invalid_category_returns_400(self):
        status, data = self._request('POST', '/api/expenses', {
            'amount': 5, 'category': 'Nope', 'date': '2024-01-15'
        })
        self.assertEqual(status, 400)

    def test_invalid_date_returns_400(self):
        status, data = self._request('POST', '/api/expenses', {
            'amount': 5, 'category': 'Food', 'date': 'not-a-date'
        })
        self.assertEqual(status, 400)

    def test_delete_missing_returns_404(self):
        status, data = self._request('DELETE', '/api/expenses/doesnotexist')
        self.assertEqual(status, 404)
        self.assertIn('error', data)

    def test_unknown_route_returns_404(self):
        status, _ = self._request('GET', '/api/unknown')
        self.assertEqual(status, 404)

    # ---- editing (PUT /api/expenses/<id>) ----

    def _make(self, **over):
        body = {'amount': 10, 'category': 'Food', 'date': '2024-01-01', 'note': ''}
        body.update(over)
        status, data = self._request('POST', '/api/expenses', body)
        self.assertEqual(status, 201)
        return data

    def test_edit_amount_and_category(self):
        e = self._make(amount=10, category='Food')
        status, updated = self._request('PUT', '/api/expenses/' + e['id'],
                                        {'amount': 25.5, 'category': 'Bills'})
        self.assertEqual(status, 200)
        self.assertEqual(updated['amount'], 25.5)
        self.assertEqual(updated['category'], 'Bills')
        # persisted + reflected in totals
        _, listing = self._request('GET', '/api/expenses')
        self.assertEqual(listing['total'], 25.5)
        self.assertEqual(listing['breakdown']['Bills'], 25.5)
        self.assertEqual(listing['breakdown']['Food'], 0.0)

    def test_edit_partial_keeps_other_fields(self):
        e = self._make(amount=10, category='Fun', note='movie', date='2024-03-03')
        status, updated = self._request('PUT', '/api/expenses/' + e['id'], {'amount': 12})
        self.assertEqual(status, 200)
        self.assertEqual(updated['amount'], 12)
        self.assertEqual(updated['category'], 'Fun')
        self.assertEqual(updated['note'], 'movie')
        self.assertEqual(updated['date'], '2024-03-03')

    def test_edit_invalid_amount_returns_400(self):
        e = self._make()
        status, data = self._request('PUT', '/api/expenses/' + e['id'], {'amount': -3})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_edit_missing_returns_404(self):
        status, data = self._request('PUT', '/api/expenses/nope', {'amount': 5})
        self.assertEqual(status, 404)
        self.assertIn('error', data)

    # ---- count / average in summary ----

    def test_count_and_average(self):
        self._make(amount=10)
        self._make(amount=20)
        self._make(amount=30)
        _, listing = self._request('GET', '/api/expenses')
        self.assertEqual(listing['count'], 3)
        self.assertEqual(listing['total'], 60.0)
        self.assertEqual(listing['average'], 20.0)

    def test_average_zero_when_empty(self):
        _, listing = self._request('GET', '/api/expenses')
        self.assertEqual(listing['count'], 0)
        self.assertEqual(listing['average'], 0.0)

    # ---- category + date-range filtering on the server ----

    def test_category_query_filter(self):
        self._make(amount=10, category='Food')
        self._make(amount=5, category='Bills')
        _, listing = self._request('GET', '/api/expenses?category=Food')
        self.assertEqual(listing['count'], 1)
        self.assertEqual(listing['total'], 10.0)
        self.assertEqual(listing['expenses'][0]['category'], 'Food')

    def test_date_range_filter(self):
        self._make(amount=10, date='2024-01-01')
        self._make(amount=20, date='2024-02-15')
        self._make(amount=30, date='2024-03-20')
        _, listing = self._request('GET', '/api/expenses?start=2024-02-01&end=2024-02-28')
        self.assertEqual(listing['count'], 1)
        self.assertEqual(listing['total'], 20.0)

    def test_invalid_category_filter_returns_400(self):
        status, data = self._request('GET', '/api/expenses?category=Nope')
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_invalid_start_date_filter_returns_400(self):
        status, data = self._request('GET', '/api/expenses?start=bad')
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_invalid_end_date_filter_returns_400(self):
        status, data = self._request('GET', '/api/expenses?end=2024-13-99')
        self.assertEqual(status, 400)

    # ---- budget (GET/PUT /api/budget) ----

    def test_budget_defaults_to_null(self):
        status, data = self._request('GET', '/api/budget')
        self.assertEqual(status, 200)
        self.assertIsNone(data['budget'])

    def test_set_and_get_budget(self):
        status, data = self._request('PUT', '/api/budget', {'budget': 500})
        self.assertEqual(status, 200)
        self.assertEqual(data['budget'], 500.0)
        _, got = self._request('GET', '/api/budget')
        self.assertEqual(got['budget'], 500.0)

    def test_budget_status_in_summary(self):
        self._request('PUT', '/api/budget', {'budget': 100})
        self._make(amount=40)
        _, listing = self._request('GET', '/api/expenses')
        self.assertEqual(listing['budget'], 100.0)
        self.assertEqual(listing['remaining'], 60.0)
        self.assertFalse(listing['over_budget'])

    def test_budget_overspend_flagged(self):
        self._request('PUT', '/api/budget', {'budget': 50})
        self._make(amount=80)
        _, listing = self._request('GET', '/api/expenses')
        self.assertTrue(listing['over_budget'])
        self.assertEqual(listing['remaining'], -30.0)

    def test_clear_budget(self):
        self._request('PUT', '/api/budget', {'budget': 200})
        status, data = self._request('PUT', '/api/budget', {'budget': None})
        self.assertEqual(status, 200)
        self.assertIsNone(data['budget'])
        _, listing = self._request('GET', '/api/expenses')
        self.assertIsNone(listing['budget'])
        self.assertFalse(listing['over_budget'])

    def test_negative_budget_returns_400(self):
        status, data = self._request('PUT', '/api/budget', {'budget': -10})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_non_numeric_budget_returns_400(self):
        status, data = self._request('PUT', '/api/budget', {'budget': 'lots'})
        self.assertEqual(status, 400)

    # ---- monthly breakdown ----

    def test_monthly_breakdown_endpoint(self):
        self._make(amount=10, date='2024-01-05')
        self._make(amount=5, date='2024-01-25')
        self._make(amount=20, date='2024-02-10')
        status, data = self._request('GET', '/api/summary/monthly')
        self.assertEqual(status, 200)
        self.assertEqual(data['monthly']['2024-01'], 15.0)
        self.assertEqual(data['monthly']['2024-02'], 20.0)

    # ---- note search (q=) ----

    def test_note_search_filters_by_substring(self):
        self._make(amount=10, note='Lunch with Sam')
        self._make(amount=20, note='Taxi home')
        self._make(amount=5, note='lunchbox')
        _, listing = self._request('GET', '/api/expenses?q=lunch')
        self.assertEqual(listing['count'], 2)
        self.assertEqual(listing['total'], 15.0)

    def test_note_search_is_case_insensitive(self):
        self._make(amount=8, note='Coffee Beans')
        _, listing = self._request('GET', '/api/expenses?q=COFFEE')
        self.assertEqual(listing['count'], 1)

    def test_note_search_no_match_returns_empty(self):
        self._make(amount=8, note='Coffee')
        _, listing = self._request('GET', '/api/expenses?q=zzz')
        self.assertEqual(listing['count'], 0)
        self.assertEqual(listing['total'], 0.0)

    def test_note_search_combines_with_category(self):
        self._make(amount=10, category='Food', note='lunch')
        self._make(amount=20, category='Bills', note='lunch')
        _, listing = self._request('GET', '/api/expenses?q=lunch&category=Food')
        self.assertEqual(listing['count'], 1)
        self.assertEqual(listing['expenses'][0]['category'], 'Food')

    # ---- server-side sorting (sort=, order=) ----

    def test_sort_by_amount_ascending(self):
        self._make(amount=30, note='c')
        self._make(amount=10, note='a')
        self._make(amount=20, note='b')
        _, listing = self._request('GET', '/api/expenses?sort=amount&order=asc')
        amounts = [e['amount'] for e in listing['expenses']]
        self.assertEqual(amounts, [10.0, 20.0, 30.0])

    def test_sort_by_amount_descending(self):
        self._make(amount=30)
        self._make(amount=10)
        self._make(amount=20)
        _, listing = self._request('GET', '/api/expenses?sort=amount&order=desc')
        amounts = [e['amount'] for e in listing['expenses']]
        self.assertEqual(amounts, [30.0, 20.0, 10.0])

    def test_sort_by_date_ascending(self):
        self._make(amount=1, date='2024-03-01')
        self._make(amount=1, date='2024-01-01')
        self._make(amount=1, date='2024-02-01')
        _, listing = self._request('GET', '/api/expenses?sort=date&order=asc')
        dates = [e['date'] for e in listing['expenses']]
        self.assertEqual(dates, ['2024-01-01', '2024-02-01', '2024-03-01'])

    def test_default_order_is_ascending(self):
        self._make(amount=30)
        self._make(amount=10)
        _, listing = self._request('GET', '/api/expenses?sort=amount')
        amounts = [e['amount'] for e in listing['expenses']]
        self.assertEqual(amounts, [10.0, 30.0])

    def test_invalid_sort_field_returns_400(self):
        status, data = self._request('GET', '/api/expenses?sort=bogus')
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_invalid_sort_order_returns_400(self):
        status, data = self._request('GET', '/api/expenses?sort=amount&order=sideways')
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    # ---- summary enrichment: top_category + largest ----

    def test_top_category_in_summary(self):
        self._make(amount=10, category='Food')
        self._make(amount=50, category='Bills')
        self._make(amount=5, category='Food')
        _, listing = self._request('GET', '/api/expenses')
        self.assertEqual(listing['top_category'], 'Bills')

    def test_top_category_none_when_empty(self):
        _, listing = self._request('GET', '/api/expenses')
        self.assertIsNone(listing['top_category'])

    def test_largest_expense_in_summary(self):
        self._make(amount=10, note='small')
        self._make(amount=99, note='big')
        _, listing = self._request('GET', '/api/expenses')
        self.assertEqual(listing['largest']['amount'], 99.0)
        self.assertEqual(listing['largest']['note'], 'big')

    def test_largest_none_when_empty(self):
        _, listing = self._request('GET', '/api/expenses')
        self.assertIsNone(listing['largest'])

    # ---- CSV export ----

    def test_csv_export(self):
        e = self._make(amount=12.5, category='Food', note='Lunch', date='2024-01-01')
        conn = self._conn()
        conn.request('GET', '/api/expenses.csv')
        resp = conn.getresponse()
        body = resp.read().decode('utf-8')
        ctype = resp.getheader('Content-Type')
        disp = resp.getheader('Content-Disposition')
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn('text/csv', ctype)
        self.assertIn('attachment', disp)
        self.assertIn('id,date,category,amount,note', body)
        self.assertIn('Food', body)
        self.assertIn(e['id'], body)

    # ---- tags ----

    def test_create_with_tags(self):
        status, data = self._request('POST', '/api/expenses', {
            'amount': 10, 'category': 'Food', 'date': '2024-01-01',
            'tags': ['work', 'reimbursable'],
        })
        self.assertEqual(status, 201)
        self.assertEqual(data['tags'], ['work', 'reimbursable'])

    def test_create_without_tags_defaults_empty(self):
        status, data = self._request('POST', '/api/expenses', {
            'amount': 10, 'category': 'Food', 'date': '2024-01-01',
        })
        self.assertEqual(status, 201)
        self.assertEqual(data['tags'], [])

    def test_tags_normalized_strip_dedupe_drop_empty(self):
        status, data = self._request('POST', '/api/expenses', {
            'amount': 10, 'category': 'Food', 'date': '2024-01-01',
            'tags': ['  work  ', 'Work', '', '   ', 'travel'],
        })
        self.assertEqual(status, 201)
        # 'work' kept once (first spelling), blanks dropped, 'travel' kept
        self.assertEqual(data['tags'], ['work', 'travel'])

    def test_tags_must_be_a_list(self):
        status, data = self._request('POST', '/api/expenses', {
            'amount': 10, 'category': 'Food', 'date': '2024-01-01',
            'tags': 'work',
        })
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_tags_elements_must_be_strings(self):
        status, data = self._request('POST', '/api/expenses', {
            'amount': 10, 'category': 'Food', 'date': '2024-01-01',
            'tags': ['work', 5],
        })
        self.assertEqual(status, 400)

    def test_too_many_tags_returns_400(self):
        status, data = self._request('POST', '/api/expenses', {
            'amount': 10, 'category': 'Food', 'date': '2024-01-01',
            'tags': ['t%d' % i for i in range(11)],
        })
        self.assertEqual(status, 400)

    def test_filter_by_tag(self):
        self._make(amount=10, tags=['work'])
        self._make(amount=20, tags=['personal'])
        _, listing = self._request('GET', '/api/expenses?tag=work')
        self.assertEqual(listing['count'], 1)
        self.assertEqual(listing['total'], 10.0)

    def test_filter_by_tag_case_insensitive(self):
        self._make(amount=8, tags=['Groceries'])
        _, listing = self._request('GET', '/api/expenses?tag=groceries')
        self.assertEqual(listing['count'], 1)

    def test_edit_updates_tags(self):
        e = self._make(amount=10, tags=['old'])
        status, updated = self._request('PUT', '/api/expenses/' + e['id'],
                                        {'tags': ['new', 'fresh']})
        self.assertEqual(status, 200)
        self.assertEqual(updated['tags'], ['new', 'fresh'])

    def test_edit_without_tags_keeps_existing(self):
        e = self._make(amount=10, tags=['keepme'])
        status, updated = self._request('PUT', '/api/expenses/' + e['id'],
                                        {'amount': 12})
        self.assertEqual(status, 200)
        self.assertEqual(updated['tags'], ['keepme'])

    def test_tag_breakdown_endpoint(self):
        self._make(amount=10, tags=['work'])
        self._make(amount=30, tags=['work', 'travel'])
        self._make(amount=5, tags=['fun'])
        status, data = self._request('GET', '/api/summary/tags')
        self.assertEqual(status, 200)
        tags = data['tags']
        self.assertEqual(tags['work'], 40.0)
        self.assertEqual(tags['travel'], 30.0)
        self.assertEqual(tags['fun'], 5.0)
        # sorted by spend desc -> work first
        self.assertEqual(list(tags.keys())[0], 'work')

    # ---- per-category budgets ----

    def test_category_budgets_default_empty(self):
        status, data = self._request('GET', '/api/budgets/categories')
        self.assertEqual(status, 200)
        self.assertEqual(data['categories'], {})

    def test_set_category_budget(self):
        status, data = self._request('PUT', '/api/budgets/categories',
                                     {'category': 'Food', 'budget': 200})
        self.assertEqual(status, 200)
        self.assertEqual(data['categories']['Food'], 200.0)
        _, got = self._request('GET', '/api/budgets/categories')
        self.assertEqual(got['categories']['Food'], 200.0)

    def test_clear_category_budget(self):
        self._request('PUT', '/api/budgets/categories', {'category': 'Food', 'budget': 200})
        status, data = self._request('PUT', '/api/budgets/categories',
                                     {'category': 'Food', 'budget': None})
        self.assertEqual(status, 200)
        self.assertNotIn('Food', data['categories'])

    def test_category_budget_invalid_category_returns_400(self):
        status, data = self._request('PUT', '/api/budgets/categories',
                                     {'category': 'Nope', 'budget': 10})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_category_budget_negative_returns_400(self):
        status, data = self._request('PUT', '/api/budgets/categories',
                                     {'category': 'Food', 'budget': -1})
        self.assertEqual(status, 400)

    def test_category_budget_status_in_summary(self):
        self._request('PUT', '/api/budgets/categories', {'category': 'Food', 'budget': 50})
        self._make(amount=80, category='Food')
        _, listing = self._request('GET', '/api/expenses')
        cb = listing['category_budgets']['Food']
        self.assertEqual(cb['budget'], 50.0)
        self.assertEqual(cb['spent'], 80.0)
        self.assertEqual(cb['remaining'], -30.0)
        self.assertTrue(cb['over_budget'])

    # ---- spending forecast ----

    def test_forecast_endpoint_projects_month_end(self):
        # $100 spent over the first 10 days of a 31-day month -> ~$310 projected.
        self._make(amount=100, date='2024-01-05')
        status, data = self._request('GET', '/api/summary/forecast?asof=2024-01-10')
        self.assertEqual(status, 200)
        fc = data['forecast']
        self.assertEqual(fc['spent'], 100.0)
        self.assertEqual(fc['days_elapsed'], 10)
        self.assertEqual(fc['days_in_month'], 31)
        self.assertEqual(fc['avg_daily'], 10.0)
        self.assertEqual(fc['projected'], 310.0)

    def test_forecast_only_counts_current_month(self):
        self._make(amount=50, date='2024-01-10')
        self._make(amount=999, date='2024-02-01')
        _, data = self._request('GET', '/api/summary/forecast?asof=2024-01-10')
        self.assertEqual(data['forecast']['spent'], 50.0)

    def test_forecast_missing_asof_returns_400(self):
        status, data = self._request('GET', '/api/summary/forecast')
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_forecast_invalid_asof_returns_400(self):
        status, data = self._request('GET', '/api/summary/forecast?asof=nope')
        self.assertEqual(status, 400)

    # ---- CSV import (POST /api/expenses/import) ----

    def test_import_valid_rows(self):
        csv_text = (
            'date,category,amount,note\n'
            '2024-01-01,Food,12.50,Lunch\n'
            '2024-01-02,Transport,5,Bus\n'
        )
        status, data = self._request('POST', '/api/expenses/import', {'csv': csv_text})
        self.assertEqual(status, 200)
        self.assertEqual(data['imported'], 2)
        self.assertEqual(data['skipped'], 0)
        self.assertEqual(data['errors'], [])
        # each imported row got a fresh id and is persisted/listed
        self.assertTrue(all(e.get('id') for e in data['expenses']))
        _, listing = self._request('GET', '/api/expenses')
        self.assertEqual(listing['count'], 2)
        self.assertEqual(listing['total'], 17.5)
        self.assertEqual(listing['breakdown']['Food'], 12.5)
        self.assertEqual(listing['breakdown']['Transport'], 5.0)

    def test_import_skips_invalid_rows_keeps_good(self):
        csv_text = (
            'date,category,amount,note\n'
            '2024-01-01,Food,10,ok\n'
            '2024-01-02,Nope,5,bad-category\n'
            'bad-date,Food,7,bad-date\n'
            '2024-01-03,Food,-3,bad-amount\n'
            '2024-01-04,Bills,20,ok2\n'
        )
        status, data = self._request('POST', '/api/expenses/import', {'csv': csv_text})
        self.assertEqual(status, 200)
        self.assertEqual(data['imported'], 2)
        self.assertEqual(data['skipped'], 3)
        # errors carry the 1-based data-row number
        rows = [e['row'] for e in data['errors']]
        self.assertEqual(rows, [2, 3, 4])
        _, listing = self._request('GET', '/api/expenses')
        self.assertEqual(listing['count'], 2)
        self.assertEqual(listing['total'], 30.0)

    def test_import_with_tags_column(self):
        csv_text = (
            'date,category,amount,note,tags\n'
            '2024-01-01,Food,10,Lunch,work;reimbursable\n'
        )
        status, data = self._request('POST', '/api/expenses/import', {'csv': csv_text})
        self.assertEqual(status, 200)
        self.assertEqual(data['imported'], 1)
        self.assertEqual(data['expenses'][0]['tags'], ['work', 'reimbursable'])

    def test_import_headers_case_insensitive_and_id_ignored(self):
        # the export writes id,date,category,amount,note — re-importing it works
        # and the original id is dropped in favour of a fresh one.
        csv_text = (
            'id,Date,CATEGORY,Amount,Note\n'
            'oldid123,2024-01-01,Food,9,Snack\n'
        )
        status, data = self._request('POST', '/api/expenses/import', {'csv': csv_text})
        self.assertEqual(status, 200)
        self.assertEqual(data['imported'], 1)
        self.assertNotEqual(data['expenses'][0]['id'], 'oldid123')
        self.assertEqual(data['expenses'][0]['note'], 'Snack')

    def test_import_roundtrips_export(self):
        # export -> import should reproduce the same totals
        self._make(amount=12.5, category='Food', note='Lunch', date='2024-01-01')
        self._make(amount=8, category='Bills', note='Water', date='2024-01-02')
        conn = self._conn()
        conn.request('GET', '/api/expenses.csv')
        resp = conn.getresponse()
        exported = resp.read().decode('utf-8')
        conn.close()
        status, data = self._request('POST', '/api/expenses/import', {'csv': exported})
        self.assertEqual(status, 200)
        self.assertEqual(data['imported'], 2)
        _, listing = self._request('GET', '/api/expenses')
        # original 2 + imported 2
        self.assertEqual(listing['count'], 4)
        self.assertEqual(listing['total'], 41.0)

    def test_import_empty_csv_imports_nothing(self):
        status, data = self._request('POST', '/api/expenses/import', {'csv': ''})
        self.assertEqual(status, 200)
        self.assertEqual(data['imported'], 0)
        self.assertEqual(data['skipped'], 0)

    def test_import_missing_csv_field_returns_400(self):
        status, data = self._request('POST', '/api/expenses/import', {})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_import_non_string_csv_returns_400(self):
        status, data = self._request('POST', '/api/expenses/import', {'csv': 123})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_import_does_not_persist_when_all_invalid(self):
        csv_text = 'date,category,amount,note\nbad,Nope,-1,x\n'
        status, data = self._request('POST', '/api/expenses/import', {'csv': csv_text})
        self.assertEqual(status, 200)
        self.assertEqual(data['imported'], 0)
        self.assertEqual(data['skipped'], 1)
        # no data file should have been written for an all-invalid import
        self.assertFalse(os.path.exists(self.data_file))


class DomainTest(unittest.TestCase):
    """Unit tests for the pure domain helpers (no server/socket)."""

    def test_monthly_breakdown_groups_and_sorts(self):
        out = server._monthly_breakdown([
            {'amount': 3, 'date': '2024-02-01'},
            {'amount': 10, 'date': '2024-01-05'},
            {'amount': 5, 'date': '2024-01-20'},
        ])
        self.assertEqual(list(out.keys()), ['2024-01', '2024-02'])
        self.assertEqual(out['2024-01'], 15.0)
        self.assertEqual(out['2024-02'], 3.0)

    def test_monthly_breakdown_skips_bad_dates(self):
        out = server._monthly_breakdown([{'amount': 5, 'date': ''}])
        self.assertEqual(out, {})

    def test_budget_status_none(self):
        s = server._budget_status(50, None)
        self.assertIsNone(s['budget'])
        self.assertIsNone(s['remaining'])
        self.assertFalse(s['over_budget'])

    def test_budget_status_over(self):
        s = server._budget_status(120, 100)
        self.assertTrue(s['over_budget'])
        self.assertEqual(s['remaining'], -20.0)

    def test_budget_status_under(self):
        s = server._budget_status(40, 100)
        self.assertFalse(s['over_budget'])
        self.assertEqual(s['remaining'], 60.0)

    def test_csv_quotes_embedded_commas(self):
        out = server._expenses_csv([
            {'id': 'x', 'date': '2024-01-01', 'category': 'Food',
             'amount': 10, 'note': 'a,b'},
        ])
        lines = out.strip().splitlines()
        self.assertEqual(lines[0], 'id,date,category,amount,note')
        self.assertIn('"a,b"', lines[1])

    def test_load_corrupt_file_returns_empty(self):
        corrupt = os.path.join(server.BASE_DIR, 'corrupt_unit_test.json')
        with open(corrupt, 'w', encoding='utf-8') as f:
            f.write('{ this is : not json ]')
        old = server.DATA_FILE
        server.DATA_FILE = corrupt
        try:
            self.assertEqual(server._load(), [])
        finally:
            server.DATA_FILE = old
            os.remove(corrupt)

    def test_sort_unknown_field_preserves_order(self):
        items = [{'amount': 3}, {'amount': 1}, {'amount': 2}]
        out = server._sort_expenses(items, None, 'asc')
        self.assertEqual([e['amount'] for e in out], [3, 1, 2])

    def test_sort_by_note_case_insensitive(self):
        items = [{'note': 'banana'}, {'note': 'Apple'}, {'note': 'cherry'}]
        out = server._sort_expenses(items, 'note', 'asc')
        self.assertEqual([e['note'] for e in out], ['Apple', 'banana', 'cherry'])

    def test_filter_by_query_substring(self):
        items = [
            {'note': 'Lunch', 'category': 'Food', 'date': '2024-01-01', 'amount': 1},
            {'note': 'Bus', 'category': 'Transport', 'date': '2024-01-02', 'amount': 1},
        ]
        out = server._filter_expenses(items, query='lun')
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['note'], 'Lunch')

    def test_top_category_ties_break_alphabetically(self):
        # Bills and Food both at 10 -> alphabetically first wins.
        self.assertEqual(
            server._top_category({'Food': 10.0, 'Bills': 10.0, 'Fun': 0.0}),
            'Bills')

    def test_top_category_none_when_no_spend(self):
        self.assertIsNone(server._top_category({'Food': 0.0, 'Bills': 0.0}))

    def test_largest_expense_picks_max(self):
        items = [{'amount': 5}, {'amount': 40}, {'amount': 12}]
        self.assertEqual(server._largest_expense(items)['amount'], 40)

    def test_largest_expense_empty_is_none(self):
        self.assertIsNone(server._largest_expense([]))

    def test_load_budget_missing_returns_none(self):
        old = server.BUDGET_FILE
        server.BUDGET_FILE = os.path.join(server.BASE_DIR, 'no_such_budget.json')
        try:
            self.assertIsNone(server._load_budget())
        finally:
            server.BUDGET_FILE = old

    # ---- tags domain helpers ----

    def test_normalize_tags_none_is_empty(self):
        tags, err = server._normalize_tags(None)
        self.assertIsNone(err)
        self.assertEqual(tags, [])

    def test_normalize_tags_strip_and_dedupe(self):
        tags, err = server._normalize_tags(['  a ', 'A', 'b', 'b'])
        self.assertIsNone(err)
        self.assertEqual(tags, ['a', 'b'])

    def test_normalize_tags_rejects_non_list(self):
        tags, err = server._normalize_tags('a')
        self.assertIsNone(tags)
        self.assertIsNotNone(err)

    def test_normalize_tags_rejects_non_string_element(self):
        tags, err = server._normalize_tags(['a', 7])
        self.assertIsNone(tags)
        self.assertIsNotNone(err)

    def test_normalize_tags_rejects_too_long(self):
        tags, err = server._normalize_tags(['x' * (server.MAX_TAG_LEN + 1)])
        self.assertIsNone(tags)
        self.assertIsNotNone(err)

    def test_tag_breakdown_sorts_by_spend_desc(self):
        out = server._tag_breakdown([
            {'amount': 5, 'tags': ['a']},
            {'amount': 30, 'tags': ['b', 'a']},
        ])
        self.assertEqual(out['a'], 35.0)
        self.assertEqual(out['b'], 30.0)
        self.assertEqual(list(out.keys()), ['a', 'b'])

    def test_filter_by_tag_matches_any(self):
        items = [
            {'tags': ['work'], 'category': 'Food', 'date': '2024-01-01', 'amount': 1},
            {'tags': ['home'], 'category': 'Bills', 'date': '2024-01-02', 'amount': 1},
        ]
        out = server._filter_expenses(items, tag='WORK')
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['tags'], ['work'])

    # ---- forecast domain helper ----

    def test_forecast_projects_linearly(self):
        out = server._forecast([{'amount': 100, 'date': '2024-04-05'}], '2024-04-10')
        # April has 30 days; $100 over 10 days -> $10/day -> $300 projected
        self.assertEqual(out['days_in_month'], 30)
        self.assertEqual(out['avg_daily'], 10.0)
        self.assertEqual(out['projected'], 300.0)

    def test_forecast_invalid_date_returns_none(self):
        self.assertIsNone(server._forecast([], 'not-a-date'))

    # ---- CSV import domain helper ----

    def test_parse_import_csv_basic(self):
        expenses, errors = server._parse_import_csv(
            'date,category,amount,note\n2024-01-01,Food,10,Lunch\n')
        self.assertEqual(errors, [])
        self.assertEqual(len(expenses), 1)
        self.assertEqual(expenses[0]['amount'], 10.0)
        self.assertEqual(expenses[0]['category'], 'Food')
        self.assertEqual(expenses[0]['note'], 'Lunch')
        # cleaned dicts carry no id (assigned at the handler layer)
        self.assertNotIn('id', expenses[0])

    def test_parse_import_csv_records_row_errors(self):
        expenses, errors = server._parse_import_csv(
            'date,category,amount,note\n'
            '2024-01-01,Food,10,ok\n'
            '2024-01-02,Bogus,5,bad\n')
        self.assertEqual(len(expenses), 1)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['row'], 2)
        self.assertIn('category', errors[0]['error'])

    def test_parse_import_csv_tags_semicolon_split(self):
        expenses, errors = server._parse_import_csv(
            'date,category,amount,tags\n2024-01-01,Food,10,a;b;a\n')
        self.assertEqual(errors, [])
        # dedupe still applies via _validate_fields -> _normalize_tags
        self.assertEqual(expenses[0]['tags'], ['a', 'b'])

    def test_parse_import_csv_empty_and_blank(self):
        self.assertEqual(server._parse_import_csv(''), ([], []))
        self.assertEqual(server._parse_import_csv('   '), ([], []))
        self.assertEqual(server._parse_import_csv(None), ([], []))

    def test_parse_import_csv_header_only(self):
        expenses, errors = server._parse_import_csv('date,category,amount,note\n')
        self.assertEqual(expenses, [])
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
