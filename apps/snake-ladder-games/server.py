"""Snake & Ladder game — HTTP server + JSON API (Python 3 standard library only).

Run with:  python3 server.py   (serves on http://localhost:8000)

The core game engine (board, dice, move resolution, turn order, win detection)
lives in plain functions/classes so it is fully unit-testable without the network.
"""

import json
import os
import random
import threading
import http.server
import socketserver
from http import HTTPStatus

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(BASE_DIR, 'index.html')
STATE_PATH = os.path.join(BASE_DIR, 'game.json')

BOARD_SIZE = 100
DIE_MIN = 1
DIE_MAX = 6

# Classic Snakes & Ladders board.
# Ladders move a player UP (bottom square -> top square).
LADDERS = {
    1: 38, 4: 14, 9: 31, 21: 42, 28: 84,
    36: 44, 51: 67, 71: 91, 80: 100,
}
# Snakes move a player DOWN (head square -> tail square).
SNAKES = {
    16: 6, 47: 26, 49: 11, 56: 53, 62: 19,
    64: 60, 87: 24, 93: 73, 95: 75, 98: 78,
}

# Combined transition map: square -> destination square.
BOARD = {}
BOARD.update(LADDERS)
BOARD.update(SNAKES)


def square_kind(square, ladders=None, snakes=None):
    """Return 'ladder', 'snake', or None for a given landing square.

    Defaults to the classic module-level board, but accepts custom
    ladder/snake maps so it works for custom boards too.
    """
    ladders = LADDERS if ladders is None else ladders
    snakes = SNAKES if snakes is None else snakes
    if square in ladders:
        return 'ladder'
    if square in snakes:
        return 'snake'
    return None


def roll_die(rng=None):
    """Roll a single fair die (1-6). Accepts an injectable RNG for determinism."""
    rng = rng or random
    return rng.randint(DIE_MIN, DIE_MAX)


def resolve_move(position, roll, ladders=None, snakes=None, size=None):
    """Pure move resolution. Given a current position and a die roll,
    return a dict describing the outcome.

    Rules implemented:
      * A player must land EXACTLY on the final square to win. A roll that
        would overshoot the final square forfeits the move (player stays put).
      * After advancing, if the landing square is a snake head or ladder
        bottom, the player is transported to the connected square.

    ``ladders``/``snakes``/``size`` default to the classic 100-square board
    but may be overridden for custom boards.
    """
    ladders = LADDERS if ladders is None else ladders
    snakes = SNAKES if snakes is None else snakes
    size = BOARD_SIZE if size is None else size

    if roll < DIE_MIN or roll > DIE_MAX:
        raise ValueError('roll must be between %d and %d' % (DIE_MIN, DIE_MAX))

    target = position + roll
    if target > size:
        # Overshoot — cannot move, must land exactly on the final square.
        return {
            'from': position,
            'rolled': roll,
            'after_dice': position,
            'to': position,
            'event': 'overshoot',
            'won': False,
        }

    after_dice = target
    event = 'move'
    final = target
    kind = square_kind(target, ladders, snakes)
    if kind == 'ladder':
        final = ladders[target]
        event = 'ladder'
    elif kind == 'snake':
        final = snakes[target]
        event = 'snake'

    return {
        'from': position,
        'rolled': roll,
        'after_dice': after_dice,
        'to': final,
        'event': event,
        'won': final == size,
    }


def winning_rolls(position, size=None):
    """Return the die value(s) that would land EXACTLY on the final square
    from ``position``. Because a single die is rolled, this is at most one
    value (the empty list means no single roll can win from here).
    """
    size = BOARD_SIZE if size is None else size
    need = size - position
    return [need] if DIE_MIN <= need <= DIE_MAX else []


def reconstruct_positions(history):
    """Replay a move history into the final {player: position} mapping.

    Pure helper used by the replay/history view: a player's final position is
    simply the ``to`` square of their most recent recorded move.
    """
    positions = {}
    for rec in history:
        name = rec.get('player')
        if name is not None:
            positions[name] = rec.get('to')
    return positions


