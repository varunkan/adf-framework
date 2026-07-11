import { describe, it, expect, beforeEach } from 'vitest';
import { buildApp } from '../server/app.mjs';

let app;

beforeEach(async () => {
  app = await buildApp();
  await app.ready();
});

describe('snake-ladder-games API', () => {
  it('returns board metadata', async () => {
    const res = await app.inject({ method: 'GET', url: '/api/snake-ladder-games/board' });
    expect(res.statusCode).toBe(200);
    const body = res.json();
    expect(body.size).toBe(100);
    expect(typeof body.snakes).toBe('object');
    expect(typeof body.ladders).toBe('object');
  });

  it('creates a game with valid player count', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/snake-ladder-games/games',
      payload: { playerCount: 2 }
    });
    expect(res.statusCode).toBe(201);
    const body = res.json();
    expect(body.id).toBeGreaterThan(0);
    expect(body.playerCount).toBe(2);
    expect(body.positions).toEqual([0, 0]);
    expect(body.status).toBe('active');
  });

  it('rejects invalid player count (400)', async () => {
    const res = await app.inject({
      method: 'POST',
      url: '/api/snake-ladder-games/games',
      payload: { playerCount: 1 }
    });
    expect(res.statusCode).toBe(400);
  });

  it('returns 404 for unknown game', async () => {
    const res = await app.inject({
      method: 'GET',
      url: '/api/snake-ladder-games/games/99999'
    });
    expect(res.statusCode).toBe(404);
  });

  it('rolls dice and advances the current player', async () => {
    const create = await app.inject({
      method: 'POST',
      url: '/api/snake-ladder-games/games',
      payload: { playerCount: 2 }
    });
    const game = create.json();

    const roll = await app.inject({
      method: 'POST',
      url: `/api/snake-ladder-games/games/${game.id}/roll`,
      payload: { dice: 3 }
    });
    expect(roll.statusCode).toBe(200);
    const body = roll.json();
    expect(body.move.player).toBe(0);
    expect(body.move.dice).toBe(3);
    expect(body.move.from).toBe(0);
    expect(body.move.to).toBe(3);
    expect(body.game.currentPlayer).toBe(1);
  });

  it('rejects invalid dice value (400)', async () => {
    const create = await app.inject({
      method: 'POST',
      url: '/api/snake-ladder-games/games',
      payload: { playerCount: 2 }
    });
    const game = create.json();
    const res = await app.inject({
      method: 'POST',
      url: `/api/snake-ladder-games/games/${game.id}/roll`,
      payload: { dice: 9 }
    });
    expect(res.statusCode).toBe(400);
  });

  it('detects a winner when reaching cell 100', async () => {
    const create = await app.inject({
      method: 'POST',
      url: '/api/snake-ladder-games/games',
      payload: { playerCount: 2 }
    });
    const game = create.json();
    const id = game.id;

    let current = game;
    let safety = 0;
    while (current.status === 'active' && safety < 500) {
      safety++;
      const pos = current.positions[current.currentPlayer];
      const need = 100 - pos;
      const dice = need >= 6 ? 6 : need >= 1 ? need : 1;
      const r = await app.inject({
        method: 'POST',
        url: `/api/snake-ladder-games/games/${id}/roll`,
        payload: { dice }
      });
      current = r.json().game;
    }
    expect(current.status).toBe('finished');
    expect(current.winner === 0 || current.winner === 1).toBe(true);
  });

  it('returns move history', async () => {
    const create = await app.inject({
      method: 'POST',
      url: '/api/snake-ladder-games/games',
      payload: { playerCount: 2 }
    });
    const game = create.json();
    await app.inject({
      method: 'POST',
      url: `/api/snake-ladder-games/games/${game.id}/roll`,
      payload: { dice: 2 }
    });
    const res = await app.inject({
      method: 'GET',
      url: `/api/snake-ladder-games/games/${game.id}/moves`
    });
    expect(res.statusCode).toBe(200);
    const moves = res.json();
    expect(Array.isArray(moves)).toBe(true);
    expect(moves.length).toBe(1);
    expect(moves[0].dice).toBe(2);
  });
});
