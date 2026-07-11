import { db } from '../db.mjs';
import { resolvePosition, BOARD_SIZE, SNAKES, LADDERS } from '../board.mjs';

function serializeGame(row) {
  return {
    id: row.id,
    playerCount: row.player_count,
    currentPlayer: row.current_player,
    positions: JSON.parse(row.positions),
    winner: row.winner,
    status: row.status,
    createdAt: row.created_at
  };
}

export default async function snakeLadderGames(app) {
  const base = '/snake-ladder-games';

  // Board metadata (snakes & ladders)
  app.get(`${base}/board`, async () => {
    return { size: BOARD_SIZE, snakes: SNAKES, ladders: LADDERS };
  });

  // Create a new game
  app.post(`${base}/games`, async (request, reply) => {
    const body = request.body || {};
    const playerCount = Number(body.playerCount);
    if (!Number.isInteger(playerCount) || playerCount < 2 || playerCount > 4) {
      return reply.code(400).send({ error: 'playerCount must be an integer between 2 and 4' });
    }
    const positions = new Array(playerCount).fill(0);
    const info = db.prepare(
      'INSERT INTO games (player_count, current_player, positions, status) VALUES (?, ?, ?, ?)'
    ).run(playerCount, 0, JSON.stringify(positions), 'active');
    const row = db.prepare('SELECT * FROM games WHERE id = ?').get(info.lastInsertRowid);
    return reply.code(201).send(serializeGame(row));
  });

  // List games
  app.get(`${base}/games`, async () => {
    const rows = db.prepare('SELECT * FROM games ORDER BY id DESC').all();
    return rows.map(serializeGame);
  });

  // Get a single game
  app.get(`${base}/games/:id`, async (request, reply) => {
    const id = Number(request.params.id);
    const row = db.prepare('SELECT * FROM games WHERE id = ?').get(id);
    if (!row) return reply.code(404).send({ error: 'game not found' });
    return serializeGame(row);
  });

  // Roll dice for the current player
  app.post(`${base}/games/:id/roll`, async (request, reply) => {
    const id = Number(request.params.id);
    const row = db.prepare('SELECT * FROM games WHERE id = ?').get(id);
    if (!row) return reply.code(404).send({ error: 'game not found' });
    if (row.status !== 'active') {
      return reply.code(400).send({ error: 'game is already finished' });
    }

    const body = request.body || {};
    let dice = body.dice;
    if (dice === undefined || dice === null) {
      dice = Math.floor(Math.random() * 6) + 1;
    } else {
      dice = Number(dice);
      if (!Number.isInteger(dice) || dice < 1 || dice > 6) {
        return reply.code(400).send({ error: 'dice must be an integer between 1 and 6' });
      }
    }

    const positions = JSON.parse(row.positions);
    const player = row.current_player;
    const from = positions[player];
    const { to, jumped } = resolvePosition(from, dice);
    positions[player] = to;

    let winner = row.winner;
    let status = row.status;
    if (to === BOARD_SIZE) {
      winner = player;
      status = 'finished';
    }

    const nextPlayer = status === 'finished'
      ? player
      : (player + 1) % row.player_count;

    db.prepare(
      'UPDATE games SET positions = ?, current_player = ?, winner = ?, status = ? WHERE id = ?'
    ).run(JSON.stringify(positions), nextPlayer, winner, status, id);

    db.prepare(
      'INSERT INTO moves (game_id, player, dice, from_pos, to_pos, jumped) VALUES (?, ?, ?, ?, ?, ?)'
    ).run(id, player, dice, from, to, jumped);

    const updated = db.prepare('SELECT * FROM games WHERE id = ?').get(id);
    return reply.code(200).send({
      game: serializeGame(updated),
      move: { player, dice, from, to, jumped: !!jumped }
    });
  });

  // Move history for a game
  app.get(`${base}/games/:id/moves`, async (request, reply) => {
    const id = Number(request.params.id);
    const row = db.prepare('SELECT * FROM games WHERE id = ?').get(id);
    if (!row) return reply.code(404).send({ error: 'game not found' });
    const moves = db.prepare('SELECT * FROM moves WHERE game_id = ? ORDER BY id ASC').all(id);
    return moves.map((m) => ({
      id: m.id,
      player: m.player,
      dice: m.dice,
      from: m.from_pos,
      to: m.to_pos,
      jumped: !!m.jumped,
      createdAt: m.created_at
    }));
  });
}