def validate_board(ladders, snakes, size):
    """Validate a custom board. Returns normalized (ladders, snakes, size)
    with integer keys/values, or raises ValueError describing the problem.
    """
    try:
        size = int(size)
    except (TypeError, ValueError):
        raise ValueError('board size must be an integer')
    if size < 2:
        raise ValueError('board size must be at least 2')

    def _norm(raw, name):
        out = {}
        if raw is None:
            return out
        if not isinstance(raw, dict):
            raise ValueError('%s must be a mapping of square -> square' % name)
        for k, v in raw.items():
            try:
                src, dst = int(k), int(v)
            except (TypeError, ValueError):
                raise ValueError('%s entries must be integers' % name)
            if not (1 <= src <= size) or not (1 <= dst <= size):
                raise ValueError('%s squares must be within 1..%d' % (name, size))
            if src == size:
                raise ValueError('%s cannot start on the final square' % name)
            out[src] = dst
        return out

    ladders = _norm(ladders, 'ladders')
    snakes = _norm(snakes, 'snakes')

    for src, dst in ladders.items():
        if dst <= src:
            raise ValueError('ladder at %d must lead upward' % src)
    for src, dst in snakes.items():
        if dst >= src:
            raise ValueError('snake at %d must lead downward' % src)

    overlap = set(ladders) & set(snakes)
    if overlap:
        raise ValueError('square(s) %s are both a ladder and a snake'
                         % ', '.join(str(s) for s in sorted(overlap)))

    return ladders, snakes, size


def player_achievements(player, won=False):
    """Derive the badge list a player has earned from their counters.

    Pure helper: badges are a deterministic function of a player's ladder/snake
    counters plus whether they won. Returned sorted for stable output.
    """
    badges = set()
    ladders = player.get('ladders_climbed', 0)
    snakes = player.get('snakes_bitten', 0)
    rolls = player.get('rolls', 0)
    if ladders >= 1:
        badges.add('climbed_ladder')
    if ladders >= 3:
        badges.add('ladder_master')
    if snakes >= 1:
        badges.add('snake_bitten')
    if snakes >= 3:
        badges.add('snake_magnet')
    if won:
        badges.add('champion')
        if snakes == 0:
            badges.add('flawless')
        if rolls and rolls <= 7:
            badges.add('speedrunner')
    return sorted(badges)


