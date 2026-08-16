"""Unit + integration tests for the Snake & Ladder game (stdlib only).

Run with:  python3 -m unittest -v

Covers the pure game engine (square_kind, roll_die, resolve_move,
validate_board, Game), JSON persistence, and the live HTTP API.
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import server


# ----------------------------------------------------------------------
# Pure board helpers
# ----------------------------------------------------------------------
class TestSquareKind(unittest.TestCase):
    def test_ladder_square(self):
        self.assertEqual(server.square_kind(1), 'ladder')

    def test_snake_square(self):
        self.assertEqual(server.square_kind(16), 'snake')

    def test_plain_square(self):
        self.assertIsNone(server.square_kind(2))

    def test_custom_board(self):
        self.assertEqual(server.square_kind(3, ladders={3: 9}, snakes={}), 'ladder')
        self.assertEqual(server.square_kind(7, ladders={}, snakes={7: 2}), 'snake')
        self.assertIsNone(server.square_kind(3, ladders={}, snakes={}))


class TestRollDie(unittest.TestCase):
    def test_in_range(self):
        for _ in range(200):
            self.assertIn(server.roll_die(), range(1, 7))

    def test_injectable_rng(self):
        class FixedRng:
            def randint(self, a, b):
                return b
        self.assertEqual(server.roll_die(FixedRng()), 6)


class TestResolveMove(unittest.TestCase):
    def test_plain_move(self):
        out = server.resolve_move(0, 3)
        self.assertEqual(out['to'], 3)
        self.assertEqual(out['event'], 'move')
        self.assertFalse(out['won'])

    def test_landing_on_ladder_climbs(self):
        out = server.resolve_move(0, 1)  # square 1 -> 38
        self.assertEqual(out['after_dice'], 1)
        self.assertEqual(out['to'], 38)
        self.assertEqual(out['event'], 'ladder')

    def test_landing_on_snake_descends(self):
        out = server.resolve_move(10, 6)  # square 16 -> 6
        self.assertEqual(out['after_dice'], 16)
        self.assertEqual(out['to'], 6)
        self.assertEqual(out['event'], 'snake')

    def test_exact_win(self):
        out = server.resolve_move(94, 6)  # lands exactly on 100
        self.assertEqual(out['to'], 100)
        self.assertTrue(out['won'])

    def test_overshoot_forfeits(self):
        out = server.resolve_move(98, 5)  # would pass 100
        self.assertEqual(out['to'], 98)
        self.assertEqual(out['event'], 'overshoot')
        self.assertFalse(out['won'])

    def test_invalid_roll_raises(self):
        with self.assertRaises(ValueError):
            server.resolve_move(0, 7)
        with self.assertRaises(ValueError):
            server.resolve_move(0, 0)

    def test_custom_board_resolution(self):
        out = server.resolve_move(0, 2, ladders={2: 5}, snakes={}, size=10)
        self.assertEqual(out['to'], 5)
        self.assertEqual(out['event'], 'ladder')

    def test_custom_board_exact_win(self):
        out = server.resolve_move(8, 2, ladders={}, snakes={}, size=10)
        self.assertTrue(out['won'])


# ----------------------------------------------------------------------
# Board validation
# ----------------------------------------------------------------------
class TestValidateBoard(unittest.TestCase):
    def test_valid_board_normalizes_keys(self):
        ladders, snakes, size = server.validate_board({'2': '8'}, {'9': '3'}, '10')
        self.assertEqual(ladders, {2: 8})
        self.assertEqual(snakes, {9: 3})
        self.assertEqual(size, 10)

    def test_size_must_be_integer(self):
        with self.assertRaises(ValueError):
            server.validate_board({}, {}, 'abc')

    def test_size_minimum(self):
        with self.assertRaises(ValueError):
            server.validate_board({}, {}, 1)

    def test_entries_must_be_dict(self):
        with self.assertRaises(ValueError):
            server.validate_board([1, 2], {}, 10)

    def test_entries_must_be_integers(self):
        with self.assertRaises(ValueError):
            server.validate_board({'x': 'y'}, {}, 10)

    def test_squares_within_range(self):
        with self.assertRaises(ValueError):
            server.validate_board({5: 99}, {}, 10)

    def test_cannot_start_on_final_square(self):
        with self.assertRaises(ValueError):
            server.validate_board({10: 5}, {}, 10)

    def test_ladder_must_lead_up(self):
        with self.assertRaises(ValueError):
            server.validate_board({8: 2}, {}, 10)

    def test_snake_must_lead_down(self):
        with self.assertRaises(ValueError):
            server.validate_board({}, {2: 8}, 10)

    def test_no_overlap_between_ladder_and_snake(self):
        with self.assertRaises(ValueError):
            server.validate_board({5: 9}, {5: 1}, 10)

    def test_classic_board_is_valid(self):
        ladders, snakes, size = server.validate_board(
            server.LADDERS, server.SNAKES, server.BOARD_SIZE)
        self.assertEqual(size, 100)
        self.assertEqual(ladders[1], 38)
        self.assertEqual(snakes[16], 6)


# ----------------------------------------------------------------------
# Game engine
# ----------------------------------------------------------------------
class FixedRng:
    """Deterministic RNG yielding a scripted sequence of die values."""

    def __init__(self, values):
        self.values = list(values)
        self.i = 0

    def randint(self, a, b):
        v = self.values[self.i % len(self.values)]
        self.i += 1
        return v


class TestGameSetup(unittest.TestCase):
    def test_requires_two_players(self):
        with self.assertRaises(ValueError):
            server.Game(['solo'])

    def test_rejects_more_than_six(self):
        with self.assertRaises(ValueError):
            server.Game(['a', 'b', 'c', 'd', 'e', 'f', 'g'])

    def test_rejects_duplicate_names(self):
        with self.assertRaises(ValueError):
            server.Game(['amy', 'amy'])

    def test_strips_blank_names(self):
        game = server.Game([' Amy ', '', '  ', 'Bob'])
        self.assertEqual([p['name'] for p in game.players], ['Amy', 'Bob'])

    def test_players_start_at_zero_with_counters(self):
        game = server.Game(['Amy', 'Bob'])
        for p in game.players:
            self.assertEqual(p['position'], 0)
            self.assertEqual(p['rolls'], 0)
            self.assertEqual(p['ladders_climbed'], 0)
            self.assertEqual(p['snakes_bitten'], 0)

    def test_default_board_is_classic(self):
        game = server.Game(['Amy', 'Bob'])
        self.assertEqual(game.size, 100)
        self.assertEqual(game.ladders[1], 38)


class TestGamePlay(unittest.TestCase):
    def test_turn_order_advances(self):
        game = server.Game(['Amy', 'Bob'])
        self.assertEqual(game.to_dict()['current_player'], 'Amy')
        game.roll(forced=3)
        self.assertEqual(game.to_dict()['current_player'], 'Bob')

    def test_rolling_six_grants_extra_turn(self):
        game = server.Game(['Amy', 'Bob'])
        rec = game.roll(forced=6)  # Amy moves 0 -> 6, keeps turn
        self.assertTrue(rec['extra_turn'])
        self.assertEqual(game.current, 0)

    def test_counters_track_rolls_and_ladders(self):
        game = server.Game(['Amy', 'Bob'])
        game.roll(forced=1)  # Amy lands on ladder 1 -> 38
        amy = game.players[0]
        self.assertEqual(amy['position'], 38)
        self.assertEqual(amy['rolls'], 1)
        self.assertEqual(amy['ladders_climbed'], 1)

    def test_counter_tracks_snake(self):
        game = server.Game(['Amy', 'Bob'])
        game.players[0]['position'] = 10
        game.roll(forced=6)  # 16 -> 6 (snake)
        self.assertEqual(game.players[0]['position'], 6)
        self.assertEqual(game.players[0]['snakes_bitten'], 1)

    def test_win_detection_and_freeze(self):
        game = server.Game(['Amy', 'Bob'])
        game.players[0]['position'] = 94
        rec = game.roll(forced=6)  # exact 100
        self.assertTrue(rec['won'])
        self.assertEqual(game.winner, 'Amy')
        self.assertTrue(game.to_dict()['finished'])
        with self.assertRaises(RuntimeError):
            game.roll(forced=1)

    def test_stats_aggregate(self):
        game = server.Game(['Amy', 'Bob'])
        game.roll(forced=3)
        game.roll(forced=2)
        stats = game.stats()
        self.assertEqual(stats['total_rolls'], 2)
        self.assertEqual(stats['moves'], 2)

    def test_standings_rank_by_position(self):
        game = server.Game(['Amy', 'Bob'])
        game.players[0]['position'] = 50
        game.players[1]['position'] = 70
        standings = game.standings()
        self.assertEqual(standings[0]['name'], 'Bob')
        self.assertEqual(standings[0]['rank'], 1)
        self.assertEqual(standings[1]['name'], 'Amy')

    def test_random_game_uses_injected_rng(self):
        game = server.Game(['Amy', 'Bob'], rng=FixedRng([3]))
        rec = game.roll()
        self.assertEqual(rec['rolled'], 3)


class TestGameUndo(unittest.TestCase):
    def test_undo_reverts_position_and_turn(self):
        game = server.Game(['Amy', 'Bob'])
        game.roll(forced=3)  # Amy 0 -> 3, turn to Bob
        self.assertEqual(game.players[0]['position'], 3)
        game.undo()
        self.assertEqual(game.players[0]['position'], 0)
        self.assertEqual(game.players[0]['rolls'], 0)
        self.assertEqual(game.current, 0)
        self.assertEqual(game.history, [])

    def test_undo_reverts_a_win(self):
        game = server.Game(['Amy', 'Bob'])
        game.players[0]['position'] = 94
        game.roll(forced=6)
        self.assertEqual(game.winner, 'Amy')
        game.undo()
        self.assertIsNone(game.winner)
        self.assertFalse(game.to_dict()['finished'])

    def test_undo_without_history_raises(self):
        game = server.Game(['Amy', 'Bob'])
        with self.assertRaises(RuntimeError):
            game.undo()

    def test_can_undo_flag(self):
        game = server.Game(['Amy', 'Bob'])
        self.assertFalse(game.to_dict()['can_undo'])
        game.roll(forced=2)
        self.assertTrue(game.to_dict()['can_undo'])


class TestCustomBoardGame(unittest.TestCase):
    def test_small_custom_board_win(self):
        game = server.Game(['Amy', 'Bob'], ladders={2: 5}, snakes={8: 3}, size=10)
        self.assertEqual(game.size, 10)
        game.players[0]['position'] = 8
        rec = game.roll(forced=2)  # exact 10 wins
        self.assertTrue(rec['won'])

    def test_custom_ladder_applies(self):
        game = server.Game(['Amy', 'Bob'], ladders={2: 9}, snakes={}, size=20)
        rec = game.roll(forced=2)
        self.assertEqual(rec['to'], 9)
        self.assertEqual(rec['event'], 'ladder')

    def test_invalid_custom_board_rejected(self):
        with self.assertRaises(ValueError):
            server.Game(['Amy', 'Bob'], ladders={5: 2}, snakes={}, size=10)


class TestSerialization(unittest.TestCase):
    def test_round_trip_preserves_state(self):
        game = server.Game(['Amy', 'Bob'])
        game.roll(forced=1)  # ladder climb, mutates counters
        data = game.to_dict()
        restored = server.Game.from_dict(data)
        self.assertEqual(restored.players[0]['position'], 38)
        self.assertEqual(restored.players[0]['ladders_climbed'], 1)
        self.assertEqual(restored.current, game.current)

    def test_round_trip_preserves_custom_board(self):
        game = server.Game(['Amy', 'Bob'], ladders={2: 9}, snakes={8: 1}, size=12)
        restored = server.Game.from_dict(game.to_dict())
        self.assertEqual(restored.size, 12)
        self.assertEqual(restored.ladders[2], 9)


# ----------------------------------------------------------------------
# Persistence helpers
# ----------------------------------------------------------------------
class TestPersistence(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.remove(self.path)
        self._orig = server.STATE_PATH
        server.STATE_PATH = self.path

    def tearDown(self):
        server.STATE_PATH = self._orig
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_save_and_load_round_trip(self):
        game = server.Game(['Amy', 'Bob'])
        game.roll(forced=3)
        server.save_game(game)
        loaded = server.load_game()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.players[0]['position'], 3)

    def test_load_missing_returns_none(self):
        self.assertIsNone(server.load_game())

    def test_load_corrupt_returns_none(self):
        with open(self.path, 'w') as f:
            f.write('{ not json')
        self.assertIsNone(server.load_game())

    def test_clear_removes_file(self):
        server.save_game(server.Game(['Amy', 'Bob']))
        self.assertTrue(os.path.exists(self.path))
        server.clear_game()
        self.assertFalse(os.path.exists(self.path))


# ----------------------------------------------------------------------
# HTTP API (live server on an ephemeral port)
# ----------------------------------------------------------------------
class TestHttpApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.state_path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.remove(cls.state_path)
        cls._orig_state = server.STATE_PATH
        server.STATE_PATH = cls.state_path

        fd, cls.lb_path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.remove(cls.lb_path)
        cls._orig_lb = server.LEADERBOARD_PATH
        server.LEADERBOARD_PATH = cls.lb_path

        cls.httpd = server.make_server(0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        server.STATE_PATH = cls._orig_state
        server.LEADERBOARD_PATH = cls._orig_lb
        if os.path.exists(cls.state_path):
            os.remove(cls.state_path)
        if os.path.exists(cls.lb_path):
            os.remove(cls.lb_path)

    def setUp(self):
        self._post('/api/game/reset', {})

    def _url(self, path):
        return 'http://127.0.0.1:%d%s' % (self.port, path)

    def _post(self, path, body):
        data = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(self._url(path), data=data, method='POST',
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode('utf-8'))

    def _get(self, path):
        try:
            with urllib.request.urlopen(self._url(path)) as resp:
                return resp.status, resp.read().decode('utf-8')
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode('utf-8')

    def _get_json(self, path):
        status, body = self._get(path)
        return status, json.loads(body)

    # -- routes ----------------------------------------------------------
    def test_index_served(self):
        status, body = self._get('/')
        self.assertEqual(status, 200)
        self.assertIn('<html', body.lower())

    def test_board_endpoint(self):
        status, payload = self._get_json('/api/board')
        self.assertEqual(status, 200)
        self.assertEqual(payload['size'], 100)
        self.assertIn('1', {str(k) for k in payload['ladders']})

    def test_new_game_then_get(self):
        status, payload = self._post('/api/game/new', {'players': ['Amy', 'Bob']})
        self.assertEqual(status, 200)
        self.assertEqual(payload['current_player'], 'Amy')
        status, state = self._get_json('/api/game')
        self.assertEqual(status, 200)
        self.assertEqual(len(state['players']), 2)

    def test_new_game_rejects_one_player(self):
        status, payload = self._post('/api/game/new', {'players': ['Amy']})
        self.assertEqual(status, 400)
        self.assertIn('error', payload)

    def test_new_game_rejects_non_list(self):
        status, payload = self._post('/api/game/new', {'players': 'Amy'})
        self.assertEqual(status, 400)

    def test_roll_forced_moves_player(self):
        self._post('/api/game/new', {'players': ['Amy', 'Bob']})
        status, payload = self._post('/api/game/roll', {'roll': 3})
        self.assertEqual(status, 200)
        self.assertEqual(payload['move']['to'], 3)
        self.assertEqual(payload['state']['current_player'], 'Bob')

    def test_roll_rejects_out_of_range(self):
        self._post('/api/game/new', {'players': ['Amy', 'Bob']})
        status, payload = self._post('/api/game/roll', {'roll': 9})
        self.assertEqual(status, 400)

    def test_roll_without_game_404(self):
        status, payload = self._post('/api/game/roll', {'roll': 3})
        self.assertEqual(status, 404)

    def test_undo_endpoint(self):
        self._post('/api/game/new', {'players': ['Amy', 'Bob']})
        self._post('/api/game/roll', {'roll': 3})
        status, payload = self._post('/api/game/undo', {})
        self.assertEqual(status, 200)
        self.assertEqual(payload['state']['players'][0]['position'], 0)

    def test_undo_with_nothing_conflicts(self):
        self._post('/api/game/new', {'players': ['Amy', 'Bob']})
        status, payload = self._post('/api/game/undo', {})
        self.assertEqual(status, 409)

    def test_undo_without_game_404(self):
        status, payload = self._post('/api/game/undo', {})
        self.assertEqual(status, 404)

    def test_custom_board_via_api(self):
        status, payload = self._post('/api/game/new', {
            'players': ['Amy', 'Bob'],
            'ladders': {'2': 9},
            'snakes': {'8': 1},
            'size': 12,
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload['board']['size'], 12)

    def test_custom_board_invalid_400(self):
        status, payload = self._post('/api/game/new', {
            'players': ['Amy', 'Bob'],
            'ladders': {'5': 2},  # downward ladder
            'size': 10,
        })
        self.assertEqual(status, 400)

    def test_reset_clears_game(self):
        self._post('/api/game/new', {'players': ['Amy', 'Bob']})
        status, payload = self._post('/api/game/reset', {})
        self.assertEqual(status, 200)
        status, _ = self._get_json('/api/game')
        self.assertEqual(status, 404)

    def test_unknown_route_404(self):
        status, _ = self._get('/api/nope')
        self.assertEqual(status, 404)

    def test_full_game_to_win_via_api(self):
        self._post('/api/game/new', {'players': ['Amy', 'Bob']})
        # Drive a deterministic game to completion: each turn force the exact
        # roll to win if reachable, otherwise step forward onto a non-snake
        # square so progress is strictly monotonic and the loop terminates.
        for _ in range(300):
            status, state = self._get_json('/api/game')
            if state['finished']:
                break
            size = state['board']['size']
            snakes = {int(k) for k in state['board']['snakes']}
            cur = state['current_player']
            pos = next(p['position'] for p in state['players'] if p['name'] == cur)
            need = size - pos
            if 1 <= need <= 6:
                roll = need
            else:
                roll = next(r for r in range(5, 0, -1) if (pos + r) not in snakes)
            self._post('/api/game/roll', {'roll': roll})
        status, state = self._get_json('/api/game')
        self.assertTrue(state['finished'])
        self.assertIsNotNone(state['winner'])


# ----------------------------------------------------------------------
# Win-odds + replay pure helpers
# ----------------------------------------------------------------------
class TestWinningRolls(unittest.TestCase):
    def test_exact_roll_wins(self):
        self.assertEqual(server.winning_rolls(96), [4])

    def test_on_final_minus_one(self):
        self.assertEqual(server.winning_rolls(99), [1])

    def test_too_far_returns_empty(self):
        self.assertEqual(server.winning_rolls(50), [])

    def test_distance_within_range_wins(self):
        # On a size-12 board a 4 lands exactly on 12 from square 8.
        self.assertEqual(server.winning_rolls(8, size=12), [4])
        # From square 5 the final square is 7 away — no single roll reaches it.
        self.assertEqual(server.winning_rolls(5, size=12), [])

    def test_custom_board_size(self):
        self.assertEqual(server.winning_rolls(8, size=10), [2])


class TestReconstructPositions(unittest.TestCase):
    def test_empty_history(self):
        self.assertEqual(server.reconstruct_positions([]), {})

    def test_uses_latest_move_per_player(self):
        history = [
            {'player': 'Amy', 'to': 3},
            {'player': 'Bob', 'to': 5},
            {'player': 'Amy', 'to': 12},
        ]
        self.assertEqual(server.reconstruct_positions(history), {'Amy': 12, 'Bob': 5})

    def test_matches_live_game(self):
        game = server.Game(['Amy', 'Bob'])
        game.roll(forced=3)   # Amy -> 3
        game.roll(forced=2)   # Bob -> 2
        positions = server.reconstruct_positions(game.history)
        self.assertEqual(positions['Amy'], 3)
        self.assertEqual(positions['Bob'], 2)


# ----------------------------------------------------------------------
# Leaderboard / Hall of Fame
# ----------------------------------------------------------------------
class TestLeaderboard(unittest.TestCase):
    def test_record_increments_wins_and_games(self):
        lb = server.Leaderboard()
        lb.record('Amy', ['Amy', 'Bob'])
        standings = {s['name']: s for s in lb.standings()}
        self.assertEqual(standings['Amy']['wins'], 1)
        self.assertEqual(standings['Amy']['games'], 1)
        self.assertEqual(standings['Bob']['wins'], 0)
        self.assertEqual(standings['Bob']['games'], 1)

    def test_accepts_player_dicts(self):
        lb = server.Leaderboard()
        lb.record('Bob', [{'name': 'Amy'}, {'name': 'Bob'}])
        self.assertEqual(lb.players['Bob']['wins'], 1)

    def test_winner_must_be_a_player(self):
        lb = server.Leaderboard()
        with self.assertRaises(ValueError):
            lb.record('Zoe', ['Amy', 'Bob'])

    def test_ranking_orders_by_wins(self):
        lb = server.Leaderboard()
        lb.record('Amy', ['Amy', 'Bob'])
        lb.record('Bob', ['Amy', 'Bob'])
        lb.record('Bob', ['Amy', 'Bob'])
        standings = lb.standings()
        self.assertEqual(standings[0]['name'], 'Bob')
        self.assertEqual(standings[0]['rank'], 1)
        self.assertEqual(standings[0]['wins'], 2)

    def test_win_rate_computed(self):
        lb = server.Leaderboard()
        lb.record('Amy', ['Amy', 'Bob'])  # Amy 1/1, Bob 0/1
        lb.record('Bob', ['Amy', 'Bob'])  # Amy 1/2, Bob 1/2
        rates = {s['name']: s['win_rate'] for s in lb.standings()}
        self.assertEqual(rates['Amy'], 0.5)
        self.assertEqual(rates['Bob'], 0.5)

    def test_top_limits_results(self):
        lb = server.Leaderboard()
        for name in ['a', 'b', 'c']:
            lb.record(name, ['a', 'b', 'c'])
        self.assertEqual(len(lb.top(2)), 2)

    def test_games_played_counter(self):
        lb = server.Leaderboard()
        lb.record('Amy', ['Amy', 'Bob'])
        lb.record('Bob', ['Amy', 'Bob'])
        self.assertEqual(lb.to_dict()['games_played'], 2)

    def test_round_trip_serialization(self):
        lb = server.Leaderboard()
        lb.record('Amy', ['Amy', 'Bob'])
        restored = server.Leaderboard.from_dict(lb.to_dict())
        self.assertEqual(restored.players['Amy']['wins'], 1)
        self.assertEqual(restored.games_played, 1)

    def test_from_dict_tolerates_empty(self):
        lb = server.Leaderboard.from_dict({})
        self.assertEqual(lb.standings(), [])
        self.assertEqual(lb.games_played, 0)


class TestLeaderboardPersistence(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.remove(self.path)
        self._orig = server.LEADERBOARD_PATH
        server.LEADERBOARD_PATH = self.path

    def tearDown(self):
        server.LEADERBOARD_PATH = self._orig
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_save_and_load_round_trip(self):
        lb = server.Leaderboard()
        lb.record('Amy', ['Amy', 'Bob'])
        server.save_leaderboard(lb)
        loaded = server.load_leaderboard()
        self.assertEqual(loaded.players['Amy']['wins'], 1)

    def test_load_missing_returns_empty(self):
        lb = server.load_leaderboard()
        self.assertEqual(lb.standings(), [])

    def test_load_corrupt_returns_empty(self):
        with open(self.path, 'w') as f:
            f.write('{ not json')
        self.assertEqual(server.load_leaderboard().standings(), [])

    def test_clear_removes_file(self):
        server.save_leaderboard(server.Leaderboard())
        self.assertTrue(os.path.exists(self.path))
        server.clear_leaderboard()
        self.assertFalse(os.path.exists(self.path))


# ----------------------------------------------------------------------
# New HTTP endpoints: leaderboard, history, hint
# ----------------------------------------------------------------------
class TestHttpExtensions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fd, cls.state_path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.remove(cls.state_path)
        cls._orig_state = server.STATE_PATH
        server.STATE_PATH = cls.state_path

        fd, cls.lb_path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        os.remove(cls.lb_path)
        cls._orig_lb = server.LEADERBOARD_PATH
        server.LEADERBOARD_PATH = cls.lb_path

        cls.httpd = server.make_server(0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        server.STATE_PATH = cls._orig_state
        server.LEADERBOARD_PATH = cls._orig_lb
        for p in (cls.state_path, cls.lb_path):
            if os.path.exists(p):
                os.remove(p)

    def setUp(self):
        self._post('/api/game/reset', {})
        self._post('/api/leaderboard/reset', {})

    def _url(self, path):
        return 'http://127.0.0.1:%d%s' % (self.port, path)

    def _post(self, path, body):
        data = json.dumps(body).encode('utf-8')
        req = urllib.request.Request(self._url(path), data=data, method='POST',
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode('utf-8'))

    def _get_json(self, path):
        try:
            with urllib.request.urlopen(self._url(path)) as resp:
                return resp.status, json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode('utf-8'))

    def _drive_to_win(self):
        """Force the active game to a deterministic win and return the winner."""
        for _ in range(300):
            status, state = self._get_json('/api/game')
            if state['finished']:
                return state['winner']
            size = state['board']['size']
            snakes = {int(k) for k in state['board']['snakes']}
            cur = state['current_player']
            pos = next(p['position'] for p in state['players'] if p['name'] == cur)
            need = size - pos
            roll = need if 1 <= need <= 6 else next(
                r for r in range(5, 0, -1) if (pos + r) not in snakes)
            self._post('/api/game/roll', {'roll': roll})
        return None

    # -- leaderboard -----------------------------------------------------
    def test_leaderboard_starts_empty(self):
        status, payload = self._get_json('/api/leaderboard')
        self.assertEqual(status, 200)
        self.assertEqual(payload['standings'], [])
        self.assertEqual(payload['games_played'], 0)

    def test_winning_a_game_records_leaderboard(self):
        self._post('/api/game/new', {'players': ['Amy', 'Bob']})
        winner = self._drive_to_win()
        self.assertIsNotNone(winner)
        status, payload = self._get_json('/api/leaderboard')
        self.assertEqual(payload['games_played'], 1)
        names = {s['name']: s for s in payload['standings']}
        self.assertEqual(names[winner]['wins'], 1)
        self.assertEqual(sum(s['games'] for s in payload['standings']), 2)

    def test_leaderboard_reset_clears(self):
        self._post('/api/game/new', {'players': ['Amy', 'Bob']})
        self._drive_to_win()
        self._post('/api/leaderboard/reset', {})
        status, payload = self._get_json('/api/leaderboard')
        self.assertEqual(payload['standings'], [])

    # -- history ---------------------------------------------------------
    def test_history_endpoint_lists_moves(self):
        self._post('/api/game/new', {'players': ['Amy', 'Bob']})
        self._post('/api/game/roll', {'roll': 3})
        self._post('/api/game/roll', {'roll': 2})
        status, payload = self._get_json('/api/game/history')
        self.assertEqual(status, 200)
        self.assertEqual(payload['count'], 2)
        self.assertEqual(payload['positions']['Amy'], 3)
        self.assertEqual(payload['positions']['Bob'], 2)

    def test_history_without_game_404(self):
        status, _ = self._get_json('/api/game/history')
        self.assertEqual(status, 404)

    # -- hint ------------------------------------------------------------
    def test_hint_reports_winning_roll(self):
        # Empty size-10 board: Amy rolls a 6 (keeps the turn), landing on 6,
        # so the only winning roll from there is a 4 (6 + 4 == 10).
        self._post('/api/game/new',
                   {'players': ['Amy', 'Bob'], 'ladders': {}, 'snakes': {}, 'size': 10})
        self._post('/api/game/roll', {'roll': 6})  # Amy -> 6, rolled 6 keeps turn
        status, payload = self._get_json('/api/game/hint')
        self.assertEqual(status, 200)
        self.assertEqual(payload['player'], 'Amy')
        self.assertEqual(payload['position'], 6)
        self.assertEqual(payload['winning_rolls'], [4])

    def test_hint_without_game_404(self):
        status, _ = self._get_json('/api/game/hint')
        self.assertEqual(status, 404)


if __name__ == '__main__':
    unittest.main()
