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
        self.recurring_file = os.path.join(server.BASE_DIR, 'recurring_test.json')
        server.DATA_FILE = self.data_file
        server.BUDGET_FILE = self.budget_file
        server.CAT_BUDGET_FILE = self.cat_budget_file
        server.RECURRING_FILE = self.recurring_file
        for f in (self.data_file, self.budget_file, self.cat_budget_file,
                  self.recurring_file):
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
        for f in (self.data_file, self.budget_file, self.cat_budget_file,
                  self.recurring_file):
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

    # ---- amount-range filtering (min_amount / max_amount) ----

    def test_min_amount_filter(self):
        self._make(amount=5)
        self._make(amount=15)
        self._make(amount=25)
        _, listing = self._request('GET', '/api/expenses?min_amount=15')
        amounts = sorted(e['amount'] for e in listing['expenses'])
        self.assertEqual(amounts, [15.0, 25.0])
        self.assertEqual(listing['count'], 2)
        self.assertEqual(listing['total'], 40.0)

    def test_max_amount_filter(self):
        self._make(amount=5)
        self._make(amount=15)
        self._make(amount=25)
        _, listing = self._request('GET', '/api/expenses?max_amount=15')
        amounts = sorted(e['amount'] for e in listing['expenses'])
        self.assertEqual(amounts, [5.0, 15.0])
        self.assertEqual(listing['count'], 2)

    def test_amount_range_inclusive_bounds(self):
        self._make(amount=10)
        self._make(amount=20)
        self._make(amount=30)
        _, listing = self._request(
            'GET', '/api/expenses?min_amount=10&max_amount=20')
        amounts = sorted(e['amount'] for e in listing['expenses'])
        self.assertEqual(amounts, [10.0, 20.0])

    def test_amount_range_combines_with_category(self):
        self._make(amount=50, category='Food')
        self._make(amount=50, category='Bills')
        self._make(amount=5, category='Food')
        _, listing = self._request(
            'GET', '/api/expenses?category=Food&min_amount=10')
        self.assertEqual(listing['count'], 1)
        self.assertEqual(listing['expenses'][0]['amount'], 50.0)
        self.assertEqual(listing['expenses'][0]['category'], 'Food')

    def test_invalid_min_amount_returns_400(self):
        status, data = self._request('GET', '/api/expenses?min_amount=lots')
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_negative_min_amount_returns_400(self):
        status, data = self._request('GET', '/api/expenses?min_amount=-5')
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_invalid_max_amount_returns_400(self):
        status, data = self._request('GET', '/api/expenses?max_amount=nope')
        self.assertEqual(status, 400)

    def test_min_greater_than_max_returns_400(self):
        status, data = self._request(
            'GET', '/api/expenses?min_amount=50&max_amount=10')
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    # ---- per-category monthly pivot ----

    def test_category_monthly_endpoint(self):
        self._make(amount=10, category='Food', date='2024-01-05')
        self._make(amount=5, category='Food', date='2024-01-20')
        self._make(amount=20, category='Food', date='2024-02-10')
        self._make(amount=30, category='Bills', date='2024-01-15')
        status, data = self._request('GET', '/api/summary/category-monthly')
        self.assertEqual(status, 200)
        cm = data['category_monthly']
        self.assertEqual(cm['Food']['2024-01'], 15.0)
        self.assertEqual(cm['Food']['2024-02'], 20.0)
        self.assertEqual(cm['Bills']['2024-01'], 30.0)

    def test_category_monthly_empty(self):
        status, data = self._request('GET', '/api/summary/category-monthly')
        self.assertEqual(status, 200)
        self.assertEqual(data['category_monthly'], {})

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

    # ---- recurring expenses ----------------------------------------------

    def test_recurring_create_and_list(self):
        status, data = self._request('POST', '/api/recurring', {
            'amount': 9.99, 'category': 'Bills', 'date': '2024-01-01',
            'freq': 'monthly', 'note': 'Netflix'
        })
        self.assertEqual(status, 201)
        self.assertIn('id', data)
        self.assertEqual(data['freq'], 'monthly')
        self.assertEqual(data['start'], '2024-01-01')
        self.assertIsNone(data['last_generated'])
        # no 'date' key — anchor lives under 'start'
        self.assertNotIn('date', data)

        status, listing = self._request('GET', '/api/recurring')
        self.assertEqual(status, 200)
        self.assertEqual(len(listing['recurring']), 1)
        self.assertEqual(listing['recurring'][0]['note'], 'Netflix')

    def test_recurring_create_invalid_freq_returns_400(self):
        status, data = self._request('POST', '/api/recurring', {
            'amount': 5, 'category': 'Food', 'date': '2024-01-01',
            'freq': 'yearly'
        })
        self.assertEqual(status, 400)
        self.assertIn('freq', data['error'])

    def test_recurring_create_invalid_amount_returns_400(self):
        status, data = self._request('POST', '/api/recurring', {
            'amount': 0, 'category': 'Food', 'date': '2024-01-01',
            'freq': 'daily'
        })
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_recurring_delete(self):
        _, created = self._request('POST', '/api/recurring', {
            'amount': 5, 'category': 'Food', 'date': '2024-01-01',
            'freq': 'weekly'
        })
        rid = created['id']
        status, data = self._request('DELETE', '/api/recurring/' + rid)
        self.assertEqual(status, 200)
        self.assertEqual(data['deleted'], rid)
        _, listing = self._request('GET', '/api/recurring')
        self.assertEqual(listing['recurring'], [])

    def test_recurring_delete_missing_returns_404(self):
        status, data = self._request('DELETE', '/api/recurring/nope')
        self.assertEqual(status, 404)
        self.assertIn('error', data)

    def test_recurring_run_generates_expenses(self):
        self._request('POST', '/api/recurring', {
            'amount': 10, 'category': 'Bills', 'date': '2024-01-01',
            'freq': 'monthly', 'note': 'Rent'
        })
        status, data = self._request('POST', '/api/recurring/run',
                                     {'asof': '2024-03-15'})
        self.assertEqual(status, 200)
        # Jan 1, Feb 1, Mar 1 -> 3 occurrences
        self.assertEqual(data['generated'], 3)
        dates = sorted(e['date'] for e in data['expenses'])
        self.assertEqual(dates, ['2024-01-01', '2024-02-01', '2024-03-01'])
        for e in data['expenses']:
            self.assertEqual(e['amount'], 10)
            self.assertEqual(e['category'], 'Bills')
            self.assertIn('recurring_id', e)

        # generated expenses are real expenses in the list + total
        _, listing = self._request('GET', '/api/expenses')
        self.assertEqual(len(listing['expenses']), 3)
        self.assertEqual(listing['total'], 30.0)

    def test_recurring_run_is_idempotent(self):
        self._request('POST', '/api/recurring', {
            'amount': 7, 'category': 'Fun', 'date': '2024-01-01',
            'freq': 'weekly'
        })
        _, first = self._request('POST', '/api/recurring/run',
                                  {'asof': '2024-01-31'})
        self.assertGreater(first['generated'], 0)
        # running again with the same asof generates nothing new
        _, second = self._request('POST', '/api/recurring/run',
                                   {'asof': '2024-01-31'})
        self.assertEqual(second['generated'], 0)
        _, listing = self._request('GET', '/api/expenses')
        self.assertEqual(len(listing['expenses']), first['generated'])

    def test_recurring_run_resumes_from_last_generated(self):
        self._request('POST', '/api/recurring', {
            'amount': 1, 'category': 'Other', 'date': '2024-01-01',
            'freq': 'daily'
        })
        _, first = self._request('POST', '/api/recurring/run',
                                  {'asof': '2024-01-03'})
        self.assertEqual(first['generated'], 3)  # 1st, 2nd, 3rd
        _, second = self._request('POST', '/api/recurring/run',
                                  {'asof': '2024-01-05'})
        self.assertEqual(second['generated'], 2)  # only 4th, 5th
        dates = sorted(e['date'] for e in second['expenses'])
        self.assertEqual(dates, ['2024-01-04', '2024-01-05'])

    def test_recurring_run_invalid_asof_returns_400(self):
        status, data = self._request('POST', '/api/recurring/run',
                                     {'asof': 'not-a-date'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_recurring_run_before_start_generates_nothing(self):
        self._request('POST', '/api/recurring', {
            'amount': 4, 'category': 'Food', 'date': '2024-06-01',
            'freq': 'monthly'
        })
        status, data = self._request('POST', '/api/recurring/run',
                                     {'asof': '2024-01-01'})
        self.assertEqual(status, 200)
        self.assertEqual(data['generated'], 0)

    def test_recurring_run_persists_to_file(self):
        self._request('POST', '/api/recurring', {
            'amount': 2, 'category': 'Transport', 'date': '2024-01-01',
            'freq': 'daily'
        })
        self._request('POST', '/api/recurring/run', {'asof': '2024-01-02'})
        with open(self.data_file) as f:
            saved = json.load(f)
        self.assertEqual(len(saved), 2)
        with open(self.recurring_file) as f:
            templates = json.load(f)
        self.assertEqual(templates[0]['last_generated'], '2024-01-02')

    # ---- weekly / percentages / top endpoints (relocated from DomainTest) --
    # These exercise the live HTTP API, so they need ExpenseAPITest's server
    # fixture; in DomainTest they raised AttributeError on self._request.

    def test_weekly_endpoint(self):
        self._request('POST', '/api/expenses',
                      {'amount': 12, 'category': 'Food', 'date': '2024-01-01'})
        self._request('POST', '/api/expenses',
                      {'amount': 8, 'category': 'Fun', 'date': '2024-01-09'})
        status, data = self._request('GET', '/api/summary/weekly')
        self.assertEqual(status, 200)
        self.assertEqual(data['weekly'], {'2024-W01': 12.0, '2024-W02': 8.0})

    def test_percentages_endpoint(self):
        self._request('POST', '/api/expenses',
                      {'amount': 30, 'category': 'Food', 'date': '2024-01-01'})
        self._request('POST', '/api/expenses',
                      {'amount': 10, 'category': 'Fun', 'date': '2024-01-01'})
        status, data = self._request('GET', '/api/summary/percentages')
        self.assertEqual(status, 200)
        self.assertEqual(data['percentages']['total'], 40.0)
        self.assertEqual(data['percentages']['categories']['Food']['percent'], 75.0)
        self.assertEqual(data['percentages']['categories']['Fun']['percent'], 25.0)

    def test_top_endpoint(self):
        for amt in (5, 100, 50):
            self._request('POST', '/api/expenses',
                          {'amount': amt, 'category': 'Food', 'date': '2024-01-01'})
        status, data = self._request('GET', '/api/summary/top?n=2')
        self.assertEqual(status, 200)
        self.assertEqual([e['amount'] for e in data['top']], [100.0, 50.0])

    def test_top_endpoint_default_n(self):
        for amt in range(1, 9):
            self._request('POST', '/api/expenses',
                          {'amount': amt, 'category': 'Food', 'date': '2024-01-01'})
        status, data = self._request('GET', '/api/summary/top')
        self.assertEqual(status, 200)
        self.assertEqual(len(data['top']), 5)  # default n=5

    def test_top_endpoint_invalid_n(self):
        status, data = self._request('GET', '/api/summary/top?n=abc')
        self.assertEqual(status, 400)
        status, data = self._request('GET', '/api/summary/top?n=0')
        self.assertEqual(status, 400)

    # ---- bulk delete (relocated from DomainTest) --------------------------

    def test_bulk_delete_removes_many(self):
        ids = []
        for amt in (1, 2, 3):
            _, e = self._request('POST', '/api/expenses',
                                 {'amount': amt, 'category': 'Food', 'date': '2024-01-01'})
            ids.append(e['id'])
        status, data = self._request('POST', '/api/expenses/bulk-delete',
                                     {'ids': [ids[0], ids[2]]})
        self.assertEqual(status, 200)
        self.assertEqual(data['count'], 2)
        self.assertEqual(set(data['deleted']), {ids[0], ids[2]})
        self.assertEqual(data['not_found'], [])
        # only the middle one survives
        _, listing = self._request('GET', '/api/expenses')
        self.assertEqual([e['id'] for e in listing['expenses']], [ids[1]])

    def test_bulk_delete_reports_not_found(self):
        _, e = self._request('POST', '/api/expenses',
                             {'amount': 9, 'category': 'Fun', 'date': '2024-01-01'})
        status, data = self._request('POST', '/api/expenses/bulk-delete',
                                     {'ids': [e['id'], 'ghost', e['id']]})
        self.assertEqual(status, 200)
        self.assertEqual(data['deleted'], [e['id']])  # de-duplicated
        self.assertEqual(data['not_found'], ['ghost'])
        self.assertEqual(data['count'], 1)

    def test_bulk_delete_empty_is_noop(self):
        self._request('POST', '/api/expenses',
                      {'amount': 9, 'category': 'Fun', 'date': '2024-01-01'})
        status, data = self._request('POST', '/api/expenses/bulk-delete', {'ids': []})
        self.assertEqual(status, 200)
        self.assertEqual(data['count'], 0)
        _, listing = self._request('GET', '/api/expenses')
        self.assertEqual(len(listing['expenses']), 1)

    def test_bulk_delete_non_list_is_400(self):
        status, data = self._request('POST', '/api/expenses/bulk-delete',
                                     {'ids': 'oops'})
        self.assertEqual(status, 400)

    def test_bulk_delete_persists(self):
        ids = []
        for amt in (1, 2):
            _, e = self._request('POST', '/api/expenses',
                                 {'amount': amt, 'category': 'Food', 'date': '2024-01-01'})
            ids.append(e['id'])
        self._request('POST', '/api/expenses/bulk-delete', {'ids': ids})
        with open(self.data_file) as f:
            saved = json.load(f)
        self.assertEqual(saved, [])

    # ---- previously-untested existing endpoints ---------------------------

    def test_stats_endpoint(self):
        self._make(amount=10, date='2024-01-01')  # Mon
        self._make(amount=30, date='2024-01-02')  # Tue
        self._make(amount=20, date='2024-01-03')  # Wed
        status, data = self._request('GET', '/api/summary/stats')
        self.assertEqual(status, 200)
        st = data['stats']
        self.assertEqual(st['min'], 10.0)
        self.assertEqual(st['max'], 30.0)
        self.assertEqual(st['median'], 20.0)
        self.assertEqual(st['weekday']['Mon'], 10.0)
        self.assertEqual(st['weekday']['Tue'], 30.0)

    def test_stats_endpoint_empty(self):
        status, data = self._request('GET', '/api/summary/stats')
        self.assertEqual(status, 200)
        st = data['stats']
        self.assertIsNone(st['min'])
        self.assertIsNone(st['max'])
        self.assertIsNone(st['median'])

    def test_daily_endpoint(self):
        self._make(amount=10, date='2024-01-05')
        self._make(amount=5, date='2024-01-05')
        self._make(amount=20, date='2024-01-06')
        self._make(amount=99, date='2024-02-01')  # different month, excluded
        status, data = self._request('GET', '/api/summary/daily?month=2024-01')
        self.assertEqual(status, 200)
        self.assertEqual(data['month'], '2024-01')
        self.assertEqual(data['daily'], {'2024-01-05': 15.0, '2024-01-06': 20.0})

    def test_daily_endpoint_invalid_month(self):
        status, data = self._request('GET', '/api/summary/daily?month=2024-13')
        self.assertEqual(status, 400)
        self.assertIn('error', data)
        status, _ = self._request('GET', '/api/summary/daily')
        self.assertEqual(status, 400)

    def test_category_averages_endpoint(self):
        self._make(amount=10, category='Food')
        self._make(amount=30, category='Food')
        self._make(amount=20, category='Bills')
        status, data = self._request('GET', '/api/summary/category-averages')
        self.assertEqual(status, 200)
        ca = data['category_averages']
        self.assertEqual(ca['Food'], {'count': 2, 'total': 40.0, 'average': 20.0})
        self.assertEqual(ca['Bills'], {'count': 1, 'total': 20.0, 'average': 20.0})
        self.assertEqual(ca['Fun'], {'count': 0, 'total': 0.0, 'average': 0.0})

    def test_compare_endpoint(self):
        self._make(amount=100, category='Food', date='2024-01-10')
        self._make(amount=150, category='Food', date='2024-02-10')
        self._make(amount=50, category='Bills', date='2024-02-15')
        status, data = self._request(
            'GET', '/api/summary/compare?a=2024-01&b=2024-02')
        self.assertEqual(status, 200)
        cmp = data['compare']
        self.assertEqual(cmp['total_a'], 100.0)
        self.assertEqual(cmp['total_b'], 200.0)
        self.assertEqual(cmp['delta'], 100.0)
        self.assertEqual(cmp['percent_change'], 100.0)
        self.assertEqual(cmp['categories']['Food']['delta'], 50.0)
        self.assertEqual(cmp['categories']['Bills']['delta'], 50.0)

    def test_compare_endpoint_invalid_month(self):
        status, _ = self._request('GET', '/api/summary/compare?a=bad&b=2024-02')
        self.assertEqual(status, 400)
        status, _ = self._request('GET', '/api/summary/compare?a=2024-01')
        self.assertEqual(status, 400)

    def test_recurring_edit_updates_fields(self):
        _, created = self._request('POST', '/api/recurring', {
            'amount': 5, 'category': 'Food', 'date': '2024-01-01',
            'freq': 'monthly', 'note': 'Gym'
        })
        rid = created['id']
        status, updated = self._request('PUT', '/api/recurring/' + rid,
                                        {'amount': 12.5, 'freq': 'weekly'})
        self.assertEqual(status, 200)
        self.assertEqual(updated['amount'], 12.5)
        self.assertEqual(updated['freq'], 'weekly')
        self.assertEqual(updated['note'], 'Gym')  # untouched
        self.assertEqual(updated['start'], '2024-01-01')  # untouched

    def test_recurring_edit_preserves_last_generated(self):
        _, created = self._request('POST', '/api/recurring', {
            'amount': 1, 'category': 'Other', 'date': '2024-01-01',
            'freq': 'daily'
        })
        rid = created['id']
        self._request('POST', '/api/recurring/run', {'asof': '2024-01-03'})
        # editing the amount must not re-materialize already-generated days
        status, updated = self._request('PUT', '/api/recurring/' + rid,
                                        {'amount': 9})
        self.assertEqual(status, 200)
        self.assertEqual(updated['last_generated'], '2024-01-03')
        _, again = self._request('POST', '/api/recurring/run', {'asof': '2024-01-03'})
        self.assertEqual(again['generated'], 0)

    def test_recurring_edit_invalid_freq_returns_400(self):
        _, created = self._request('POST', '/api/recurring', {
            'amount': 5, 'category': 'Food', 'date': '2024-01-01', 'freq': 'daily'
        })
        status, data = self._request('PUT', '/api/recurring/' + created['id'],
                                     {'freq': 'yearly'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_recurring_edit_missing_returns_404(self):
        status, data = self._request('PUT', '/api/recurring/nope', {'amount': 5})
        self.assertEqual(status, 404)
        self.assertIn('error', data)

    # ---- budget pacing (new) ----------------------------------------------

    def test_pace_on_track_under_budget(self):
        # $100 over 10 days of a 31-day month -> projected $310, budget $400.
        self._request('PUT', '/api/budget', {'budget': 400})
        self._make(amount=100, date='2024-01-05')
        status, data = self._request('GET', '/api/summary/pace?asof=2024-01-10')
        self.assertEqual(status, 200)
        pace = data['pace']
        self.assertEqual(pace['budget'], 400.0)
        self.assertEqual(pace['spent'], 100.0)
        self.assertEqual(pace['projected'], 310.0)
        self.assertEqual(pace['projected_remaining'], 90.0)
        self.assertTrue(pace['on_track'])
        self.assertFalse(pace['already_over'])
        self.assertEqual(pace['days_left'], 21)
        # (400 - 100) / 21 remaining days
        self.assertEqual(pace['daily_budget_remaining'], 14.29)
        self.assertEqual(pace['percent_used'], 25.0)

    def test_pace_projected_over_budget(self):
        # $300 over 10 days -> projected $930, budget $500 -> not on track.
        self._request('PUT', '/api/budget', {'budget': 500})
        self._make(amount=300, date='2024-01-05')
        _, data = self._request('GET', '/api/summary/pace?asof=2024-01-10')
        pace = data['pace']
        self.assertEqual(pace['projected'], 930.0)
        self.assertFalse(pace['on_track'])
        self.assertFalse(pace['already_over'])  # spent 300 < 500
        self.assertEqual(pace['projected_remaining'], -430.0)

    def test_pace_already_over_budget(self):
        self._request('PUT', '/api/budget', {'budget': 50})
        self._make(amount=80, date='2024-01-05')
        _, data = self._request('GET', '/api/summary/pace?asof=2024-01-10')
        pace = data['pace']
        self.assertTrue(pace['already_over'])
        self.assertFalse(pace['on_track'])
        self.assertEqual(pace['daily_budget_remaining'], 0.0)  # never negative

    def test_pace_no_budget_set(self):
        self._make(amount=100, date='2024-01-05')
        _, data = self._request('GET', '/api/summary/pace?asof=2024-01-10')
        pace = data['pace']
        self.assertIsNone(pace['budget'])
        self.assertTrue(pace['on_track'])  # no budget -> nothing to overshoot
        self.assertIsNone(pace['projected_remaining'])
        self.assertIsNone(pace['percent_used'])
        self.assertEqual(pace['projected'], 310.0)  # forecast still computed

    def test_pace_missing_asof_returns_400(self):
        status, data = self._request('GET', '/api/summary/pace')
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_pace_invalid_asof_returns_400(self):
        status, _ = self._request('GET', '/api/summary/pace?asof=nope')
        self.assertEqual(status, 400)


    # ---- Outlier detection ----------------------------------------------

    def test_outliers_flags_large_for_category(self):
        # Food median is 10; the 100 is 10x -> flagged at default threshold 2.0.
        self._make(amount=10, category='Food', date='2024-01-01')
        self._make(amount=10, category='Food', date='2024-01-02')
        self._make(amount=100, category='Food', date='2024-01-03')
        status, data = self._request('GET', '/api/summary/outliers')
        self.assertEqual(status, 200)
        self.assertEqual(data['threshold'], 2.0)
        self.assertEqual(len(data['outliers']), 1)
        flagged = data['outliers'][0]
        self.assertEqual(flagged['amount'], 100)
        self.assertEqual(flagged['category_median'], 10.0)
        self.assertEqual(flagged['ratio'], 10.0)

    def test_outliers_per_category_baseline(self):
        # A 50 Bills expense is huge for Bills but normal-ish only relative to
        # its own category — outliers are computed per category, not globally.
        self._make(amount=10, category='Food', date='2024-01-01')
        self._make(amount=10, category='Food', date='2024-01-02')
        self._make(amount=2, category='Bills', date='2024-01-03')
        self._make(amount=2, category='Bills', date='2024-01-04')
        self._make(amount=50, category='Bills', date='2024-01-05')
        status, data = self._request('GET', '/api/summary/outliers')
        self.assertEqual(status, 200)
        cats = {o['category'] for o in data['outliers']}
        self.assertEqual(cats, {'Bills'})

    def test_outliers_custom_threshold(self):
        self._make(amount=10, category='Food', date='2024-01-01')
        self._make(amount=10, category='Food', date='2024-01-02')
        self._make(amount=25, category='Food', date='2024-01-03')  # 2.5x median
        # threshold 3.0 -> 25 is below 3x10, nothing flagged.
        _, data = self._request('GET', '/api/summary/outliers?threshold=3')
        self.assertEqual(data['outliers'], [])
        # threshold 2.0 -> flagged.
        _, data = self._request('GET', '/api/summary/outliers?threshold=2')
        self.assertEqual(len(data['outliers']), 1)

    def test_outliers_single_expense_not_flagged(self):
        # A category of one equals its own median -> never an outlier.
        self._make(amount=999, category='Fun', date='2024-01-01')
        _, data = self._request('GET', '/api/summary/outliers')
        self.assertEqual(data['outliers'], [])

    def test_outliers_empty(self):
        _, data = self._request('GET', '/api/summary/outliers')
        self.assertEqual(data['outliers'], [])

    def test_outliers_invalid_threshold_returns_400(self):
        status, data = self._request('GET', '/api/summary/outliers?threshold=abc')
        self.assertEqual(status, 400)
        self.assertIn('threshold', data['error'])

    def test_outliers_threshold_below_one_returns_400(self):
        status, data = self._request('GET', '/api/summary/outliers?threshold=0.5')
        self.assertEqual(status, 400)

    # ---- Duplicate detection --------------------------------------------

    def test_duplicates_groups_same_amount_category_date(self):
        self._make(amount=12, category='Food', date='2024-03-01', note='lunch')
        self._make(amount=12, category='Food', date='2024-03-01', note='lunch again')
        self._make(amount=5, category='Bills', date='2024-03-02')
        status, data = self._request('GET', '/api/summary/duplicates')
        self.assertEqual(status, 200)
        self.assertEqual(len(data['duplicates']), 1)
        group = data['duplicates'][0]
        self.assertEqual(group['amount'], 12)
        self.assertEqual(group['category'], 'Food')
        self.assertEqual(group['date'], '2024-03-01')
        self.assertEqual(group['count'], 2)
        self.assertEqual(len(group['ids']), 2)

    def test_duplicates_distinct_fields_not_grouped(self):
        # Same amount + category but different date -> not duplicates.
        self._make(amount=12, category='Food', date='2024-03-01')
        self._make(amount=12, category='Food', date='2024-03-02')
        _, data = self._request('GET', '/api/summary/duplicates')
        self.assertEqual(data['duplicates'], [])

    def test_duplicates_sorted_by_count_then_amount(self):
        # Group A: 3x of 5; group B: 2x of 50. A has higher count -> first.
        for _ in range(3):
            self._make(amount=5, category='Food', date='2024-04-01')
        for _ in range(2):
            self._make(amount=50, category='Bills', date='2024-04-02')
        _, data = self._request('GET', '/api/summary/duplicates')
        counts = [g['count'] for g in data['duplicates']]
        self.assertEqual(counts, [3, 2])

    def test_duplicates_empty(self):
        _, data = self._request('GET', '/api/summary/duplicates')
        self.assertEqual(data['duplicates'], [])

    # ---- Bulk recategorize ----------------------------------------------

    def test_recategorize_moves_all_in_category(self):
        a = self._make(amount=10, category='Fun', date='2024-05-01')
        b = self._make(amount=20, category='Fun', date='2024-05-02')
        self._make(amount=5, category='Food', date='2024-05-03')
        status, data = self._request(
            'POST', '/api/expenses/recategorize', {'from': 'Fun', 'to': 'Other'})
        self.assertEqual(status, 200)
        self.assertEqual(data['moved'], 2)
        self.assertEqual(set(data['ids']), {a['id'], b['id']})
        # Persisted: Fun now empty, Other holds the moved spend.
        _, listing = self._request('GET', '/api/expenses')
        self.assertEqual(listing['breakdown']['Fun'], 0.0)
        self.assertEqual(listing['breakdown']['Other'], 30.0)

    def test_recategorize_same_category_is_noop(self):
        self._make(amount=10, category='Food', date='2024-05-01')
        status, data = self._request(
            'POST', '/api/expenses/recategorize', {'from': 'Food', 'to': 'Food'})
        self.assertEqual(status, 200)
        self.assertEqual(data['moved'], 0)
        self.assertEqual(data['ids'], [])

    def test_recategorize_no_matches(self):
        self._make(amount=10, category='Food', date='2024-05-01')
        status, data = self._request(
            'POST', '/api/expenses/recategorize', {'from': 'Bills', 'to': 'Fun'})
        self.assertEqual(status, 200)
        self.assertEqual(data['moved'], 0)

    def test_recategorize_invalid_from_returns_400(self):
        status, data = self._request(
            'POST', '/api/expenses/recategorize', {'from': 'Nope', 'to': 'Food'})
        self.assertEqual(status, 400)
        self.assertIn('from', data['error'])

    def test_recategorize_invalid_to_returns_400(self):
        status, data = self._request(
            'POST', '/api/expenses/recategorize', {'from': 'Food', 'to': 'Nope'})
        self.assertEqual(status, 400)
        self.assertIn('to', data['error'])


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

    def test_filter_by_amount_range(self):
        items = [
            {'amount': 5, 'category': 'Food', 'date': '2024-01-01'},
            {'amount': 15, 'category': 'Food', 'date': '2024-01-02'},
            {'amount': 25, 'category': 'Food', 'date': '2024-01-03'},
        ]
        out = server._filter_expenses(items, min_amount=10, max_amount=20)
        self.assertEqual([e['amount'] for e in out], [15])

    def test_filter_min_amount_only(self):
        items = [{'amount': 5}, {'amount': 50}]
        out = server._filter_expenses(items, min_amount=10)
        self.assertEqual([e['amount'] for e in out], [50])

    def test_category_monthly_pivot(self):
        out = server._category_monthly([
            {'amount': 10, 'category': 'Food', 'date': '2024-02-01'},
            {'amount': 5, 'category': 'Food', 'date': '2024-01-05'},
            {'amount': 30, 'category': 'Bills', 'date': '2024-01-15'},
        ])
        # categories sorted by name, months sorted within
        self.assertEqual(list(out.keys()), ['Bills', 'Food'])
        self.assertEqual(list(out['Food'].keys()), ['2024-01', '2024-02'])
        self.assertEqual(out['Food']['2024-01'], 5.0)
        self.assertEqual(out['Food']['2024-02'], 10.0)
        self.assertEqual(out['Bills']['2024-01'], 30.0)

    def test_category_monthly_skips_bad_dates_and_categories(self):
        out = server._category_monthly([
            {'amount': 5, 'category': 'Food', 'date': ''},
            {'amount': 5, 'category': 'Bogus', 'date': '2024-01-01'},
        ])
        self.assertEqual(out, {})

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

    # ---- recurring date logic --------------------------------------------

    def test_add_months_clamps_day(self):
        import datetime
        # Jan 31 + 1 month -> Feb 29 in a leap year
        self.assertEqual(server._add_months(datetime.date(2024, 1, 31), 1),
                         datetime.date(2024, 2, 29))
        # Jan 31 + 1 month -> Feb 28 in a non-leap year
        self.assertEqual(server._add_months(datetime.date(2023, 1, 31), 1),
                         datetime.date(2023, 2, 28))
        # crossing a year boundary
        self.assertEqual(server._add_months(datetime.date(2024, 12, 15), 1),
                         datetime.date(2025, 1, 15))

    def test_occurrence_anchored_no_drift(self):
        import datetime
        start = datetime.date(2024, 1, 31)
        # monthly occurrences anchor to start, so March returns to the 31st
        self.assertEqual(server._occurrence(start, 'monthly', 2),
                         datetime.date(2024, 3, 31))
        self.assertEqual(server._occurrence(start, 'weekly', 2),
                         datetime.date(2024, 2, 14))
        self.assertEqual(server._occurrence(start, 'daily', 5),
                         datetime.date(2024, 2, 5))

    def test_due_occurrences_inclusive_bounds(self):
        out = server._due_occurrences('2024-01-01', 'daily', '2024-01-03')
        self.assertEqual(out, ['2024-01-01', '2024-01-02', '2024-01-03'])

    def test_due_occurrences_after_skips_generated(self):
        out = server._due_occurrences('2024-01-01', 'daily', '2024-01-05',
                                      after='2024-01-03')
        self.assertEqual(out, ['2024-01-04', '2024-01-05'])

    def test_due_occurrences_start_after_asof_is_empty(self):
        self.assertEqual(
            server._due_occurrences('2024-06-01', 'monthly', '2024-01-01'), [])

    def test_due_occurrences_invalid_inputs_empty(self):
        self.assertEqual(server._due_occurrences('bad', 'daily', '2024-01-01'), [])
        self.assertEqual(
            server._due_occurrences('2024-01-01', 'yearly', '2024-02-01'), [])

    def test_validate_recurring_rejects_bad_freq(self):
        cleaned, err = server._validate_recurring(
            5, 'Food', '', '2024-01-01', 'fortnightly')
        self.assertIsNone(cleaned)
        self.assertIn('freq', err)

    def test_validate_recurring_shapes_template(self):
        cleaned, err = server._validate_recurring(
            5.5, 'Food', ' coffee ', '2024-01-01', 'weekly', ['Daily', 'daily'])
        self.assertIsNone(err)
        self.assertEqual(cleaned['start'], '2024-01-01')
        self.assertEqual(cleaned['freq'], 'weekly')
        self.assertEqual(cleaned['note'], 'coffee')
        self.assertIsNone(cleaned['last_generated'])
        self.assertEqual(cleaned['tags'], ['Daily'])  # deduped
        self.assertNotIn('date', cleaned)

    def test_materialize_recurring_advances_last_generated(self):
        templates = [{
            'id': 'r1', 'amount': 3, 'category': 'Fun', 'note': '',
            'tags': [], 'freq': 'daily', 'start': '2024-01-01',
            'last_generated': None,
        }]
        expenses = []
        gen = server._materialize_recurring(templates, expenses, '2024-01-02')
        self.assertEqual(len(gen), 2)
        self.assertEqual(templates[0]['last_generated'], '2024-01-02')
        self.assertEqual(len(expenses), 2)
        # a second run with the same asof yields nothing
        gen2 = server._materialize_recurring(templates, expenses, '2024-01-02')
        self.assertEqual(gen2, [])

    def test_load_recurring_corrupt_returns_empty(self):
        path = os.path.join(server.BASE_DIR, 'recurring_corrupt_test.json')
        with open(path, 'w') as f:
            f.write('{ not json')
        old = server.RECURRING_FILE
        server.RECURRING_FILE = path
        try:
            self.assertEqual(server._load_recurring(), [])
        finally:
            server.RECURRING_FILE = old
            os.remove(path)


    # ---- weekly breakdown -------------------------------------------------

    def test_iso_week_breakdown_groups_by_week(self):
        # 2024-01-01 (Mon) is ISO week 2024-W01; 2024-01-08 is W02.
        exps = [
            {'date': '2024-01-01', 'amount': 10, 'category': 'Food'},
            {'date': '2024-01-03', 'amount': 5, 'category': 'Food'},
            {'date': '2024-01-08', 'amount': 20, 'category': 'Bills'},
        ]
        wk = server._iso_week_breakdown(exps)
        self.assertEqual(wk, {'2024-W01': 15.0, '2024-W02': 20.0})
        # sorted ascending
        self.assertEqual(list(wk.keys()), ['2024-W01', '2024-W02'])

    def test_iso_week_breakdown_skips_bad_dates(self):
        exps = [
            {'date': 'nope', 'amount': 9, 'category': 'Food'},
            {'date': '2024-02-19', 'amount': 4, 'category': 'Fun'},
        ]
        self.assertEqual(server._iso_week_breakdown(exps), {'2024-W08': 4.0})

    # ---- category percentages --------------------------------------------

    def test_category_percentages_basic(self):
        exps = [
            {'date': '2024-01-01', 'amount': 75, 'category': 'Food'},
            {'date': '2024-01-02', 'amount': 25, 'category': 'Bills'},
        ]
        pct = server._category_percentages(exps)
        self.assertEqual(pct['total'], 100.0)
        self.assertEqual(pct['categories']['Food'],
                         {'spent': 75.0, 'percent': 75.0})
        self.assertEqual(pct['categories']['Bills'],
                         {'spent': 25.0, 'percent': 25.0})
        # unused categories present with zeros
        self.assertEqual(pct['categories']['Fun'],
                         {'spent': 0.0, 'percent': 0.0})

    def test_category_percentages_empty_no_div_by_zero(self):
        pct = server._category_percentages([])
        self.assertEqual(pct['total'], 0.0)
        for c in server.CATEGORIES:
            self.assertEqual(pct['categories'][c],
                             {'spent': 0.0, 'percent': 0.0})

    # ---- top expenses -----------------------------------------------------

    def test_top_expenses_orders_and_clamps(self):
        exps = [
            {'id': 'a', 'date': '2024-01-01', 'amount': 5, 'category': 'Food'},
            {'id': 'b', 'date': '2024-01-02', 'amount': 50, 'category': 'Bills'},
            {'id': 'c', 'date': '2024-01-03', 'amount': 20, 'category': 'Fun'},
        ]
        top = server._top_expenses(exps, 2)
        self.assertEqual([e['id'] for e in top], ['b', 'c'])
        # n larger than list is clamped
        self.assertEqual(len(server._top_expenses(exps, 99)), 3)
        # non-positive n -> empty
        self.assertEqual(server._top_expenses(exps, 0), [])

    def test_top_expenses_tie_broken_deterministically(self):
        exps = [
            {'id': 'a', 'date': '2024-01-01', 'amount': 10, 'category': 'Food'},
            {'id': 'b', 'date': '2024-01-05', 'amount': 10, 'category': 'Fun'},
        ]
        # equal amounts -> later date first
        self.assertEqual([e['id'] for e in server._top_expenses(exps, 2)],
                         ['b', 'a'])

    # ---- budget pacing domain helper -------------------------------------

    def test_budget_pace_under(self):
        exps = [{'amount': 100, 'date': '2024-01-05', 'category': 'Food'}]
        pace = server._budget_pace(exps, 400, '2024-01-10')
        self.assertEqual(pace['projected'], 310.0)
        self.assertTrue(pace['on_track'])
        self.assertEqual(pace['projected_remaining'], 90.0)
        self.assertEqual(pace['days_left'], 21)

    def test_budget_pace_no_budget(self):
        exps = [{'amount': 100, 'date': '2024-01-05', 'category': 'Food'}]
        pace = server._budget_pace(exps, None, '2024-01-10')
        self.assertIsNone(pace['budget'])
        self.assertTrue(pace['on_track'])
        self.assertIsNone(pace['projected_remaining'])
        self.assertEqual(pace['projected'], 310.0)

    def test_budget_pace_invalid_date_is_none(self):
        self.assertIsNone(server._budget_pace([], 100, 'not-a-date'))

    def test_budget_pace_daily_remaining_never_negative(self):
        # Already overspent: the per-day allowance floors at zero, not negative.
        exps = [{'amount': 80, 'date': '2024-01-05', 'category': 'Food'}]
        pace = server._budget_pace(exps, 50, '2024-01-10')
        self.assertTrue(pace['already_over'])
        self.assertEqual(pace['daily_budget_remaining'], 0.0)

    def test_budget_pace_last_day_of_month(self):
        # No days left -> daily_budget_remaining is None (can't spread over 0 days).
        exps = [{'amount': 100, 'date': '2024-01-31', 'category': 'Food'}]
        pace = server._budget_pace(exps, 200, '2024-01-31')
        self.assertEqual(pace['days_left'], 0)
        self.assertIsNone(pace['daily_budget_remaining'])
if __name__ == '__main__':
    unittest.main()