class Game:
    """A single Snake & Ladder game session for 2+ players."""

    def __init__(self, players, ladders=None, snakes=None, size=None, rng=None,
                 bots=None):
        names = [str(p).strip() for p in players if str(p).strip()]
        if len(names) < 2:
            raise ValueError('a game needs at least 2 players')
        if len(names) > 6:
            raise ValueError('a game supports at most 6 players')
        if len(set(names)) != len(names):
            raise ValueError('player names must be unique')

        # Board selection. With no overrides we use the classic 100-square
        # board verbatim; otherwise the (possibly custom) board is validated.
        if ladders is None and snakes is None and size is None:
            self.ladders, self.snakes, self.size = dict(LADDERS), dict(SNAKES), BOARD_SIZE
        else:
            self.ladders, self.snakes, self.size = validate_board(
                LADDERS if ladders is None else ladders,
                SNAKES if snakes is None else snakes,
                BOARD_SIZE if size is None else size)

        self.players = [{'name': n, 'position': 0, 'rolls': 0,
                         'ladders_climbed': 0, 'snakes_bitten': 0} for n in names]

        # Bot players are auto-playable. Any name not in the roster is rejected
        # so a typo can't silently create a bot nobody controls.
        bot_names = [str(b).strip() for b in (bots or []) if str(b).strip()]
        unknown = [b for b in bot_names if b not in names]
        if unknown:
            raise ValueError('bot(s) %s are not players in this game'
                             % ', '.join(unknown))
        self.bots = set(bot_names)

        self.current = 0
        self.winner = None
        self.history = []
        self._undo_stack = []
        self.rng = rng or random

    def is_bot(self, name):
        """True if the named player is computer-controlled."""
        return name in self.bots

    # -- derived views ---------------------------------------------------
    def stats(self):
        """Aggregate game-wide counters, useful for a scoreboard."""
        return {
            'total_rolls': sum(p.get('rolls', 0) for p in self.players),
            'moves': len(self.history),
            'ladders_climbed': sum(p.get('ladders_climbed', 0) for p in self.players),
            'snakes_bitten': sum(p.get('snakes_bitten', 0) for p in self.players),
        }

    def standings(self):
        """Players ranked by board position (furthest ahead first)."""
        ranked = sorted(self.players, key=lambda p: p['position'], reverse=True)
        return [{'name': p['name'], 'position': p['position'], 'rank': i + 1}
                for i, p in enumerate(ranked)]

    def achievements(self):
        """Map each player name to their earned badge list."""
        return {p['name']: player_achievements(p, won=(self.winner == p['name']))
                for p in self.players}

    # -- serialization ---------------------------------------------------
    def to_dict(self):
        current_name = self.players[self.current]['name']
        players = []
        for p in self.players:
            entry = dict(p)
            entry['is_bot'] = self.is_bot(p['name'])
            entry['achievements'] = player_achievements(
                p, won=(self.winner == p['name']))
            players.append(entry)
        return {
            'players': players,
            'current': self.current,
            'current_player': current_name,
            'current_is_bot': self.is_bot(current_name),
            'winner': self.winner,
            'finished': self.winner is not None,
            'history': list(self.history),
            'board': {'ladders': self.ladders, 'snakes': self.snakes, 'size': self.size},
            'stats': self.stats(),
            'standings': self.standings(),
            'bots': sorted(self.bots),
            'can_undo': bool(self._undo_stack),
        }

    @classmethod
    def from_dict(cls, data, rng=None):
        names = [p['name'] for p in data['players']]
        board = data.get('board') or {}
        game = cls(names,
                   ladders=board.get('ladders'),
                   snakes=board.get('snakes'),
                   size=board.get('size'),
                   rng=rng,
                   bots=data.get('bots'))
        # Restore raw player counters (drop any derived keys from to_dict).
        keep = ('name', 'position', 'rolls', 'ladders_climbed', 'snakes_bitten')
        game.players = [{k: p[k] for k in keep if k in p} for p in data['players']]
        game.current = data.get('current', 0)
        game.winner = data.get('winner')
        game.history = list(data.get('history', []))
        return game

    # -- gameplay --------------------------------------------------------
    def roll(self, forced=None):
        """Advance the current player by a die roll (or a forced value).

        Returns a move record. Raises RuntimeError once the game is finished.
        """
        if self.winner is not None:
            raise RuntimeError('game is already finished')

        # Capture a full snapshot so the move can be undone exactly.
        snapshot = self._snapshot()

        value = forced if forced is not None else roll_die(self.rng)
        player = self.players[self.current]
        outcome = resolve_move(player['position'], value,
                               self.ladders, self.snakes, self.size)
        player['position'] = outcome['to']
        player['rolls'] = player.get('rolls', 0) + 1
        if outcome['event'] == 'ladder':
            player['ladders_climbed'] = player.get('ladders_climbed', 0) + 1
        elif outcome['event'] == 'snake':
            player['snakes_bitten'] = player.get('snakes_bitten', 0) + 1

        record = dict(outcome)
        record['player'] = player['name']

        extra_turn = False
        if outcome['won']:
            self.winner = player['name']
        elif value == DIE_MAX:
            # Rolling the maximum grants another turn.
            extra_turn = True
        if not outcome['won'] and not extra_turn:
            self.current = (self.current + 1) % len(self.players)

        record['extra_turn'] = extra_turn
        record['next_player'] = None if self.winner else self.players[self.current]['name']
        self.history.append(record)
        self._undo_stack.append(snapshot)
        return record

    def auto_roll(self):
        """Roll on behalf of the current player, who must be a bot.

        Raises RuntimeError if the game is finished or the current player is
        human (so a human's turn can never be silently auto-played).
        """
        if self.winner is not None:
            raise RuntimeError('game is already finished')
        if not self.is_bot(self.players[self.current]['name']):
            raise RuntimeError('current player is not a bot')
        return self.roll()

    def _snapshot(self):
        """Deep-copy the mutable state needed to reverse one roll."""
        return {
            'players': [dict(p) for p in self.players],
            'current': self.current,
            'winner': self.winner,
            'history_len': len(self.history),
        }

    def undo(self):
        """Revert the most recent roll. Raises RuntimeError if there is none."""
        if not self._undo_stack:
            raise RuntimeError('nothing to undo')
        snap = self._undo_stack.pop()
        self.players = [dict(p) for p in snap['players']]
        self.current = snap['current']
        self.winner = snap['winner']
        del self.history[snap['history_len']:]
        return self.to_dict()


