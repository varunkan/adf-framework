import json
import threading
import unittest
import http.client

from server import (
    make_server, RequestHandler, _state, _history, _custom_presets,
    _preset_usage, _goal, _favorites, format_clock, MAX_SECONDS, GOAL_MAX,
)


class CountdownTimerTests(unittest.TestCase):
    def setUp(self):
        # reset module state to defaults (full reset for test isolation)
        _state.update({
            'minutes': 5, 'seconds': 0, 'total': 300, 'remaining': 300,
            'running': False, 'label': '', 'completed': 0,
            'repeat': 0, 'repeats_left': 0,
        })
        _history.clear()
        _custom_presets.clear()
        _preset_usage.clear()
        _favorites.clear()
        _goal['target'] = 0
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _conn(self):
        return http.client.HTTPConnection('localhost', self.port)

    def _request(self, method, path, body=None):
        conn = self._conn()
        headers = {}
        payload = None
        if body is not None:
            payload = json.dumps(body)
            headers['Content-Type'] = 'application/json'
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        data = resp.read().decode('utf-8')
        status = resp.status
        conn.close()
        try:
            parsed = json.loads(data)
        except ValueError:
            parsed = None
        return status, parsed

    def test_index_served(self):
        status, _ = self._request('GET', '/')
        self.assertEqual(status, 200)

    def test_index_accessibility_landmarks(self):
        # Locks in the self-heal a11y fixes: the served page must expose an
        # alert region for validation errors and a timer role for the display
        # so the countdown state is not conveyed by colour alone.
        conn = self._conn()
        conn.request('GET', '/')
        resp = conn.getresponse()
        html = resp.read().decode('utf-8')
        conn.close()
        self.assertIn('role="alert"', html)
        self.assertIn('role="timer"', html)
        self.assertIn('lang="en"', html)

    def test_main_success_path(self):
        # REQ-001/002: set minutes and seconds
        status, data = self._request('POST', '/api/timer', {'minutes': 2, 'seconds': 30})
        self.assertEqual(status, 201)
        self.assertEqual(data['minutes'], 2)
        self.assertEqual(data['seconds'], 30)
        self.assertEqual(data['remaining'], 150)
        self.assertFalse(data['running'])

        # read it back
        status, data = self._request('GET', '/api/timer')
        self.assertEqual(status, 200)
        self.assertEqual(data['remaining'], 150)

        # REQ-002: start
        status, data = self._request('POST', '/api/timer/start')
        self.assertEqual(status, 200)
        self.assertTrue(data['running'])

        # tick once -> decrement
        status, data = self._request('POST', '/api/timer/tick')
        self.assertEqual(status, 200)
        self.assertEqual(data['remaining'], 149)

        # REQ-002: pause
        status, data = self._request('POST', '/api/timer/pause')
        self.assertEqual(status, 200)
        self.assertFalse(data['running'])

        # tick while paused -> no change
        status, data = self._request('POST', '/api/timer/tick')
        self.assertEqual(data['remaining'], 149)

        # REQ-003: reset
        status, data = self._request('POST', '/api/timer/reset')
        self.assertEqual(status, 200)
        self.assertEqual(data['remaining'], 150)
        self.assertFalse(data['running'])

    def test_invalid_seconds_returns_400(self):
        status, data = self._request('POST', '/api/timer', {'minutes': 1, 'seconds': 99})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_invalid_minutes_returns_400(self):
        status, data = self._request('POST', '/api/timer', {'minutes': 99, 'seconds': 10})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_missing_fields_returns_400(self):
        status, data = self._request('POST', '/api/timer', {'minutes': 1})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_unknown_route_returns_404(self):
        status, data = self._request('GET', '/api/nope')
        self.assertEqual(status, 404)
        self.assertIn('error', data)