# ----------------------------------------------------------------------
# Monte-Carlo simulation / win odds
# ----------------------------------------------------------------------
def simulate_game(players, ladders=None, snakes=None, size=None, rng=None,
                  max_rolls=100000):
    """Play one full game to completion with random rolls and report the result.

    Returns ``{'winner', 'rolls', 'finished'}``. ``finished`` is False only if
    the (extraordinarily unlikely) ``max_rolls`` safety cap was hit first — this
    guarantees termination even for pathological custom boards.
    """
    game = Game(players, ladders=ladders, snakes=snakes, size=size, rng=rng)
    rolls = 0
    while game.winner is None and rolls < max_rolls:
        game.roll()
        rolls += 1
    return {
        'winner': game.winner,
        'rolls': rolls,
        'finished': game.winner is not None,
    }


def win_probabilities(players, ladders=None, snakes=None, size=None,
                      trials=200, rng=None):
    """Estimate each player's win probability over ``trials`` random games.

    Returns a list ranked by probability. Only games that actually finished
    count toward the denominator so a capped run can't skew the odds.
    """
    if trials < 1:
        raise ValueError('trials must be at least 1')
    rng = rng or random
    # Build one game to get canonical (stripped) player names and to surface
    # any board/roster validation error before running the heavy loop.
    canonical = [p['name'] for p in
                 Game(players, ladders=ladders, snakes=snakes, size=size).players]
    wins = {name: 0 for name in canonical}
    completed = 0
    for _ in range(trials):
        result = simulate_game(players, ladders, snakes, size, rng=rng)
        if result['winner'] is not None:
            wins[result['winner']] += 1
            completed += 1
    ranked = sorted(canonical, key=lambda n: (-wins[n], n))
    return [{
        'name': name,
        'wins': wins[name],
        'probability': round(wins[name] / completed, 3) if completed else 0.0,
    } for name in ranked]


# ----------------------------------------------------------------------
# Persistence helpers
# ----------------------------------------------------------------------
def load_game(rng=None):
    if not os.path.exists(STATE_PATH):
        return None
    try:
        with open(STATE_PATH, 'r') as f:
            data = json.load(f)
        return Game.from_dict(data, rng=rng)
    except (json.JSONDecodeError, OSError, KeyError, ValueError):
        return None


def save_game(game):
    try:
        with open(STATE_PATH, 'w') as f:
            json.dump(game.to_dict(), f, indent=2)
    except OSError:
        pass


def clear_game():
    try:
        if os.path.exists(STATE_PATH):
            os.remove(STATE_PATH)
    except OSError:
        pass


# ----------------------------------------------------------------------
# Leaderboard / Hall of Fame
# ----------------------------------------------------------------------
LEADERBOARD_PATH = os.path.join(BASE_DIR, 'leaderboard.json')


class Leaderboard:
    """Persistent cross-game record of wins and games played per player.

    Recorded once each time a game is won; powers the Hall of Fame view.
    """

    def __init__(self, entries=None):
        # name -> {'wins': int, 'games': int}
        self.players = {}
        self.games_played = 0
        if entries:
            for name, rec in entries.items():
                rec = rec or {}
                self.players[str(name)] = {
                    'wins': int(rec.get('wins', 0) or 0),
                    'games': int(rec.get('games', 0) or 0),
                }

    def record(self, winner, players):
        """Record a finished game. ``players`` is a list of player dicts or
        names; ``winner`` must be one of them. Every participant's game count
        increments; the winner additionally gains a win.
        """
        names = [p['name'] if isinstance(p, dict) else str(p) for p in players]
        names = [n for n in names if n]
        winner = str(winner)
        if winner not in names:
            raise ValueError('winner must be one of the players')
        for n in names:
            rec = self.players.setdefault(n, {'wins': 0, 'games': 0})
            rec['games'] += 1
        self.players[winner]['wins'] += 1
        self.games_played += 1
        return self.standings()

    def standings(self):
        """Players ranked by wins (then games played, then name)."""
        ranked = sorted(self.players.items(),
                        key=lambda kv: (-kv[1]['wins'], -kv[1]['games'], kv[0]))
        out = []
        for i, (name, rec) in enumerate(ranked):
            wins, games = rec['wins'], rec['games']
            out.append({
                'name': name,
                'wins': wins,
                'games': games,
                'rank': i + 1,
                'win_rate': round(wins / games, 3) if games else 0.0,
            })
        return out

    def top(self, n=10):
        return self.standings()[:n]

    def to_dict(self):
        return {
            'players': {k: dict(v) for k, v in self.players.items()},
            'games_played': self.games_played,
            'standings': self.standings(),
        }

    @classmethod
    def from_dict(cls, data):
        data = data or {}
        lb = cls(entries=data.get('players'))
        lb.games_played = int(data.get('games_played', 0) or 0)
        return lb


def load_leaderboard():
    if not os.path.exists(LEADERBOARD_PATH):
        return Leaderboard()
    try:
        with open(LEADERBOARD_PATH, 'r') as f:
            return Leaderboard.from_dict(json.load(f))
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        return Leaderboard()


def save_leaderboard(lb):
    try:
        with open(LEADERBOARD_PATH, 'w') as f:
            json.dump(lb.to_dict(), f, indent=2)
    except OSError:
        pass


def clear_leaderboard():
    try:
        if os.path.exists(LEADERBOARD_PATH):
            os.remove(LEADERBOARD_PATH)
    except OSError:
        pass