class ExistingEndpointCoverageTests(CountdownTimerTests):
    """Lock in coverage for endpoints that shipped without tests."""

    def test_format_clock_minutes_and_hours(self):
        self.assertEqual(format_clock(0), '00:00')
        self.assertEqual(format_clock(59), '00:59')
        self.assertEqual(format_clock(150), '02:30')
        self.assertEqual(format_clock(3600), '01:00:00')
        self.assertEqual(format_clock(3661), '01:01:01')
        # Negative values clamp to zero rather than rendering garbage.
        self.assertEqual(format_clock(-5), '00:00')

    def test_presets_listed(self):
        status, data = self._request('GET', '/api/timer/presets')
        self.assertEqual(status, 200)
        names = [p['name'] for p in data['presets']]
        self.assertIn('pomodoro', names)
        self.assertIn('five-minutes', names)
        # Built-ins are flagged non-custom.
        self.assertFalse(data['presets'][0]['custom'])

    def test_apply_builtin_preset(self):
        status, data = self._request('POST', '/api/timer/preset', {'name': 'pomodoro'})
        self.assertEqual(status, 200)
        self.assertEqual(data['remaining'], 25 * 60)
        self.assertEqual(data['minutes'], 25)
        self.assertEqual(data['label'], 'Pomodoro')

    def test_apply_unknown_preset_returns_400(self):
        status, data = self._request('POST', '/api/timer/preset', {'name': 'nope'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_apply_preset_missing_name_returns_400(self):
        status, data = self._request('POST', '/api/timer/preset', {})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_add_time_extends_and_subtracts(self):
        self._request('POST', '/api/timer', {'minutes': 1, 'seconds': 0})
        status, data = self._request('POST', '/api/timer/add', {'seconds': 30})
        self.assertEqual(status, 200)
        self.assertEqual(data['remaining'], 90)
        status, data = self._request('POST', '/api/timer/add', {'seconds': -30})
        self.assertEqual(data['remaining'], 60)

    def test_add_time_cannot_go_negative(self):
        self._request('POST', '/api/timer', {'minutes': 0, 'seconds': 10})
        status, data = self._request('POST', '/api/timer/add', {'seconds': -100})
        self.assertEqual(status, 200)
        self.assertEqual(data['remaining'], 0)

    def test_add_time_past_total_raises_total(self):
        self._request('POST', '/api/timer', {'minutes': 1, 'seconds': 0})
        status, data = self._request('POST', '/api/timer/add', {'seconds': 120})
        self.assertEqual(data['remaining'], 180)
        self.assertEqual(data['total'], 180)

    def test_add_time_zero_returns_400(self):
        status, data = self._request('POST', '/api/timer/add', {'seconds': 0})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_add_time_missing_field_returns_400(self):
        status, data = self._request('POST', '/api/timer/add', {})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_history_records_completed_session(self):
        self._request('POST', '/api/timer', {'minutes': 0, 'seconds': 2, 'label': 'Tea'})
        self._request('POST', '/api/timer/start')
        self._request('POST', '/api/timer/tick')
        self._request('POST', '/api/timer/tick')  # reaches zero
        status, data = self._request('GET', '/api/timer/history')
        self.assertEqual(status, 200)
        self.assertEqual(data['completed'], 1)
        self.assertEqual(len(data['history']), 1)
        self.assertEqual(data['history'][0]['label'], 'Tea')

    def test_clear_history(self):
        self._request('POST', '/api/timer', {'minutes': 0, 'seconds': 1})
        self._request('POST', '/api/timer/start')
        self._request('POST', '/api/timer/tick')
        status, data = self._request('DELETE', '/api/timer/history')
        self.assertEqual(status, 200)
        self.assertEqual(data['completed'], 0)
        self.assertEqual(data['history'], [])


class CustomPresetTests(CountdownTimerTests):
    def test_create_and_list_custom_preset(self):
        status, data = self._request(
            'POST', '/api/timer/presets',
            {'name': 'workout', 'label': 'Workout', 'seconds': 90})
        self.assertEqual(status, 201)
        self.assertTrue(data['custom'])
        self.assertEqual(data['seconds'], 90)

        status, listing = self._request('GET', '/api/timer/presets')
        names = [p['name'] for p in listing['presets']]
        self.assertIn('workout', names)

    def test_apply_custom_preset(self):
        self._request('POST', '/api/timer/presets',
                      {'name': 'soak', 'label': 'Soak', 'seconds': 200})
        status, data = self._request('POST', '/api/timer/preset', {'name': 'soak'})
        self.assertEqual(status, 200)
        self.assertEqual(data['remaining'], 200)
        self.assertEqual(data['label'], 'Soak')

    def test_create_custom_preset_label_defaults_to_name(self):
        status, data = self._request('POST', '/api/timer/presets',
                                     {'name': 'quick', 'seconds': 45})
        self.assertEqual(status, 201)
        self.assertEqual(data['label'], 'quick')

    def test_create_custom_preset_conflicts_with_builtin(self):
        status, data = self._request('POST', '/api/timer/presets',
                                     {'name': 'pomodoro', 'seconds': 60})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_create_duplicate_custom_preset_returns_400(self):
        self._request('POST', '/api/timer/presets', {'name': 'dup', 'seconds': 60})
        status, data = self._request('POST', '/api/timer/presets',
                                     {'name': 'dup', 'seconds': 90})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_create_custom_preset_invalid_seconds_returns_400(self):
        status, data = self._request('POST', '/api/timer/presets',
                                     {'name': 'bad', 'seconds': 0})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_create_custom_preset_missing_fields_returns_400(self):
        status, data = self._request('POST', '/api/timer/presets', {'name': 'x'})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_create_custom_preset_blank_name_returns_400(self):
        status, data = self._request('POST', '/api/timer/presets',
                                     {'name': '   ', 'seconds': 60})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_delete_custom_preset(self):
        self._request('POST', '/api/timer/presets', {'name': 'gone', 'seconds': 60})
        status, data = self._request('DELETE', '/api/timer/presets/gone')
        self.assertEqual(status, 200)
        self.assertEqual(data['deleted'], 'gone')
        status, listing = self._request('GET', '/api/timer/presets')
        self.assertNotIn('gone', [p['name'] for p in listing['presets']])

    def test_delete_unknown_custom_preset_returns_404(self):
        status, data = self._request('DELETE', '/api/timer/presets/missing')
        self.assertEqual(status, 404)
        self.assertIn('error', data)


class RepeatModeTests(CountdownTimerTests):
    def test_set_with_repeat_records_repeats_left(self):
        status, data = self._request(
            'POST', '/api/timer', {'minutes': 0, 'seconds': 2, 'repeat': 2})
        self.assertEqual(status, 201)
        self.assertEqual(data['repeat'], 2)
        self.assertEqual(data['repeats_left'], 2)

    def test_repeat_auto_restarts_and_keeps_running(self):
        self._request('POST', '/api/timer', {'minutes': 0, 'seconds': 1, 'repeat': 1})
        self._request('POST', '/api/timer/start')
        # First cycle hits zero -> should auto-restart, still running.
        status, data = self._request('POST', '/api/timer/tick')
        self.assertEqual(data['remaining'], 1)
        self.assertTrue(data['running'])
        self.assertEqual(data['repeats_left'], 0)
        self.assertEqual(data['completed'], 1)
        # Second cycle hits zero -> no repeats left, stops.
        status, data = self._request('POST', '/api/timer/tick')
        self.assertEqual(data['remaining'], 0)
        self.assertFalse(data['running'])
        self.assertEqual(data['completed'], 2)

    def test_repeat_completions_all_logged(self):
        self._request('POST', '/api/timer', {'minutes': 0, 'seconds': 1, 'repeat': 1})
        self._request('POST', '/api/timer/start')
        self._request('POST', '/api/timer/tick')
        self._request('POST', '/api/timer/tick')
        status, data = self._request('GET', '/api/timer/history')
        self.assertEqual(data['completed'], 2)
        self.assertEqual(len(data['history']), 2)

    def test_invalid_repeat_returns_400(self):
        status, data = self._request(
            'POST', '/api/timer', {'minutes': 1, 'seconds': 0, 'repeat': 500})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_applying_preset_clears_repeat(self):
        self._request('POST', '/api/timer', {'minutes': 0, 'seconds': 2, 'repeat': 3})
        status, data = self._request('POST', '/api/timer/preset', {'name': 'pomodoro'})
        self.assertEqual(data['repeat'], 0)
        self.assertEqual(data['repeats_left'], 0)


class StatsTests(CountdownTimerTests):
    def test_stats_empty(self):
        status, data = self._request('GET', '/api/timer/stats')
        self.assertEqual(status, 200)
        self.assertEqual(data['sessions'], 0)
        self.assertEqual(data['total_seconds'], 0)
        self.assertEqual(data['total_formatted'], '00:00')
        self.assertEqual(data['average_seconds'], 0)

    def _complete_one(self, seconds):
        self._request('POST', '/api/timer', {'minutes': 0, 'seconds': seconds})
        self._request('POST', '/api/timer/start')
        for _ in range(seconds):
            self._request('POST', '/api/timer/tick')

    def test_stats_aggregate_after_sessions(self):
        self._complete_one(2)
        self._complete_one(4)
        status, data = self._request('GET', '/api/timer/stats')
        self.assertEqual(status, 200)
        self.assertEqual(data['sessions'], 2)
        self.assertEqual(data['total_seconds'], 6)
        self.assertEqual(data['longest_seconds'], 4)
        self.assertEqual(data['average_seconds'], 3)
        self.assertEqual(data['total_formatted'], '00:06')

    def test_stats_reflect_cleared_history(self):
        self._complete_one(2)
        self._request('DELETE', '/api/timer/history')
        status, data = self._request('GET', '/api/timer/stats')
        self.assertEqual(data['sessions'], 0)
        self.assertEqual(data['completed'], 0)


class FinishTimerTests(CountdownTimerTests):
    def test_finish_completes_cycle_immediately(self):
        self._request('POST', '/api/timer', {'minutes': 1, 'seconds': 0, 'label': 'Steep'})
        self._request('POST', '/api/timer/start')
        status, data = self._request('POST', '/api/timer/finish')
        self.assertEqual(status, 200)
        self.assertEqual(data['remaining'], 0)
        self.assertFalse(data['running'])
        self.assertEqual(data['completed'], 1)

    def test_finish_logs_history(self):
        self._request('POST', '/api/timer', {'minutes': 0, 'seconds': 45, 'label': 'Brew'})
        self._request('POST', '/api/timer/finish')
        status, data = self._request('GET', '/api/timer/history')
        self.assertEqual(data['completed'], 1)
        self.assertEqual(len(data['history']), 1)
        self.assertEqual(data['history'][0]['label'], 'Brew')
        # The logged total reflects the configured duration, not zero.
        self.assertEqual(data['history'][0]['total'], 45)

    def test_finish_works_while_paused(self):
        # Skip-to-end is a deliberate action, valid even when not running.
        self._request('POST', '/api/timer', {'minutes': 0, 'seconds': 30})
        status, data = self._request('POST', '/api/timer/finish')
        self.assertEqual(status, 200)
        self.assertEqual(data['remaining'], 0)
        self.assertEqual(data['completed'], 1)

    def test_finish_consumes_one_repeat(self):
        self._request('POST', '/api/timer', {'minutes': 0, 'seconds': 5, 'repeat': 2})
        self._request('POST', '/api/timer/start')
        status, data = self._request('POST', '/api/timer/finish')
        self.assertEqual(status, 200)
        # One cycle completed; an interval repeat rolled into a fresh cycle.
        self.assertEqual(data['completed'], 1)
        self.assertEqual(data['repeats_left'], 1)
        self.assertEqual(data['remaining'], 5)
        self.assertTrue(data['running'])

    def test_finish_at_zero_returns_400(self):
        self._request('POST', '/api/timer', {'minutes': 0, 'seconds': 1})
        self._request('POST', '/api/timer/start')
        self._request('POST', '/api/timer/tick')  # reaches zero
        status, data = self._request('POST', '/api/timer/finish')
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_finish_then_stats(self):
        self._request('POST', '/api/timer', {'minutes': 0, 'seconds': 10})
        self._request('POST', '/api/timer/finish')
        status, data = self._request('GET', '/api/timer/stats')
        self.assertEqual(data['sessions'], 1)
        self.assertEqual(data['total_seconds'], 10)


class UpdateCustomPresetTests(CountdownTimerTests):
    def _make(self, name='nap', label='Nap', seconds=600):
        return self._request('POST', '/api/timer/presets',
                             {'name': name, 'label': label, 'seconds': seconds})

    def test_update_seconds(self):
        self._make()
        status, data = self._request('PUT', '/api/timer/presets/nap', {'seconds': 1200})
        self.assertEqual(status, 200)
        self.assertEqual(data['seconds'], 1200)
        self.assertEqual(data['label'], 'Nap')  # unchanged
        self.assertTrue(data['custom'])
        # Applying it now uses the new duration.
        status, applied = self._request('POST', '/api/timer/preset', {'name': 'nap'})
        self.assertEqual(applied['remaining'], 1200)

    def test_update_label(self):
        self._make()
        status, data = self._request('PUT', '/api/timer/presets/nap', {'label': 'Power Nap'})
        self.assertEqual(status, 200)
        self.assertEqual(data['label'], 'Power Nap')
        self.assertEqual(data['seconds'], 600)  # unchanged

    def test_update_both_fields(self):
        self._make()
        status, data = self._request('PUT', '/api/timer/presets/nap',
                                     {'label': 'Long Nap', 'seconds': 1800})
        self.assertEqual(status, 200)
        self.assertEqual(data['label'], 'Long Nap')
        self.assertEqual(data['seconds'], 1800)

    def test_update_unknown_preset_returns_404(self):
        status, data = self._request('PUT', '/api/timer/presets/ghost', {'seconds': 60})
        self.assertEqual(status, 404)
        self.assertIn('error', data)

    def test_update_invalid_seconds_returns_400(self):
        self._make()
        status, data = self._request('PUT', '/api/timer/presets/nap', {'seconds': 0})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_update_blank_label_returns_400(self):
        self._make()
        status, data = self._request('PUT', '/api/timer/presets/nap', {'label': '   '})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_update_no_fields_returns_400(self):
        self._make()
        status, data = self._request('PUT', '/api/timer/presets/nap', {})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_update_unknown_route_returns_404(self):
        status, data = self._request('PUT', '/api/nope', {'seconds': 60})
        self.assertEqual(status, 404)
        self.assertIn('error', data)


class LabelStatsTests(CountdownTimerTests):
    def _complete(self, seconds, label=''):
        body = {'minutes': 0, 'seconds': seconds}
        if label:
            body['label'] = label
        self._request('POST', '/api/timer', body)
        self._request('POST', '/api/timer/finish')

    def test_label_stats_empty(self):
        status, data = self._request('GET', '/api/timer/stats/labels')
        self.assertEqual(status, 200)
        self.assertEqual(data['labels'], [])

    def test_label_stats_groups_by_label(self):
        self._complete(10, 'Focus')
        self._complete(20, 'Focus')
        self._complete(5, 'Tea')
        status, data = self._request('GET', '/api/timer/stats/labels')
        self.assertEqual(status, 200)
        groups = {g['label']: g for g in data['labels']}
        self.assertEqual(groups['Focus']['sessions'], 2)
        self.assertEqual(groups['Focus']['total_seconds'], 30)
        self.assertEqual(groups['Focus']['longest_seconds'], 20)
        self.assertEqual(groups['Focus']['average_seconds'], 15)
        self.assertEqual(groups['Tea']['sessions'], 1)
        self.assertEqual(groups['Tea']['total_seconds'], 5)

    def test_label_stats_sorted_by_total_desc(self):
        self._complete(5, 'Small')
        self._complete(40, 'Big')
        status, data = self._request('GET', '/api/timer/stats/labels')
        self.assertEqual(data['labels'][0]['label'], 'Big')

    def test_label_stats_unlabeled_bucket(self):
        self._complete(7)  # no label
        status, data = self._request('GET', '/api/timer/stats/labels')
        self.assertEqual(data['labels'][0]['label'], '(unlabeled)')
        self.assertEqual(data['labels'][0]['sessions'], 1)


class HistoryCsvTests(CountdownTimerTests):
    def _raw_get(self, path):
        conn = self._conn()
        conn.request('GET', path)
        resp = conn.getresponse()
        body = resp.read().decode('utf-8')
        ctype = resp.getheader('Content-Type')
        disp = resp.getheader('Content-Disposition')
        status = resp.status
        conn.close()
        return status, body, ctype, disp

    def test_csv_header_only_when_empty(self):
        status, body, ctype, disp = self._raw_get('/api/timer/history.csv')
        self.assertEqual(status, 200)
        self.assertIn('text/csv', ctype)
        lines = body.strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn('sequence', lines[0])
        self.assertIn('formatted', lines[0])

    def test_csv_content_disposition_attachment(self):
        status, body, ctype, disp = self._raw_get('/api/timer/history.csv')
        self.assertIn('attachment', disp)
        self.assertIn('timer-history.csv', disp)

    def test_csv_rows_after_sessions(self):
        self._request('POST', '/api/timer', {'minutes': 1, 'seconds': 0, 'label': 'Run'})
        self._request('POST', '/api/timer/finish')
        status, body, ctype, disp = self._raw_get('/api/timer/history.csv')
        import csv as _csv
        import io as _io
        rows = list(_csv.reader(_io.StringIO(body)))
        self.assertEqual(rows[0][0], 'sequence')
        self.assertEqual(len(rows), 2)
        # sequence, label, total_seconds, formatted, minutes, seconds
        self.assertEqual(rows[1][1], 'Run')
        self.assertEqual(rows[1][2], '60')
        self.assertEqual(rows[1][3], '01:00')


class PresetUsageTests(CountdownTimerTests):
    """Applying a preset is counted; popularity ranks by those counts."""

    def test_listing_reports_applied_count_zero_initially(self):
        status, data = self._request('GET', '/api/timer/presets')
        self.assertEqual(status, 200)
        for p in data['presets']:
            self.assertEqual(p['applied'], 0)

    def test_applying_preset_increments_usage(self):
        self._request('POST', '/api/timer/preset', {'name': 'pomodoro'})
        self._request('POST', '/api/timer/preset', {'name': 'pomodoro'})
        self._request('POST', '/api/timer/preset', {'name': 'five-minutes'})
        status, data = self._request('GET', '/api/timer/presets')
        by_name = {p['name']: p for p in data['presets']}
        self.assertEqual(by_name['pomodoro']['applied'], 2)
        self.assertEqual(by_name['five-minutes']['applied'], 1)
        self.assertEqual(by_name['ten-minutes']['applied'], 0)

    def test_custom_preset_usage_tracked(self):
        self._request('POST', '/api/timer/presets', {'name': 'soak', 'seconds': 90})
        self._request('POST', '/api/timer/preset', {'name': 'soak'})
        status, data = self._request('GET', '/api/timer/presets')
        by_name = {p['name']: p for p in data['presets']}
        self.assertEqual(by_name['soak']['applied'], 1)

    def test_popular_endpoint_orders_by_usage(self):
        for _ in range(3):
            self._request('POST', '/api/timer/preset', {'name': 'ten-minutes'})
        self._request('POST', '/api/timer/preset', {'name': 'pomodoro'})
        status, data = self._request('GET', '/api/timer/presets/popular')
        self.assertEqual(status, 200)
        names = [p['name'] for p in data['presets']]
        # Most-applied first, then the single-applied one.
        self.assertEqual(names[0], 'ten-minutes')
        self.assertEqual(names[1], 'pomodoro')
        # Every preset is still present (unapplied ones sort to the end).
        self.assertEqual(len(names), len(set(names)))
        self.assertIn('one-minute', names)

    def test_popular_ties_break_alphabetically(self):
        # No preset applied yet -> all tie at 0 -> alphabetical by name.
        status, data = self._request('GET', '/api/timer/presets/popular')
        names = [p['name'] for p in data['presets']]
        self.assertEqual(names, sorted(names))

    def test_applying_unknown_preset_does_not_count(self):
        self._request('POST', '/api/timer/preset', {'name': 'nope'})
        status, data = self._request('GET', '/api/timer/presets')
        self.assertTrue(all(p['applied'] == 0 for p in data['presets']))


class HistoryFilterTests(CountdownTimerTests):
    def _complete(self, seconds, label=''):
        body = {'minutes': 0, 'seconds': seconds}
        if label:
            body['label'] = label
        self._request('POST', '/api/timer', body)
        self._request('POST', '/api/timer/finish')

    def test_unfiltered_history_unchanged_shape(self):
        self._complete(5, 'Focus')
        status, data = self._request('GET', '/api/timer/history')
        self.assertEqual(status, 200)
        self.assertEqual(data['completed'], 1)
        self.assertEqual(len(data['history']), 1)
        # No filter -> no filter metadata keys.
        self.assertNotIn('label', data)
        self.assertNotIn('count', data)

    def test_filter_by_label(self):
        self._complete(5, 'Focus')
        self._complete(10, 'Focus')
        self._complete(3, 'Tea')
        status, data = self._request('GET', '/api/timer/history?label=Focus')
        self.assertEqual(status, 200)
        self.assertEqual(data['label'], 'Focus')
        self.assertEqual(data['count'], 2)
        self.assertTrue(all(h['label'] == 'Focus' for h in data['history']))
        # completed still reflects ALL completions, not just the filtered ones.
        self.assertEqual(data['completed'], 3)

    def test_filter_no_matches_returns_empty(self):
        self._complete(5, 'Focus')
        status, data = self._request('GET', '/api/timer/history?label=Ghost')
        self.assertEqual(data['count'], 0)
        self.assertEqual(data['history'], [])

    def test_filter_unlabeled_sentinel(self):
        self._complete(7)            # no label
        self._complete(9, 'Named')
        status, data = self._request('GET', '/api/timer/history?label=(unlabeled)')
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['history'][0]['total'], 7)


class GoalTests(CountdownTimerTests):
    def _complete(self, seconds, label=''):
        body = {'minutes': 0, 'seconds': seconds}
        if label:
            body['label'] = label
        self._request('POST', '/api/timer', body)
        self._request('POST', '/api/timer/finish')

    def test_goal_absent_by_default(self):
        status, data = self._request('GET', '/api/timer/goal')
        self.assertEqual(status, 200)
        self.assertEqual(data['target'], 0)
        self.assertFalse(data['met'])
        self.assertEqual(data['percent'], 0)

    def test_set_goal(self):
        status, data = self._request('POST', '/api/timer/goal', {'seconds': 100})
        self.assertEqual(status, 201)
        self.assertEqual(data['target'], 100)
        self.assertEqual(data['target_formatted'], '01:40')
        self.assertEqual(data['achieved'], 0)
        self.assertEqual(data['remaining'], 100)
        self.assertFalse(data['met'])

    def test_goal_progress_tracks_completed_sessions(self):
        self._request('POST', '/api/timer/goal', {'seconds': 100})
        self._complete(30)
        status, data = self._request('GET', '/api/timer/goal')
        self.assertEqual(data['achieved'], 30)
        self.assertEqual(data['remaining'], 70)
        self.assertEqual(data['percent'], 30)
        self.assertFalse(data['met'])

    def test_goal_met_when_reached(self):
        self._request('POST', '/api/timer/goal', {'seconds': 40})
        self._complete(25)
        self._complete(20)  # total 45 >= 40
        status, data = self._request('GET', '/api/timer/goal')
        self.assertTrue(data['met'])
        self.assertEqual(data['remaining'], 0)
        # percent can exceed 100 once the goal is surpassed.
        self.assertGreaterEqual(data['percent'], 100)

    def test_clearing_history_resets_goal_progress(self):
        self._request('POST', '/api/timer/goal', {'seconds': 100})
        self._complete(30)
        self._request('DELETE', '/api/timer/history')
        status, data = self._request('GET', '/api/timer/goal')
        self.assertEqual(data['achieved'], 0)
        self.assertEqual(data['target'], 100)  # the goal itself survives

    def test_clear_goal(self):
        self._request('POST', '/api/timer/goal', {'seconds': 100})
        status, data = self._request('DELETE', '/api/timer/goal')
        self.assertEqual(status, 200)
        self.assertEqual(data['target'], 0)
        status, data = self._request('GET', '/api/timer/goal')
        self.assertEqual(data['target'], 0)

    def test_set_goal_invalid_returns_400(self):
        status, data = self._request('POST', '/api/timer/goal', {'seconds': 0})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_set_goal_above_max_returns_400(self):
        status, data = self._request('POST', '/api/timer/goal',
                                     {'seconds': GOAL_MAX + 1})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_set_goal_missing_field_returns_400(self):
        status, data = self._request('POST', '/api/timer/goal', {})
        self.assertEqual(status, 400)
        self.assertIn('error', data)


class SingleHistoryEntryTests(CountdownTimerTests):
    """Manage individual completed-session records (delete / relabel one)."""

    def _complete(self, seconds, label=''):
        body = {'minutes': 0, 'seconds': seconds}
        if label:
            body['label'] = label
        self._request('POST', '/api/timer', body)
        self._request('POST', '/api/timer/finish')

    def test_delete_single_entry(self):
        self._complete(5, 'Keep')
        self._complete(10, 'Drop')   # sequence 2
        status, data = self._request('DELETE', '/api/timer/history/2')
        self.assertEqual(status, 200)
        self.assertEqual(data['deleted'], 2)
        status, hist = self._request('GET', '/api/timer/history')
        self.assertEqual(len(hist['history']), 1)
        self.assertEqual(hist['history'][0]['label'], 'Keep')

    def test_delete_single_entry_keeps_lifetime_completed(self):
        # completed is a lifetime counter: deleting a retained record does not
        # rewind it, but stats/goal (derived from kept rows) drop the session.
        self._complete(5)
        self._complete(10)  # sequence 2
        self._request('DELETE', '/api/timer/history/2')
        status, hist = self._request('GET', '/api/timer/history')
        self.assertEqual(hist['completed'], 2)
        status, stats = self._request('GET', '/api/timer/stats')
        self.assertEqual(stats['sessions'], 1)
        self.assertEqual(stats['total_seconds'], 5)

    def test_delete_unknown_entry_returns_404(self):
        self._complete(5)
        status, data = self._request('DELETE', '/api/timer/history/99')
        self.assertEqual(status, 404)
        self.assertIn('error', data)

    def test_delete_entry_invalid_sequence_returns_404(self):
        status, data = self._request('DELETE', '/api/timer/history/abc')
        self.assertEqual(status, 404)
        self.assertIn('error', data)

    def test_delete_entry_reduces_goal_progress(self):
        self._request('POST', '/api/timer/goal', {'seconds': 100})
        self._complete(30)
        self._complete(40)  # sequence 2
        self._request('DELETE', '/api/timer/history/2')
        status, goal = self._request('GET', '/api/timer/goal')
        self.assertEqual(goal['achieved'], 30)

    def test_relabel_single_entry(self):
        self._complete(5, 'Old')
        status, data = self._request('PUT', '/api/timer/history/1', {'label': 'New'})
        self.assertEqual(status, 200)
        self.assertEqual(data['label'], 'New')
        status, hist = self._request('GET', '/api/timer/history')
        self.assertEqual(hist['history'][0]['label'], 'New')

    def test_relabel_flows_into_label_stats(self):
        self._complete(10, 'Wrong')
        self._request('PUT', '/api/timer/history/1', {'label': 'Right'})
        status, data = self._request('GET', '/api/timer/stats/labels')
        labels = [g['label'] for g in data['labels']]
        self.assertIn('Right', labels)
        self.assertNotIn('Wrong', labels)

    def test_relabel_to_empty_unlabels(self):
        self._complete(7, 'Temp')
        status, data = self._request('PUT', '/api/timer/history/1', {'label': '   '})
        self.assertEqual(status, 200)
        self.assertEqual(data['label'], '')
        status, hist = self._request('GET', '/api/timer/history?label=(unlabeled)')
        self.assertEqual(hist['count'], 1)

    def test_relabel_unknown_entry_returns_404(self):
        status, data = self._request('PUT', '/api/timer/history/42', {'label': 'X'})
        self.assertEqual(status, 404)
        self.assertIn('error', data)

    def test_relabel_missing_label_returns_400(self):
        self._complete(5)
        status, data = self._request('PUT', '/api/timer/history/1', {})
        self.assertEqual(status, 400)
        self.assertIn('error', data)

    def test_relabel_non_string_label_returns_400(self):
        self._complete(5)
        status, data = self._request('PUT', '/api/timer/history/1', {'label': 123})
        self.assertEqual(status, 400)
        self.assertIn('error', data)


class StatsEnrichmentTests(CountdownTimerTests):
    """Shortest and median join the stats payload without disturbing the rest."""

    def _complete_one(self, seconds):
        self._request('POST', '/api/timer', {'minutes': 0, 'seconds': seconds})
        self._request('POST', '/api/timer/finish')

    def test_empty_stats_have_zero_shortest_and_median(self):
        status, data = self._request('GET', '/api/timer/stats')
        self.assertEqual(status, 200)
        self.assertEqual(data['shortest_seconds'], 0)
        self.assertEqual(data['shortest_formatted'], '00:00')
        self.assertEqual(data['median_seconds'], 0)
        self.assertEqual(data['median_formatted'], '00:00')

    def test_shortest_is_minimum_duration(self):
        self._complete_one(30)
        self._complete_one(5)
        self._complete_one(20)
        status, data = self._request('GET', '/api/timer/stats')
        self.assertEqual(data['shortest_seconds'], 5)
        self.assertEqual(data['shortest_formatted'], '00:05')

    def test_median_odd_count(self):
        for s in (10, 30, 20):
            self._complete_one(s)
        status, data = self._request('GET', '/api/timer/stats')
        self.assertEqual(data['median_seconds'], 20)

    def test_median_even_count_rounds(self):
        for s in (10, 20, 30, 50):
            self._complete_one(s)
        # middle two are 20 and 30 -> mean 25
        status, data = self._request('GET', '/api/timer/stats')
        self.assertEqual(data['median_seconds'], 25)


class FavoritePresetTests(CountdownTimerTests):
    def test_presets_not_favorite_by_default(self):
        status, data = self._request('GET', '/api/timer/presets')
        self.assertEqual(status, 200)
        self.assertTrue(all(p['favorite'] is False for p in data['presets']))

    def test_toggle_builtin_favorite(self):
        status, data = self._request('POST', '/api/timer/presets/pomodoro/favorite')
        self.assertEqual(status, 200)
        self.assertEqual(data['name'], 'pomodoro')
        self.assertTrue(data['favorite'])
        status, listing = self._request('GET', '/api/timer/presets')
        by_name = {p['name']: p for p in listing['presets']}
        self.assertTrue(by_name['pomodoro']['favorite'])
        self.assertFalse(by_name['five-minutes']['favorite'])

    def test_toggle_is_reversible(self):
        self._request('POST', '/api/timer/presets/pomodoro/favorite')
        status, data = self._request('POST', '/api/timer/presets/pomodoro/favorite')
        self.assertEqual(status, 200)
        self.assertFalse(data['favorite'])

    def test_favorite_custom_preset(self):
        self._request('POST', '/api/timer/presets', {'name': 'soak', 'seconds': 90})
        status, data = self._request('POST', '/api/timer/presets/soak/favorite')
        self.assertEqual(status, 200)
        self.assertTrue(data['favorite'])

    def test_favorites_listing(self):
        self._request('POST', '/api/timer/presets/pomodoro/favorite')
        self._request('POST', '/api/timer/presets/one-minute/favorite')
        status, data = self._request('GET', '/api/timer/presets/favorites')
        self.assertEqual(status, 200)
        names = sorted(p['name'] for p in data['presets'])
        self.assertEqual(names, ['one-minute', 'pomodoro'])
        self.assertTrue(all(p['favorite'] for p in data['presets']))

    def test_favorites_listing_empty_by_default(self):
        status, data = self._request('GET', '/api/timer/presets/favorites')
        self.assertEqual(status, 200)
        self.assertEqual(data['presets'], [])

    def test_unfavorite_removes_from_listing(self):
        self._request('POST', '/api/timer/presets/pomodoro/favorite')
        self._request('POST', '/api/timer/presets/pomodoro/favorite')  # toggle off
        status, data = self._request('GET', '/api/timer/presets/favorites')
        self.assertEqual(data['presets'], [])

    def test_favorite_unknown_preset_returns_404(self):
        status, data = self._request('POST', '/api/timer/presets/ghost/favorite')
        self.assertEqual(status, 404)
        self.assertIn('error', data)

    def test_deleting_custom_preset_drops_it_from_favorites_listing(self):
        self._request('POST', '/api/timer/presets', {'name': 'gone', 'seconds': 60})
        self._request('POST', '/api/timer/presets/gone/favorite')
        self._request('DELETE', '/api/timer/presets/gone')
        status, data = self._request('GET', '/api/timer/presets/favorites')
        names = [p['name'] for p in data['presets']]
        self.assertNotIn('gone', names)


if __name__ == '__main__':
    unittest.main()