# ----------------------------------------------------------------------
# HTTP layer
# ----------------------------------------------------------------------
class RequestHandler(http.server.BaseHTTPRequestHandler):
    server_version = 'SnakeLadderHTTP/1.0'
    # Each handler instance shares the server-level in-memory game + lock.

    def log_message(self, fmt, *args):
        pass

    @property
    def _state(self):
        return self.server.game_state

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, body):
        data = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode('utf-8'))

    # -- routing ---------------------------------------------------------
    def do_GET(self):
        if self.path in ('/', '/index.html'):
            try:
                with open(INDEX_PATH, 'r', encoding='utf-8') as f:
                    self._send_html(HTTPStatus.OK, f.read())
            except OSError:
                self._send_html(HTTPStatus.NOT_FOUND, '<h1>index.html not found</h1>')
            return

        if self.path == '/api/board':
            self._send_json(HTTPStatus.OK,
                            {'ladders': LADDERS, 'snakes': SNAKES, 'size': BOARD_SIZE})
            return

        if self.path == '/api/game':
            with self._state.lock:
                game = self._state.game
                if game is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {'error': 'no active game'})
                    return
                self._send_json(HTTPStatus.OK, game.to_dict())
            return

        if self.path == '/api/leaderboard':
            with self._state.lock:
                self._send_json(HTTPStatus.OK, self._state.leaderboard.to_dict())
            return

        if self.path == '/api/game/history':
            with self._state.lock:
                game = self._state.game
                if game is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {'error': 'no active game'})
                    return
                self._send_json(HTTPStatus.OK, {
                    'history': list(game.history),
                    'count': len(game.history),
                    'positions': reconstruct_positions(game.history),
                })
            return

        if self.path == '/api/game/hint':
            with self._state.lock:
                game = self._state.game
                if game is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {'error': 'no active game'})
                    return
                player = game.players[game.current]
                self._send_json(HTTPStatus.OK, {
                    'player': player['name'],
                    'position': player['position'],
                    'winning_rolls': winning_rolls(player['position'], game.size),
                })
            return

        if self.path == '/api/game/achievements':
            with self._state.lock:
                game = self._state.game
                if game is None:
                    self._send_json(HTTPStatus.NOT_FOUND, {'error': 'no active game'})
                    return
                self._send_json(HTTPStatus.OK, {'achievements': game.achievements()})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {'error': 'not found'})

    def do_POST(self):
        if self.path == '/api/game/new':
            self._handle_new()
            return
        if self.path == '/api/game/roll':
            self._handle_roll()
            return
        if self.path == '/api/game/auto':
            self._handle_auto()
            return
        if self.path == '/api/game/simulate':
            self._handle_simulate()
            return
        if self.path == '/api/game/reset':
            self._handle_reset()
            return
        if self.path == '/api/game/undo':
            self._handle_undo()
            return
        if self.path == '/api/leaderboard/reset':
            self._handle_leaderboard_reset()
            return
        self._send_json(HTTPStatus.NOT_FOUND, {'error': 'not found'})

    # -- handlers --------------------------------------------------------
    def _handle_new(self):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return
        players = data.get('players')
        if not isinstance(players, list):
            self._send_json(HTTPStatus.BAD_REQUEST,
                            {'error': 'players must be a list of names'})
            return
        try:
            game = Game(players,
                        ladders=data.get('ladders'),
                        snakes=data.get('snakes'),
                        size=data.get('size'),
                        bots=data.get('bots'))
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': str(exc)})
            return
        with self._state.lock:
            self._state.game = game
            save_game(game)
            self._send_json(HTTPStatus.OK, game.to_dict())

    def _handle_roll(self):
        try:
            data = self._read_body()
        except (json.JSONDecodeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'invalid JSON body'})
            return

        forced = data.get('roll') if isinstance(data, dict) else None
        if forced is not None:
            try:
                forced = int(forced)
            except (TypeError, ValueError):
                self._send_json(HTTPStatus.BAD_REQUEST, {'error': 'roll must be an integer'})
                return
            if forced < DIE_MIN or forced > DIE_MAX:
                self._send_json(HTTPStatus.BAD_REQUEST,
                                {'error': 'roll must be between %d and %d' % (DIE_MIN, DIE_MAX)})
                return

        with self._state.lock:
            game = self._state.game
            if game is None:
                self._send_json(HTTPStatus.NOT_FOUND, {'error': 'no active game'})
                return
            try:
                move = game.roll(forced=forced)
            except RuntimeError as exc:
                self._send_json(HTTPStatus.CONFLICT, {'error': str(exc)})
                return
            save_game(game)
            if move.get('won'):
                # Immortalize the result in the persistent Hall of Fame.
                self._state.leaderboard.record(game.winner, game.players)
                save_leaderboard(self._state.leaderboard)
            self._send_json(HTTPStatus.OK, {'move': move, 'state': game.to_dict()})

    def _handle_undo(self):
        with self._state.lock:
            game = self._state.game
            if game is None:
                self._send_json(HTTPStatus.NOT_FOUND, {'error': 'no active game'})
                return
            try:
                state = game.undo()
            except RuntimeError as exc:
                self._send_json(HTTPStatus.CONFLICT, {'error': str(exc)})
                return
            save_game(game)
            self._send_json(HTTPStatus.OK, {'state': state})

    def _handle_reset(self):
        with self._state.lock:
            self._state.game = None
            clear_game()
            self._send_json(HTTPStatus.OK, {'ok': True})

    def _handle_leaderboard_reset(self):
        with self._state.lock:
            self._state.leaderboard = Leaderboard()
            clear_leaderboard()
            self._send_json(HTTPStatus.OK, {'ok': True})


class _GameState:
    """Server-scoped holder for the active game + a lock for thread safety."""

    def __init__(self):
        self.game = None
        self.leaderboard = Leaderboard()
        self.lock = threading.Lock()


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(port=0):
    server = ThreadingHTTPServer(('', port), RequestHandler)
    server.game_state = _GameState()
    server.game_state.game = load_game()
    server.game_state.leaderboard = load_leaderboard()
    return server


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '8000'))
    httpd = make_server(port)
    print('Snake & Ladder server ready on http://localhost:{}'.format(
        httpd.server_address[1]))
    httpd.serve_forever()
